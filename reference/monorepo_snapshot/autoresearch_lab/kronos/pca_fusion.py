"""PCA-based residual representation fusion.

Kronos embedding (dim=512 for Kronos-small) -> PCA(dim=16) -> concatenate
with symbolic z features (dim=30 by current blind spec) -> fused vector.

Fitted PCA bases are persisted via :func:`persist_pca_artifact` so fused
vectors remain reproducible (``pca_artifact_id`` on ``pattern_snapshot``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

_PCA_DIM = 16
_FUSION_VERSION = "fused_concat_v1"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ARTIFACT_DIR = _PROJECT_ROOT / "data" / "pattern_memory" / "pca_artifacts"


def fit_pca(embeddings: np.ndarray, n_components: int = _PCA_DIM, *, whiten: bool = True):
    """Fit PCA on a batch of embeddings.

    Parameters
    ----------
    embeddings : np.ndarray
        Shape (N, D) batch of raw Kronos embeddings.
    n_components : int
        Target dimensionality (default 16).

    Returns
    -------
    PCA
        Fitted PCA model ready for transform_fused().
    """
    from sklearn.decomposition import PCA

    n_samples, n_features = embeddings.shape
    if n_samples < 2:
        raise ValueError("PCA fusion requires at least 2 fit samples")
    actual_components = min(n_components, n_samples - 1, n_features)
    if actual_components < n_components:
        logger.warning(
            "Reducing PCA components from %d to %d (only %d samples)",
            n_components,
            actual_components,
            n_samples,
        )
    pca = PCA(n_components=actual_components, whiten=whiten)
    pca.fit(embeddings)
    logger.info(
        "PCA fitted: %d -> %d dims, explained variance ratio sum=%.4f",
        n_features,
        actual_components,
        float(pca.explained_variance_ratio_.sum()),
    )
    return pca


def transform_fused(
    kronos_embedding: np.ndarray,
    pca,
    warpcore_features: np.ndarray,
    *,
    kronos_weight: float = 0.35,
    z_weight: float = 0.65,
) -> np.ndarray:
    """Concatenate PCA-reduced Kronos embedding with Warpcore features.

    Both halves are L2-normalised, then explicitly weighted. The weights are
    normalized to sum to one and applied as square-root block weights so cosine
    contribution is controlled by ``kronos_weight`` / ``z_weight`` instead of
    being implicitly locked to 50/50 by geometry.

    Parameters
    ----------
    kronos_embedding : np.ndarray
        Shape (D,) raw Kronos embedding.
    pca : PCA
        Fitted PCA model.
    warpcore_features : np.ndarray
        Shape (W,) warpcore feature vector (34D or extended).

    Returns
    -------
    np.ndarray
        Shape (pca_dim + warpcore_dim,) fused L2-normalised vector.
    """
    if kronos_weight < 0 or z_weight < 0 or (kronos_weight + z_weight) <= 0:
        raise ValueError("kronos_weight and z_weight must be non-negative with positive sum")
    total_weight = kronos_weight + z_weight
    kronos_scale = float(np.sqrt(kronos_weight / total_weight))
    z_scale = float(np.sqrt(z_weight / total_weight))

    kronos_reduced = pca.transform(kronos_embedding.reshape(1, -1))[0]
    kronos_reduced = kronos_reduced / (np.linalg.norm(kronos_reduced) + 1e-8)
    z_normalised = warpcore_features / (np.linalg.norm(warpcore_features) + 1e-8)
    fused = np.concatenate([kronos_reduced * kronos_scale, z_normalised * z_scale])
    return fused / (np.linalg.norm(fused) + 1e-8)


def pca_artifact_payload(pca) -> dict[str, Any]:
    """Serialize a fitted sklearn PCA for JSON persistence."""
    return {
        "n_components": int(pca.n_components_),
        "components": np.asarray(pca.components_, dtype=np.float64).tolist(),
        "mean": np.asarray(pca.mean_, dtype=np.float64).tolist(),
        "explained_variance_ratio": np.asarray(
            pca.explained_variance_ratio_, dtype=np.float64
        ).tolist(),
        "whiten": bool(getattr(pca, "whiten", False)),
    }


def load_pca_from_payload(payload: dict[str, Any]):
    """Reconstruct a sklearn PCA model from :func:`pca_artifact_payload`."""
    from sklearn.decomposition import PCA

    n_components = int(payload["n_components"])
    pca = PCA(n_components=n_components, whiten=bool(payload.get("whiten", False)))
    pca.components_ = np.asarray(payload["components"], dtype=np.float64)
    pca.mean_ = np.asarray(payload["mean"], dtype=np.float64)
    pca.explained_variance_ratio_ = np.asarray(
        payload["explained_variance_ratio"], dtype=np.float64
    )
    pca.n_components_ = n_components
    pca.n_features_in_ = pca.components_.shape[1]
    return pca


def persist_pca_artifact(
    pca,
    *,
    stats_id: str | None,
    fit_start: str | None,
    fit_end: str | None,
    n_fit_rows: int,
    model_repo: str | None = None,
    artifact_dir: Path | None = None,
    pca_artifact_id: str | None = None,
) -> dict[str, Any]:
    """Write PCA basis JSON to disk and return registry metadata."""
    artifact_dir = artifact_dir or _DEFAULT_ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifact_id = pca_artifact_id or f"pca_{uuid.uuid4().hex[:12]}"
    payload = pca_artifact_payload(pca)
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    path = artifact_dir / f"{artifact_id}.json"
    path.write_bytes(blob)

    evr_sum = float(np.sum(pca.explained_variance_ratio_))
    record = {
        "pca_artifact_id": artifact_id,
        "fusion_version": _FUSION_VERSION,
        "stats_id": stats_id,
        "fit_start": fit_start,
        "fit_end": fit_end,
        "n_fit_rows": int(n_fit_rows),
        "n_components": int(pca.n_components_),
        "explained_variance_ratio_sum": round(evr_sum, 6),
        "model_repo": model_repo,
        "artifact_path": str(path),
        "artifact_hash": digest,
    }
    logger.info(
        "Persisted PCA artifact %s (components=%d, evr_sum=%.4f, path=%s)",
        artifact_id,
        record["n_components"],
        evr_sum,
        path,
    )
    return record


def load_pca_artifact(artifact_path: str | Path):
    """Load PCA from a persisted JSON artifact."""
    path = Path(artifact_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return load_pca_from_payload(payload)
