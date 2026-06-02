"""30D feature extraction from V8 snapshots for Pattern Memory.

Bridge between the V8 snapshot structure and the 30D invariant vector.
Extracts raw numeric values (with encoding for categorical fields) ready
for Z-score normalization. Verified against FINAL_SPEC_VECTORIZER.md.

System B (Neuro-Symbolic Oracle) must remain BLIND to System A's V8 scores
(see PATTERN_MEMORY_INTEGRATION_FULL_SPEC.md §1.2). The vector therefore
contains 30 pure structural/physics factors only - no setup/ignition/total
scores or V8 penalty internals leak into the cosine-recall space.
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ── 30D Feature Specification (code-verified) ──────────────────────
# NOTE: V8 score factors are deliberately EXCLUDED. System B is blind to
# System A's heuristic scores (spec §1.2). Pure physics factors only.
VECTOR_FEATURES = {
    "structure": [
        "zs_count",               # snap["chan"]["zs_count"]
        "bi_count",               # snap["chan"]["bi_count"]
        "seg_count",              # snap["chan"]["seg_count"]
        "pivot_pct_in_range",     # snap["chan"]["pivot"]["pct_in_range"]
        "pivot_range_width",      # DERIVED: chan["pivot"]["range"][1] - [0]
        "pivot_core_width",       # DERIVED: chan["pivot"]["core_range"][1] - [0]
        "trend_type_encoded",     # DERIVED: chan["trend_type"] -> numeric
        "stage_code_encoded",     # DERIVED: chan["stage_code"] -> numeric
    ],
    "volume": [
        "cvd",                    # snap["volume"]["consecutive_vol_days"]
        "vol_ratio_5d",           # snap["volume"]["vol_ratio_5d"]
        "shrink_days",            # snap["volume"]["shrink_days"]
        "fake_out_days",          # snap["volume"]["fake_out_days"]
        "vol_up_down_ratio",      # snap["momentum"]["vol_up_down_ratio"]
    ],
    "momentum": [
        "rsi",                    # snap["indicators"]["rsi"]["value"]
        "macd_hist",              # snap["indicators"]["macd"]["hist"]
        "adx",                    # snap["indicators"]["adx"]["value"]
        "bb_pct_b",               # snap["indicators"]["bb"]["pct_b"]
        "rsi_momentum_5d",        # snap["momentum"]["rsi_momentum_5d"]
        "consecutive_up_days",    # snap["momentum"]["consecutive_up_days"]
        "return_1d",              # snap["momentum"]["return_1d"]
    ],
    "risk": [
        "atr_ratio_pct",          # snap["risk"]["atr_ratio_pct"]
        "bias_60",                # snap["risk"]["bias_60"]
        "max_drawdown_60d",       # snap["risk"]["max_drawdown_60d"]
        "downside_std_20d",       # snap["risk"]["downside_std_20d"]
    ],
    "chan": [
        "bsp_side_encoded",       # DERIVED: chan["bsp"]["latest"]["side"] -> 1/-1/0
        "bsp_type_t1",            # DERIVED: "1buy" or "1sell" in chan["bsp"]["latest"]["types"]
        "bsp_type_t2",            # DERIVED: "2buy" or "2sell" in types list
        "bsp_type_t3",            # DERIVED: "3buy" or "3sell" in types list
        "macd_divergence",        # DERIVED: chan["macd_divergence"]["divergence"] -> 1/0
        "macd_area_ratio",        # chan["macd_divergence"]["area_ratio"]
    ],
}

# Flat ordered list — 30 dimensions total
FEATURE_NAMES_ORDERED: list[str] = []
for _group_names in VECTOR_FEATURES.values():
    FEATURE_NAMES_ORDERED.extend(_group_names)

assert len(FEATURE_NAMES_ORDERED) == 30, f"Expected 30 features, got {len(FEATURE_NAMES_ORDERED)}"

# Encoding maps
TREND_TYPE_MAP: dict[str, float] = {
    # CamelCase (Rust WalkTrendType)
    "UpTrend": 2.0,
    "DownTrend": 0.0,
    "Consolidation": 1.0,
    # SCREAMING_SNAKE (Python bridge / some Rust outputs)
    "UP_TREND": 2.0,
    "DOWN_TREND": 0.0,
    "CONSOLIDATION": 1.0,
    # snake_case (Rust trend_code)
    "up_trend": 2.0,
    "down_trend": 0.0,
    "consolidation": 1.0,
    # Special
    "UNKNOWN": 0.5,
    "ERROR": 0.5,
}

STAGE_CODE_MAP: dict[str, float] = {
    "forming": 1.0,
    "developing": 2.0,
    "mature": 3.0,
    "complete": 4.0,
    "insufficient": 0.0,
    "error": 0.0,
}

# Dimension index boundaries for CoST disentanglement
STRUCTURE_SLICE = slice(0, 8)
VOLUME_SLICE = slice(8, 13)
MOMENTUM_SLICE = slice(13, 20)
RISK_SLICE = slice(20, 24)
CHAN_SLICE = slice(24, 30)


def _safe_get(d: dict | None, *keys, default=np.nan):
    """Safely navigate nested dict. Returns default if any key is missing."""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current if current is not None else default


def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float, returning default for non-finite or non-numeric values."""
    try:
        v = float(value)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """Coerce to int, returning default for non-numeric values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _encode_bsp_side(side) -> float:
    """'买' or 'buy' -> 1, '卖' or 'sell' -> -1, None/other -> 0."""
    if side is None:
        return 0.0
    s = str(side)
    if s in ("买", "buy"):
        return 1.0
    if s in ("卖", "sell"):
        return -1.0
    return 0.0


def _encode_stage_code(stage: str) -> float:
    """forming -> 1, developing -> 2, mature -> 3, complete -> 4, other -> 0."""
    return STAGE_CODE_MAP.get(str(stage), 0.0)


def _encode_trend_type(trend_type: str) -> float:
    """UpTrend/UP_TREND -> 2, Consolidation/CONSOLIDATION -> 1, DownTrend/DOWN_TREND -> 0."""
    return TREND_TYPE_MAP.get(str(trend_type), 0.5)


def _has_bsp_type(types_list: list, tier: int) -> float:
    """Check if T-prefix BSP tier exists in types list. Returns 1.0 or 0.0.

    Matches both 'T1'/'T2'/'T3' (current Rust format) and legacy
    '1buy'/'1sell' (test format).
    """
    if not isinstance(types_list, list):
        return 0.0
    prefix = f"T{tier}"
    legacy_buy = f"{tier}buy"
    legacy_sell = f"{tier}sell"
    for t in types_list:
        s = str(t)
        if s.startswith(prefix) or s == legacy_buy or s == legacy_sell:
            return 1.0
    return 0.0


def extract_feature_vector(snapshot: dict) -> dict:
    """Extract 30D feature vector from a V8 snapshot.

    Parameters
    ----------
    snapshot : dict
        Complete V8 snapshot dict containing: chan, volume, indicators,
        momentum, v8_score.

    Returns
    -------
    dict
        {
            "raw": np.ndarray (30-D, unnormalized, NaN for missing),
            "feature_names": list[str] (30 items, in order),
            "metadata": {
                "v8_grade": str,
                "symbol": str,
                "as_of_date": str,
                "period": str,
                "chan_trend_type": str,
                "chan_bsp_side": str,
                "chan_bsp_types": list,
            },
            "missing_features": list[str],
        }

    Missing features are filled with NaN (handled by normalizer).
    """
    if not isinstance(snapshot, dict):
        raise TypeError(f"Expected dict, got {type(snapshot).__name__}")

    chan = snapshot.get("chan") or {}
    volume = snapshot.get("volume") or {}
    indicators = snapshot.get("indicators") or {}
    momentum = snapshot.get("momentum") or {}
    risk = snapshot.get("risk") or {}
    v8_score = snapshot.get("v8_score") or {}

    pivot = chan.get("pivot") or {}
    bsp_latest = _safe_get(chan, "bsp", "latest", default={})
    if not isinstance(bsp_latest, dict):
        bsp_latest = {}
    bsp_types_raw = bsp_latest.get("types") if isinstance(bsp_latest, dict) else None
    bsp_types = bsp_types_raw if isinstance(bsp_types_raw, list) else None
    macd_div = chan.get("macd_divergence") or {}
    missing: list[str] = []
    raw_values: list[float] = []

    # ── Structure (8d) ──────────────────────────────────────────────
    val = _safe_get(chan, "zs_count", default=np.nan)
    raw_values.append(_to_float(val, default=np.nan if val is np.nan else 0.0))
    if val is np.nan or chan.get("zs_count") is None:
        missing.append("zs_count")

    val = _safe_get(chan, "bi_count", default=np.nan)
    raw_values.append(_to_float(val, default=np.nan if val is np.nan else 0.0))
    if val is np.nan or chan.get("bi_count") is None:
        missing.append("bi_count")

    val = _safe_get(chan, "seg_count", default=np.nan)
    raw_values.append(_to_float(val, default=np.nan if val is np.nan else 0.0))
    if val is np.nan or chan.get("seg_count") is None:
        missing.append("seg_count")

    val = _safe_get(chan, "pivot", "pct_in_range", default=np.nan)
    raw_values.append(_to_float(val, default=np.nan if val is np.nan else 0.0))
    if val is np.nan:
        missing.append("pivot_pct_in_range")

    # DERIVED: pivot_range_width = range[1] - range[0]
    raw_range = pivot.get("range")
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        raw_values.append(float(raw_range[1]) - float(raw_range[0]))
    else:
        raw_values.append(np.nan)
        missing.append("pivot_range_width")

    # DERIVED: pivot_core_width = core_range[1] - core_range[0]
    raw_core = pivot.get("core_range")
    if isinstance(raw_core, (list, tuple)) and len(raw_core) == 2:
        raw_values.append(float(raw_core[1]) - float(raw_core[0]))
    else:
        raw_values.append(np.nan)
        missing.append("pivot_core_width")

    # DERIVED: trend_type_encoded
    trend_type_raw = chan.get("trend_type")
    if trend_type_raw is not None:
        raw_values.append(_encode_trend_type(trend_type_raw))
    else:
        raw_values.append(np.nan)
        missing.append("trend_type_encoded")

    # DERIVED: stage_code_encoded
    stage_code_raw = chan.get("stage_code")
    if stage_code_raw is not None:
        raw_values.append(_encode_stage_code(stage_code_raw))
    else:
        raw_values.append(np.nan)
        missing.append("stage_code_encoded")

    # ── Volume (5d) ─────────────────────────────────────────────────
    val = volume.get("consecutive_vol_days")
    if val is not None:
        raw_values.append(float(_to_int(val)))
    else:
        raw_values.append(np.nan)
        missing.append("cvd")

    val = volume.get("vol_ratio_5d")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("vol_ratio_5d")

    val = volume.get("shrink_days")
    if val is not None:
        raw_values.append(float(_to_int(val)))
    else:
        raw_values.append(np.nan)
        missing.append("shrink_days")

    val = volume.get("fake_out_days")
    if val is not None:
        raw_values.append(float(_to_int(val)))
    else:
        raw_values.append(np.nan)
        missing.append("fake_out_days")

    val = momentum.get("vol_up_down_ratio")
    if val is not None:
        raw_values.append(_to_float(val, default=1.0))
    else:
        raw_values.append(np.nan)
        missing.append("vol_up_down_ratio")

    # ── Momentum (7d) ───────────────────────────────────────────────
    val = _safe_get(indicators, "rsi", "value", default=np.nan)
    if val is not np.nan:
        raw_values.append(_to_float(val, default=50.0))
    else:
        raw_values.append(np.nan)
        missing.append("rsi")

    val = _safe_get(indicators, "macd", "hist", default=np.nan)
    if val is not np.nan:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("macd_hist")

    val = _safe_get(indicators, "adx", "value", default=np.nan)
    if val is not np.nan:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("adx")

    val = _safe_get(indicators, "bb", "pct_b", default=np.nan)
    if val is not np.nan:
        raw_values.append(_to_float(val, default=0.5))
    else:
        raw_values.append(np.nan)
        missing.append("bb_pct_b")

    val = momentum.get("rsi_momentum_5d")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("rsi_momentum_5d")

    val = momentum.get("consecutive_up_days")
    if val is not None:
        raw_values.append(float(_to_int(val)))
    else:
        raw_values.append(np.nan)
        missing.append("consecutive_up_days")

    val = momentum.get("return_1d")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("return_1d")

    # ── Risk (4d) ───────────────────────────────────────────────────
    # Deliberately use physical risk fields, not V8 penalty internals, so
    # System B remains blind to System A's score logic.
    val = risk.get("atr_ratio_pct")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("atr_ratio_pct")

    val = risk.get("bias_60")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("bias_60")

    val = risk.get("max_drawdown_60d")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("max_drawdown_60d")

    val = risk.get("downside_std_20d")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("downside_std_20d")

    # ── Chan Theory (6d) ────────────────────────────────────────────
    # DERIVED: bsp_side_encoded
    bsp_side_raw = bsp_latest.get("side") if isinstance(bsp_latest, dict) else None
    if bsp_side_raw is not None:
        raw_values.append(_encode_bsp_side(bsp_side_raw))
    else:
        raw_values.append(np.nan)
        missing.append("bsp_side_encoded")

    # DERIVED: bsp_type_t1/t2/t3
    if bsp_types is not None:
        raw_values.append(_has_bsp_type(bsp_types, 1))
        raw_values.append(_has_bsp_type(bsp_types, 2))
        raw_values.append(_has_bsp_type(bsp_types, 3))
    else:
        # Only mark as missing if bsp_latest had no types key at all
        for tier_label in ("bsp_type_t1", "bsp_type_t2", "bsp_type_t3"):
            raw_values.append(np.nan)
            missing.append(tier_label)

    # DERIVED: macd_divergence bool -> 1/0
    div_val = macd_div.get("divergence")
    if div_val is not None:
        raw_values.append(1.0 if bool(div_val) else 0.0)
    else:
        raw_values.append(np.nan)
        missing.append("macd_divergence")

    val = macd_div.get("area_ratio")
    if val is not None:
        raw_values.append(_to_float(val))
    else:
        raw_values.append(np.nan)
        missing.append("macd_area_ratio")

    raw = np.array(raw_values, dtype=np.float64)

    metadata = {
        "v8_grade": str(v8_score.get("grade", "")),
        "symbol": str(snapshot.get("symbol", "")),
        "as_of_date": str(snapshot.get("as_of_date", "")),
        "period": str(snapshot.get("period", "day")),
        "chan_trend_type": str(trend_type_raw or ""),
        "chan_bsp_side": str(bsp_side_raw or ""),
        "chan_bsp_types": list(bsp_types) if isinstance(bsp_types, list) else [],
    }

    return {
        "raw": raw,
        "feature_names": list(FEATURE_NAMES_ORDERED),
        "metadata": metadata,
        "missing_features": missing,
    }
