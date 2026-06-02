"""Kronos embedding configuration helpers (stamp + pooling + metadata)."""
from __future__ import annotations

from typing import Any, Literal, Optional

import numpy as np

STAMP_MODES = ("none", "official")
POOLING_MODES = ("last", "mean", "last_k_mean", "concat_last_mean")

StampMode = Literal["none", "official"]
PoolingMode = Literal["last", "mean", "last_k_mean", "concat_last_mean"]

_TIME_COLS = ("minute", "hour", "weekday", "day", "month")
_DEFAULT_LAST_K = 8


def resolve_last_k(pooling_mode: str, last_k: Optional[int]) -> int:
    if pooling_mode != "last_k_mean":
        return _DEFAULT_LAST_K
    k = last_k if last_k is not None else _DEFAULT_LAST_K
    if k < 1:
        raise ValueError(f"last_k must be >= 1, got {k}")
    return k


def build_official_stamp(df) -> np.ndarray:
    """Return float32 stamp array [seq_len, 5] (minute/hour/weekday/day/month)."""
    import pandas as pd

    from autoresearch_lab.kronos.native.kronos import calc_time_stamps

    ts = _extract_timestamps(df)
    stamp_df = calc_time_stamps(ts)
    missing = [c for c in _TIME_COLS if c not in stamp_df.columns]
    if missing:
        raise ValueError(f"calc_time_stamps missing columns: {missing}")
    return stamp_df[list(_TIME_COLS)].to_numpy(dtype=np.float32)


def _extract_timestamps(df):
    import pandas as pd

    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index, index=df.index)
    for col in ("timestamp", "date", "datetime", "time"):
        if col in df.columns:
            return pd.to_datetime(df[col], errors="coerce")
    raise ValueError(
        "DataFrame needs DatetimeIndex or one of: timestamp, date, datetime, time"
    )


def pool_context(
    context,
    *,
    pooling_mode: PoolingMode,
    last_k: int = _DEFAULT_LAST_K,
) -> "np.ndarray":
    """Reduce [batch, seq_len, d_model] context to a 1-D embedding."""
    import torch

    if not isinstance(context, torch.Tensor):
        raise TypeError(f"expected torch.Tensor context, got {type(context)!r}")
    if context.ndim != 3 or context.shape[0] != 1:
        raise ValueError(f"expected context shape [1, seq, d_model], got {tuple(context.shape)}")

    seq = context[0]
    if seq.shape[0] == 0:
        raise ValueError("empty sequence in context")

    if pooling_mode == "last":
        return seq[-1].detach().cpu().float().numpy()
    if pooling_mode == "mean":
        return seq.mean(dim=0).detach().cpu().float().numpy()
    if pooling_mode == "last_k_mean":
        k = min(last_k, seq.shape[0])
        return seq[-k:].mean(dim=0).detach().cpu().float().numpy()
    if pooling_mode == "concat_last_mean":
        last_vec = seq[-1]
        mean_vec = seq.mean(dim=0)
        return torch.cat([last_vec, mean_vec], dim=0).detach().cpu().float().numpy()

    raise ValueError(
        f"Invalid pooling_mode {pooling_mode!r}. "
        f"Must be one of {', '.join(POOLING_MODES)}"
    )


def embedding_metadata(
    *,
    model_name: str,
    model_repo: str,
    tokenizer_repo: str,
    embedding_dim: int,
    preprocess_mode: str,
    stamp_mode: StampMode,
    pooling_mode: PoolingMode,
    input_cols: list[str],
    window_length: int,
    last_k: Optional[int] = None,
    output_dim: Optional[int] = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "model_name": model_name,
        "model_repo": model_repo,
        "tokenizer_repo": tokenizer_repo,
        "tokenizer_name": tokenizer_repo,
        "embedding_dim": embedding_dim,
        "output_dim": output_dim if output_dim is not None else embedding_dim,
        "preprocess_mode": preprocess_mode,
        "stamp_mode": stamp_mode,
        "pooling_mode": pooling_mode,
        "input_cols": list(input_cols),
        "window_length": window_length,
    }
    if pooling_mode == "last_k_mean":
        meta["last_k"] = resolve_last_k(pooling_mode, last_k)
    return meta