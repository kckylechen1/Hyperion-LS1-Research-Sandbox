"""KronosExtractor -- dense pattern embeddings from the native Kronos model.

Kronos is a custom time-series foundation model (BSQ tokenizer + decoder
transformer) loaded via huggingface_hub ``PyTorchModelHubMixin`` — NOT the
transformers ``Auto*`` classes (its ``config.json`` carries no ``model_type``).
The native classes are vendored under :mod:`autoresearch_lab.kronos.native`.

Embedding strategy (no forecasting / no prediction — Kronos is used purely as a
representation encoder, per the pattern-memory design):

    OHLCV(+amount) window  -> per-series z-normalize + clip(±5)
                           -> tokenizer.encode(x, half=True) -> [s1_ids, s2_ids]
                           -> model.decode_s1(s1, s2, stamp=None) -> (logits, context)
                           -> context[:, -1, :]  (last-step d_model hidden state)

The resulting ``d_model`` (512 for Kronos-small) vector is the dense Kronos
component later PCA-reduced and fused with the symbolic z-vector
(``autoresearch_lab.pattern_memory.fusion``).

Heavy deps (torch, the native model) are imported lazily so the rest of the
``kronos`` package stays importable in lightweight environments.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from autoresearch_lab.kronos.embedding_config import (
    POOLING_MODES,
    STAMP_MODES,
    PoolingMode,
    StampMode,
    build_official_stamp,
    embedding_metadata,
    pool_context,
    resolve_last_k,
)

logger = logging.getLogger(__name__)

# Native Kronos weights live under the NeoQuasar HF org. The previous
# ``shiyu-coder/Kronos-*`` ids were wrong (that is the GitHub org, not the HF
# model org) and caused every load to fail.
_MODEL_REPOS = {
    "kronos-mini": "NeoQuasar/Kronos-mini",
    "kronos-small": "NeoQuasar/Kronos-small",
    "kronos-base": "NeoQuasar/Kronos-base",
}
# Kronos-small / base share the base tokenizer; mini uses the 2k tokenizer.
_TOKENIZER_REPOS = {
    "kronos-mini": "NeoQuasar/Kronos-Tokenizer-2k",
    "kronos-small": "NeoQuasar/Kronos-Tokenizer-base",
    "kronos-base": "NeoQuasar/Kronos-Tokenizer-base",
}

# radar kline column -> Kronos feature order (open, high, low, close, vol, amount).
# radar exposes 成交额 as ``turnover``; Kronos calls the same field ``amount``.
_FEATURE_COLS = ["open", "high", "low", "close", "volume", "turnover"]
_CLIP = 5.0


class KronosExtractor:
    """Load a native Kronos model + tokenizer and expose ``embed_symbol`` /
    ``embed_batch`` returning dense NumPy embedding vectors.

    Parameters
    ----------
    model_name:
        One of ``kronos-mini`` / ``kronos-small`` / ``kronos-base`` (or a raw
        HF repo id). Defaults to ``kronos-small`` (the locally cached weights).
    tokenizer_name:
        Override the tokenizer repo. Defaults to the tokenizer paired with
        ``model_name``.
    device:
        ``"cpu"``, ``"cuda"``, ``"mps"``, or ``"auto"`` (auto-detected).
    """

    def __init__(
        self,
        model_name: str = "kronos-small",
        tokenizer_name: Optional[str] = None,
        device: str = "auto",
        *,
        stamp_mode: StampMode = "none",
        pooling_mode: PoolingMode = "last",
        last_k: Optional[int] = None,
    ):
        if stamp_mode not in STAMP_MODES:
            raise ValueError(f"stamp_mode must be one of {STAMP_MODES}, got {stamp_mode!r}")
        if pooling_mode not in POOLING_MODES:
            raise ValueError(f"pooling_mode must be one of {POOLING_MODES}, got {pooling_mode!r}")
        self.stamp_mode: StampMode = stamp_mode
        self.pooling_mode: PoolingMode = pooling_mode
        self.last_k = resolve_last_k(pooling_mode, last_k)

        self.model_name = model_name
        self._model_repo = _MODEL_REPOS.get(model_name, model_name)
        self._tokenizer_repo = (
            tokenizer_name
            or _TOKENIZER_REPOS.get(model_name, "NeoQuasar/Kronos-Tokenizer-base")
        )
        self._device = self._resolve_device(device)
        self._model = None
        self._tokenizer = None
        self._peak_memory = 0.0
        
        # Auditing fields (PR 3)
        self.load_mode = "unknown"
        self.load_error = None
        self.embedding_dim = 0
        self.device = str(self._device)
        self.model_repo = self._model_repo
        self.tokenizer_repo = self._tokenizer_repo
        self.feature_cols = list(_FEATURE_COLS)
        self.preprocess_mode = "zscore_norm"
        self._last_embedding_meta: dict[str, Any] = {}

        self._load_model()

    # ------------------------------------------------------------------
    # Device resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device(device: str):
        import torch

        if device == "auto":
            if torch.cuda.is_available():
                return torch.device("cuda")
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return torch.device("mps")
            return torch.device("cpu")
        return torch.device(device)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Load the native Kronos model + tokenizer via PyTorchModelHubMixin."""
        import torch

        from autoresearch_lab.kronos.native import Kronos, KronosTokenizer

        try:
            self._tokenizer = (
                KronosTokenizer.from_pretrained(self._tokenizer_repo).to(self._device).eval()
            )
            self._model = (
                Kronos.from_pretrained(self._model_repo).to(self._device).eval()
            )
            self.load_mode = "pytorch_hub"
            logger.info(
                "Loaded Kronos %s (tokenizer %s) on %s",
                self._model_repo,
                self._tokenizer_repo,
                self._device,
            )
            if self._device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(self._device)
                self._peak_memory = torch.cuda.max_memory_allocated(self._device) / 1e6
        except TypeError as te:
            logger.info("TypeError encountered for %s. Retrying with manual config injection...", self.model_name)
            from huggingface_hub import hf_hub_download
            import json
            try:
                # 1. Download and inject tokenizer config
                tok_config_path = hf_hub_download(repo_id=self._tokenizer_repo, filename="config.json")
                with open(tok_config_path) as f:
                    tok_config = json.load(f)
                self._tokenizer = (
                    KronosTokenizer.from_pretrained(self._tokenizer_repo, **tok_config)
                    .to(self._device)
                    .eval()
                )

                # 2. Download and inject model config
                config_path = hf_hub_download(repo_id=self._model_repo, filename="config.json")
                with open(config_path) as f:
                    config = json.load(f)
                self._model = (
                    Kronos.from_pretrained(self._model_repo, **config)
                    .to(self._device)
                    .eval()
                )
                self.load_mode = "manual_mixin_fallback"
                logger.info(
                    "Loaded Kronos %s (tokenizer %s) via manual config injection on %s",
                    self._model_repo,
                    self._tokenizer_repo,
                    self._device,
                )
                if self._device.type == "cuda":
                    torch.cuda.reset_peak_memory_stats(self._device)
                    self._peak_memory = torch.cuda.max_memory_allocated(self._device) / 1e6
            except Exception as inner_exc:
                self.load_mode = "error"
                self.load_error = f"Manual config fallback failed: {str(inner_exc)}"
                logger.error(
                    "Failed to load Kronos model %s / tokenizer %s even with manual config injection",
                    self._model_repo,
                    self._tokenizer_repo,
                    exc_info=True,
                )
                self._model = None
                self._tokenizer = None
        except Exception as e:
            self.load_mode = "error"
            self.load_error = f"Initial load failed: {str(e)}"
            logger.error(
                "Failed to load Kronos model %s / tokenizer %s",
                self._model_repo,
                self._tokenizer_repo,
                exc_info=True,
            )
            self._model = None
            self._tokenizer = None

        if self._model is not None:
            self.embedding_dim = getattr(self._model, "d_model", 512)


    # ------------------------------------------------------------------
    # Embedding extraction
    # ------------------------------------------------------------------

    def embed_symbol(
        self,
        symbol: str,
        period: str = "day",
        length: int = 512,
    ) -> Optional[np.ndarray]:
        """Return a 1-D float32 Kronos embedding for *symbol* (latest window).

        Loads the most recent ``length`` bars via radar and embeds them. Use
        :meth:`embed_dataframe` directly for point-in-time / historical windows
        (e.g. pattern-memory backfill), where radar's "latest" window would
        introduce look-ahead.
        """
        df = self._load_kline_df(symbol, period, length)
        if df is None:
            return None
        return self.embed_dataframe(df, label=symbol)

    def embed_dataframe(
        self,
        df,
        *,
        label: str = "<df>",
    ) -> Optional[np.ndarray]:
        """Embed a pre-sliced OHLCV(+amount) window supplied as a DataFrame.

        The caller is responsible for point-in-time correctness (the window
        must end at the desired as-of bar). Expects the columns in
        ``_FEATURE_COLS``. Returns a 1-D float32 ``d_model`` vector, or *None*.
        """
        import torch

        if self._model is None or self._tokenizer is None:
            logger.warning("Kronos model not loaded; cannot embed %s", label)
            return None

        x = self._normalize_features(df, label=label)
        if x is None:
            return None

        try:
            xt = torch.from_numpy(x[np.newaxis, :].astype(np.float32)).to(self._device)
            stamp_tensor = None
            if self.stamp_mode == "official":
                stamp_np = build_official_stamp(df)
                if stamp_np.shape[0] != x.shape[0]:
                    raise ValueError(
                        f"stamp length {stamp_np.shape[0]} != feature length {x.shape[0]}"
                    )
                stamp_tensor = torch.from_numpy(stamp_np[np.newaxis, :]).to(self._device)

            with torch.no_grad():
                s1_ids, s2_ids = self._tokenizer.encode(xt, half=True)
                _logits, context = self._model.decode_s1(s1_ids, s2_ids, stamp=stamp_tensor)
                embedding = pool_context(
                    context,
                    pooling_mode=self.pooling_mode,
                    last_k=self.last_k,
                )

            out_dim = int(embedding.shape[0])
            base_dim = int(self.embedding_dim or out_dim)
            self._last_embedding_meta = embedding_metadata(
                model_name=self.model_name,
                model_repo=self.model_repo,
                tokenizer_repo=self.tokenizer_repo,
                embedding_dim=base_dim,
                preprocess_mode=self.preprocess_mode,
                stamp_mode=self.stamp_mode,
                pooling_mode=self.pooling_mode,
                input_cols=self.feature_cols,
                window_length=int(x.shape[0]),
                last_k=self.last_k if self.pooling_mode == "last_k_mean" else None,
                output_dim=out_dim,
            )

            if self._device.type == "cuda":
                self._peak_memory = max(
                    self._peak_memory,
                    torch.cuda.max_memory_allocated(self._device) / 1e6,
                )
            return embedding.astype(np.float32)
        except Exception:
            logger.error("Kronos embedding failed for %s", label, exc_info=True)
            return None

    def embed_batch(
        self,
        symbols: list[str],
        period: str = "day",
        length: int = 512,
    ) -> dict[str, np.ndarray]:
        """Embed multiple symbols, returning ``{symbol: embedding}``."""
        results: dict[str, np.ndarray] = {}
        for sym in symbols:
            try:
                emb = self.embed_symbol(sym, period, length)
                if emb is not None:
                    results[sym] = emb
            except Exception as exc:
                logger.warning("embed_symbol(%s) failed: %s", sym, exc)
        return results

    # ------------------------------------------------------------------
    # Feature loading
    # ------------------------------------------------------------------

    def _load_kline_df(self, symbol: str, period: str, length: int):
        """Load the latest ``length`` bars for *symbol* via radar (live path)."""
        from engine.v8.infra.radar import radar

        try:
            df = radar.load_kline(symbol, period=period, limit=length)
        except Exception:
            logger.debug("Failed to load kline for %s/%s", symbol, period, exc_info=True)
            return None

        if df is None or len(df) == 0:
            logger.warning("No kline data for %s/%s (length=%d)", symbol, period, length)
            return None
        return df

    def _normalize_features(self, df, *, label: str = "<df>") -> Optional[np.ndarray]:
        """Normalize an OHLCV(+amount) DataFrame window into a [T, 6] array.

        Mirrors ``KronosPredictor`` preprocessing: per-series z-normalization
        with a small epsilon, then clip to ``±_CLIP``.
        """
        missing = [c for c in _FEATURE_COLS if c not in df.columns]
        if missing:
            logger.warning("kline for %s missing columns %s; cannot embed", label, missing)
            return None

        feat = df[_FEATURE_COLS].to_numpy(dtype=np.float64)
        if feat.shape[0] == 0:
            return None
        if not np.isfinite(feat).all():
            feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)

        mean = feat.mean(axis=0)
        std = feat.std(axis=0)
        x = (feat - mean) / (std + 1e-5)
        x = np.clip(x, -_CLIP, _CLIP)
        return x.astype(np.float32)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def peak_memory_mb(self) -> float:
        """Return peak GPU memory in MB used by the model tensors."""
        return self._peak_memory

    def get_embedding_metadata(self) -> dict[str, Any]:
        """Metadata for the most recent :meth:`embed_dataframe` call."""
        return dict(self._last_embedding_meta)

    @staticmethod
    def embedding_to_bytes(embedding: np.ndarray) -> bytes:
        """Serialize an embedding vector to a compact ``bytes`` blob."""
        return embedding.astype(np.float32).tobytes()
