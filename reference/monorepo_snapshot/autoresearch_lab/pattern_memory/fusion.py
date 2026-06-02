"""Kronos -> PCA -> fused vector writeback (nightly closing-loop).

Pipeline position (PATTERN_MEMORY_INTEGRATION_FULL_SPEC §2 / §6):

    kronos_embed (overnight)  ->  pattern_snapshot.kronos_vector
    z-normalize physics       ->  pattern_snapshot.z_feature_vector
    THIS MODULE (nightly)     ->  fit PCA on the kronos batch,
                                  fuse PCA(kronos) ++ z-features,
                                  write back pattern_snapshot.fused_vector
    Go hot path               ->  reads fused top-k via a nightly JSON cache
                                  (never imports Python at runtime, §6)

The fused vector is `PCA(kronos, dim=16)` concatenated with the 30D z-normalized
physics vector, giving a 46D representation used for `query_top_k(embedding_type
="fused")`. When split metadata is present, the PCA basis is fitted on train rows
only and then applied to all rows in the same stats cohort.
"""

from __future__ import annotations

import logging

import numpy as np

from autoresearch_lab.kronos.pca_fusion import (
    _FUSION_VERSION,
    fit_pca,
    persist_pca_artifact,
    transform_fused,
)
from autoresearch_lab.pattern_memory.store import PatternStore

logger = logging.getLogger(__name__)

_PCA_DIM = 16


def build_fused_vectors(
    store: PatternStore,
    *,
    pca_dim: int = _PCA_DIM,
    fit_stats_id: str | None = None,
    fit_end_date: str | None = None,
    kronos_weight: float = 0.35,
    z_weight: float = 0.65,
    commit: bool = True,
) -> dict:
    """Fit PCA on train-safe kronos vectors and write fused vectors back.

    Parameters
    ----------
    store : PatternStore
        Open DuckDB-backed pattern store.
    pca_dim : int
        Target PCA dimensionality for the Kronos component (default 16).
    fit_stats_id : str | None
        Optional stats cohort to use for fitting and writeback.
    fit_end_date : str | None
        Optional inclusive max as_of_date for PCA fitting. If omitted and a
        single stats_id has persisted feature stats, that train_end is used.
    kronos_weight / z_weight : float
        Explicit cosine block weights. Defaults keep the experimental Kronos
        leg below the blind symbolic z leg until it proves alpha.
    commit : bool
        When True, persist the fused vectors via ``store.update_fused_vector``.
        When False, compute only (dry run) and report what *would* be written.

    Returns
    -------
    dict
        Summary: {n_inputs, n_written, pca_dim, fused_dim, fitted, skipped}.
        ``fitted`` is False (and nothing written) when there are no eligible
        rows or the kronos vectors are not uniformly shaped.
    """
    rows = store.iter_fusion_inputs()
    n_inputs = len(rows)
    if n_inputs == 0:
        logger.info("build_fused_vectors: no rows with both kronos_vector and z_feature_vector")
        return {"n_inputs": 0, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                "fitted": False, "skipped": 0}

    # Validate uniform kronos dimensionality before stacking.
    kronos_lens = {len(r["kronos_vector"]) for r in rows}
    if len(kronos_lens) != 1:
        logger.warning(
            "build_fused_vectors: non-uniform kronos vector lengths %s; aborting fit",
            sorted(kronos_lens),
        )
        return {"n_inputs": n_inputs, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                "fitted": False, "skipped": n_inputs}

    if fit_stats_id is None:
        stats_ids = {r.get("stats_id") for r in rows if r.get("stats_id")}
        if len(stats_ids) == 1:
            fit_stats_id = next(iter(stats_ids))
        elif len(stats_ids) > 1:
            logger.warning(
                "build_fused_vectors: multiple stats_id cohorts %s; pass fit_stats_id explicitly",
                sorted(stats_ids),
            )
            return {"n_inputs": n_inputs, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                    "fitted": False, "skipped": n_inputs}

    effective_fit_end = fit_end_date
    if effective_fit_end is None and fit_stats_id:
        stat_row = store.con.execute(
            "SELECT train_end FROM pattern_feature_stats WHERE stats_id = ? LIMIT 1",
            [fit_stats_id],
        ).fetchone()
        if stat_row and stat_row[0]:
            effective_fit_end = str(stat_row[0])[:10]
        else:
            logger.warning(
                "build_fused_vectors: stats_id=%s has no persisted train_end; refusing PCA fit",
                fit_stats_id,
            )
            return {"n_inputs": n_inputs, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                    "fitted": False, "skipped": n_inputs}

    cohort_rows = [r for r in rows if fit_stats_id is None or r.get("stats_id") == fit_stats_id]
    fit_rows = [
        r for r in cohort_rows
        if effective_fit_end is None or str(r.get("as_of_date", ""))[:10] <= effective_fit_end
    ]
    if not fit_rows:
        logger.warning(
            "build_fused_vectors: no PCA fit rows for stats_id=%s fit_end=%s",
            fit_stats_id,
            effective_fit_end,
        )
        return {"n_inputs": n_inputs, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                "fitted": False, "skipped": n_inputs}
    if len(fit_rows) < 2:
        logger.warning(
            "build_fused_vectors: need at least 2 PCA fit rows, got %d",
            len(fit_rows),
        )
        return {"n_inputs": n_inputs, "n_written": 0, "pca_dim": pca_dim, "fused_dim": 0,
                "fitted": False, "skipped": n_inputs}

    kronos_matrix = np.asarray([r["kronos_vector"] for r in fit_rows], dtype=np.float64)
    pca = fit_pca(kronos_matrix, n_components=pca_dim)

    fit_start = min(str(r.get("as_of_date", ""))[:10] for r in fit_rows)
    fit_end = effective_fit_end or max(str(r.get("as_of_date", ""))[:10] for r in fit_rows)
    pca_record = persist_pca_artifact(
        pca,
        stats_id=fit_stats_id,
        fit_start=fit_start,
        fit_end=fit_end,
        n_fit_rows=len(fit_rows),
    )
    if commit:
        store.save_pca_artifact(pca_record)

    n_written = 0
    skipped = 0
    fused_dim = 0
    z_ref_len: int | None = None
    for r in cohort_rows:
        z_vec = np.asarray(r["z_feature_vector"], dtype=np.float64)
        # Keep the physics component width consistent across the batch.
        if z_ref_len is None:
            z_ref_len = z_vec.shape[0]
        elif z_vec.shape[0] != z_ref_len:
            logger.warning(
                "build_fused_vectors: %s has z-vector len %d != %d; skipping",
                r["pattern_id"], z_vec.shape[0], z_ref_len,
            )
            skipped += 1
            continue

        kronos_vec = np.asarray(r["kronos_vector"], dtype=np.float64)
        fused = transform_fused(
            kronos_vec,
            pca,
            z_vec,
            kronos_weight=kronos_weight,
            z_weight=z_weight,
        )
        fused_dim = fused.shape[0]
        if commit:
            store.update_fused_vector(
                r["pattern_id"],
                [float(x) for x in fused],
                pca_artifact_id=pca_record["pca_artifact_id"],
                fusion_version=_FUSION_VERSION,
            )
        n_written += 1

    logger.info(
        "build_fused_vectors: fitted PCA(%d) on %d rows, wrote %d fused vectors (dim=%d, stats_id=%s, fit_end=%s, pca_artifact_id=%s, weights=%.2f/%.2f, commit=%s)",
        pca.n_components_, len(fit_rows), n_written, fused_dim,
        fit_stats_id or "*", effective_fit_end or "*", pca_record["pca_artifact_id"],
        kronos_weight, z_weight, commit,
    )
    return {
        "n_inputs": n_inputs,
        "n_written": n_written,
        "pca_dim": int(pca.n_components_),
        "fused_dim": int(fused_dim),
        "fitted": True,
        "skipped": skipped,
        "fit_rows": len(fit_rows),
        "fit_stats_id": fit_stats_id,
        "fit_end_date": effective_fit_end,
        "kronos_weight": kronos_weight,
        "z_weight": z_weight,
        "pca_artifact_id": pca_record["pca_artifact_id"],
        "fusion_version": _FUSION_VERSION,
        "explained_variance_ratio_sum": pca_record["explained_variance_ratio_sum"],
        "artifact_path": pca_record["artifact_path"],
        "artifact_hash": pca_record["artifact_hash"],
    }
