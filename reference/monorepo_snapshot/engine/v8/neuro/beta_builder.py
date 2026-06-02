"""engine.v8.neuro.beta_builder — V8 snapshot → BetaTensor assembly.

Mirrors ``engine.v8.neuro.builder.build_alpha_tensor`` but projects into the
numeric physics hemisphere (left brain) rather than text dimensions (right brain).

Design contract
---------------
1. Reads an already-assembled V8 snapshot dict. Never recomputes physics.
2. No reverse dependency: ``engine/*`` must not import ``autoresearch_lab/*``.
3. Defensive by construction — partial snapshots degrade gracefully.
"""
from __future__ import annotations

from typing import Any

from engine.v8.neuro.beta_schema import (
    BetaChanBsp,
    BetaMomentum,
    BetaRisk,
    BetaScoreRef,
    BetaStructure,
    BetaTensor,
    BetaVolume,
)

__all__ = ["build_beta_tensor"]


def _dig(obj: Any, *paths: str, default: Any = None) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _encode_trend_type(trend_type) -> float:
    m = {"UpTrend": 2.0, "UP_TREND": 2.0, "up_trend": 2.0,
         "Consolidation": 1.0, "CONSOLIDATION": 1.0, "consolidation": 1.0,
         "DownTrend": 0.0, "DOWN_TREND": 0.0, "down_trend": 0.0}
    return m.get(str(trend_type), 0.5)


def _encode_stage_code(stage: str) -> float:
    m = {"forming": 1.0, "developing": 2.0, "mature": 3.0, "complete": 4.0}
    return m.get(str(stage), 0.0)


def _encode_bsp_side(side) -> float:
    if side is None:
        return 0.0
    s = str(side)
    if s in ("买", "buy"):
        return 1.0
    if s in ("卖", "sell"):
        return -1.0
    return 0.0


def _has_bsp_tier(types_list, tier: int) -> float:
    if not isinstance(types_list, list):
        return 0.0
    prefix = f"T{tier}"
    for t in types_list:
        s = str(t)
        if s.startswith(prefix) or s in (f"{tier}buy", f"{tier}sell"):
            return 1.0
    return 0.0


def _derive_pivot_width(pivot: dict, key: str) -> float:
    rng = pivot.get(key) if isinstance(pivot, dict) else None
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        return float(rng[1]) - float(rng[0])
    return 0.0


def _build_structure(snap: dict) -> BetaStructure:
    chan = _dig(snap, "chan", default={})
    pivot = chan.get("pivot") if isinstance(chan, dict) else {}
    return BetaStructure(
        zs_count=_f(_dig(chan, "zs_count")),
        bi_count=_f(_dig(chan, "bi_count")),
        seg_count=_f(_dig(chan, "seg_count")),
        pivot_pct_in_range=_f(_dig(chan, "pivot.pct_in_range")),
        pivot_range_width=_derive_pivot_width(pivot, "range"),
        pivot_core_width=_derive_pivot_width(pivot, "core_range"),
        trend_type_encoded=_encode_trend_type(_dig(chan, "trend_type", "trend", default="")),
        stage_code_encoded=_encode_stage_code(_dig(chan, "stage_code", "stage", default="")),
    )


def _build_volume(snap: dict) -> BetaVolume:
    vol = _dig(snap, "volume", default={})
    mom = _dig(snap, "momentum", default={})
    return BetaVolume(
        cvd=_f(_dig(vol, "consecutive_vol_days")),
        vol_ratio_5d=_f(_dig(vol, "vol_ratio_5d"), 1.0),
        shrink_days=_f(_dig(vol, "shrink_days")),
        fake_out_days=_f(_dig(vol, "fake_out_days")),
        vol_up_down_ratio=_f(_dig(mom, "vol_up_down_ratio"), 1.0),
    )


def _build_momentum(snap: dict) -> BetaMomentum:
    ind = _dig(snap, "indicators", default={})
    mom = _dig(snap, "momentum", default={})
    return BetaMomentum(
        rsi=_f(_dig(ind, "rsi.value"), 50.0),
        macd_hist=_f(_dig(ind, "macd.hist")),
        adx=_f(_dig(ind, "adx.value")),
        bb_pct_b=_f(_dig(ind, "bb.pct_b"), 0.5),
        rsi_momentum_5d=_f(_dig(mom, "rsi_momentum_5d")),
        consecutive_up_days=_f(_dig(mom, "consecutive_up_days")),
        return_1d=_f(_dig(mom, "return_1d")),
    )


def _build_risk(snap: dict) -> BetaRisk:
    v8 = _dig(snap, "v8_score", default={})
    details = v8.get("details") if isinstance(v8, dict) else {}
    tbf = v8.get("toxic_breaker_factors") if isinstance(v8, dict) else None
    tbf_count = float(len(tbf)) if isinstance(tbf, list) else 0.0
    return BetaRisk(
        overheat_index=_f(_dig(v8, "overheat_index")),
        toxic_breaker_count=tbf_count,
        fever_penalty_raw=_f(_dig(details, "fever_penalty_raw")),
        toxic_penalty=_f(_dig(details, "toxic_penalty")),
    )


def _build_chan_bsp(snap: dict) -> BetaChanBsp:
    chan = _dig(snap, "chan", default={})
    bsp_latest = _dig(chan, "bsp.latest", "bsp.latest_confirmed", "bsp.latest_candidate", default={})
    if not isinstance(bsp_latest, dict):
        bsp_latest = {}
    types_raw = bsp_latest.get("types") if isinstance(bsp_latest, dict) else None
    bsp_types = types_raw if isinstance(types_raw, list) else []
    macd_div = chan.get("macd_divergence") if isinstance(chan, dict) else {}
    return BetaChanBsp(
        bsp_side_encoded=_encode_bsp_side(bsp_latest.get("side")),
        bsp_type_t1=_has_bsp_tier(bsp_types, 1),
        bsp_type_t2=_has_bsp_tier(bsp_types, 2),
        bsp_type_t3=_has_bsp_tier(bsp_types, 3),
        macd_divergence=1.0 if bool(macd_div.get("divergence")) else 0.0,
        macd_area_ratio=_f(_dig(macd_div, "area_ratio")),
    )


def _build_score_ref(snap: dict) -> BetaScoreRef:
    v8 = _dig(snap, "v8_score", default={})
    return BetaScoreRef(
        setup_score=_f(_dig(v8, "setup_score")),
        ignition_score=_f(_dig(v8, "ignition_score")),
        left_total=_f(_dig(v8, "left_total")),
        right_total=_f(_dig(v8, "right_total")),
    )


def build_beta_tensor(snap: dict) -> BetaTensor:
    """Project a V8 snapshot dict into the BetaTensor (left-brain physics).

    Missing blocks degrade gracefully to documented defaults; never raises on a
    partial snapshot.
    """
    if not isinstance(snap, dict):
        raise TypeError(f"build_beta_tensor expects a snapshot dict, got {type(snap)!r}")

    return BetaTensor(
        symbol=str(_dig(snap, "symbol", default="UNKNOWN")),
        as_of_date=str(_dig(snap, "as_of_date", "as_of", "timestamp", default="")),
        v8_grade=str(_dig(snap, "v8_score.grade", "v8_grade", default="?")),
        feature_names_json=str(_dig(snap, "feature_names_json", default="[]")),
        structure=_build_structure(snap),
        volume=_build_volume(snap),
        momentum=_build_momentum(snap),
        risk=_build_risk(snap),
        chan_bsp=_build_chan_bsp(snap),
        score_ref=_build_score_ref(snap),
    )
