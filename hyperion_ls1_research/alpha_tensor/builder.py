"""Snapshot dict -> AlphaTensor projection (read-only; never recomputes LS1 physics)."""

from __future__ import annotations

from typing import Any

from hyperion_ls1_research.alpha_tensor.schema import (
    AlphaTensor,
    GlobalRegime,
    IgnitionDimension,
    RiskDimension,
    StructureDimension,
    VolumeDimension,
)
from hyperion_ls1_research.ls1_contract.schema import dig

__all__ = ["build_alpha_tensor", "PHYSICS_RECOMPUTE_FORBIDDEN"]


PHYSICS_RECOMPUTE_FORBIDDEN = (
    "This module only projects existing snapshot fields. "
    "It must not call Warpcore, LS1, or re-derive trap/compression math."
)


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


def _chan_bsp(snap: dict) -> str:
    node = dig(snap, "chan.bsp.latest_confirmed") or dig(snap, "chan.bsp.latest") or dig(
        snap, "chan.bsp.latest_candidate"
    )
    if not isinstance(node, dict):
        return "无"
    side = node.get("side")
    types = node.get("types") or []
    side_label = "买点" if str(side) in {"买", "buy", "long"} else ("卖点" if side else "")
    type_str = ("·" + "/".join(str(t) for t in types)) if types else ""
    return f"缠论{side_label}{type_str}".rstrip("·") or "无"


def _consolidation_phase(snap: dict) -> str:
    stage = str(dig(snap, "chan.stage_code", default="") or "")
    coiling = bool(dig(snap, "ls1_supercharged.spring.coiling", default=False))
    compressed = bool(dig(snap, "compression_setup.is_range_compressed", default=False))
    ready = bool(dig(snap, "compression_setup.is_ready", default=False))
    stage_map = {
        "forming": "震荡构筑",
        "developing": "洗盘吸收",
        "mature": "洗盘吸收就绪",
        "complete": "结构完成",
    }
    base = stage_map.get(stage, stage or "震荡")
    if ready:
        return f"{base}·就绪"
    if coiling and compressed:
        return f"{base}·盘整压缩"
    if compressed:
        return f"{base}·区间压缩"
    return base


def _build_structure(snap: dict) -> StructureDimension:
    return StructureDimension(
        chan_bsp=_chan_bsp(snap),
        setup_score=_f(dig(snap, "v8_score.setup_score")),
        zs_count=_i(dig(snap, "chan.zs_count")),
        consolidation_phase=_consolidation_phase(snap),
        gann_support=bool(dig(snap, "gann_support.hit", default=False)),
        bollinger_squeeze=bool(
            dig(snap, "compression_setup.is_bb_squeeze")
            or dig(snap, "compression_setup.is_range_compressed", default=False)
        ),
        ma_alignment=str(dig(snap, "chan_mtf.alignment", default="缠绕") or "缠绕"),
    )


def _macd_cross(snap: dict) -> str:
    state = str(dig(snap, "indicators.macd.state", default="") or "")
    if "金叉" in state or "golden" in state.lower():
        return "golden"
    if "死叉" in state or "dead" in state.lower():
        return "dead"
    return "none"


def _build_ignition(snap: dict) -> IgnitionDimension:
    return IgnitionDimension(
        ignition_score=_f(dig(snap, "v8_score.ignition_score")),
        macd_cross=_macd_cross(snap),
        ignition_bar_present=bool(
            dig(snap, "ls1_supercharged.spring.launch")
            or dig(snap, "intraday_volume_structure.launch_signal", default=False)
        ),
        breakout_confirmed=bool(
            dig(snap, "breakout.breakout_60d")
            or dig(snap, "ls1_supercharged.spring.breakout_60d", default=False)
        ),
        fund_inflow_intensity=_f(dig(snap, "capital_flow.total_net", default=0.0)),
    )


def _build_volume(snap: dict) -> VolumeDimension:
    pf = dig(snap, "trap_detection.pump_fake", default={}) or {}
    if isinstance(pf, dict) and bool(pf.get("is_trap")):
        pump_dump = _f(pf.get("volume_ratio"), 1.0)
    else:
        pump_dump = _f(dig(snap, "ls1_supercharged.three_push.pump_dump_vol_ratio"), 1.0)
    return VolumeDimension(
        volume_ratio_5d=_f(dig(snap, "momentum.vol_ratio_5d"), 1.0),
        turnover_rate=_f(dig(snap, "price.turnover_rate")),
        pump_dump_vol_ratio=pump_dump,
        volume_gap_detected=bool(dig(snap, "trap_detection.volume_gap.is_gap", default=False)),
    )


def _build_risk(snap: dict) -> RiskDimension:
    pf = dig(snap, "trap_detection.pump_fake", default={}) or {}
    if isinstance(pf, dict):
        is_trap = bool(pf.get("is_trap", False))
        trap_type = str(pf.get("trap_type") or "none")
        trap_details = str(pf.get("details") or "")
    else:
        pdr = _f(dig(snap, "ls1_supercharged.three_push.pump_dump_vol_ratio"), 1.0)
        is_trap = pdr < 0.2
        trap_type = "pump_fake" if is_trap else "none"
        trap_details = ""
    return RiskDimension(
        overheat_index=_i(dig(snap, "v8_score.overheat_index")),
        is_trap=is_trap,
        trap_type=trap_type,
        trap_details=trap_details,
        toxic_breaker=bool(dig(snap, "v8_score.toxic_breaker", default=False)),
    )


def _build_global(snap: dict) -> GlobalRegime:
    macro = dig(snap, "macro_sentinel", default={}) or {}
    regime = str(macro.get("regime", "range") if isinstance(macro, dict) else "range")
    if regime not in ("bull", "bear", "range", "crash"):
        regime = "range"
    vol = str(macro.get("vol_regime", "normal") if isinstance(macro, dict) else "normal")
    if vol not in ("low", "normal", "high", "extreme"):
        vol = "normal"
    systemic = bool(
        dig(snap, "macro_sentinel.hard_block")
        or dig(snap, "crash_signals.panic_reversal.detected", default=False)
    )
    return GlobalRegime(
        market_regime=regime,  # type: ignore[arg-type]
        vol_regime=vol,  # type: ignore[arg-type]
        iron_verdict=str(dig(snap, "iron_verdict", default="neutral") or "neutral"),
        systemic_risk_flag=systemic,
    )


def build_alpha_tensor(snap: dict) -> AlphaTensor:
    """Project an existing snapshot dict into AlphaTensor. No LS1 recompute."""
    return AlphaTensor(
        symbol=str(snap.get("symbol", "SYNTHETIC.SH")),
        as_of_date=str(snap.get("as_of_date", "2026-01-01 10:00:00")),
        v8_grade=str(dig(snap, "v8_score.grade", default="C") or "C"),
        global_regime=_build_global(snap),
        structure=_build_structure(snap),
        ignition=_build_ignition(snap),
        volume=_build_volume(snap),
        risk=_build_risk(snap),
    )