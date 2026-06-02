"""engine.v8.neuro.builder — V8 snapshot -> Alpha Tensor assembly.

DESIGN CONTRACT
---------------
1. This module *reads* an already-assembled V8 snapshot dict (the live MCP
   `snapshot` / `hapi-edge cli snapshot` Go snapshot-core object, or the offline
   `snapshot_factory._build_snapshot_at` dict). It NEVER recomputes physics.
   Warpcore already produced trap_detection / compression_setup / crash_signals /
   indicators / ls1_supercharged; we only project + serialize.

2. No reverse dependency: engine/* must not import autoresearch_lab/*. The
   regime mapping is therefore re-implemented locally.

3. Defensive by construction. Every field has a documented primary path plus
   secondary fallbacks and a safe default, so a partial snapshot never raises.

KEY PATHS (calibrated 2026-06-01 against `hapi-edge cli snapshot --format json`):
  v8_score.{grade,setup_score,ignition_score,overheat_index,toxic_breaker,
            toxic_breaker_factors}
  chan.{zs_count,stage_code}; chan.bsp.{latest_confirmed,latest,latest_candidate}
  chan_mtf.alignment
  compression_setup.{is_range_compressed,is_bb_squeeze}
  ls1_supercharged.spring.{coiling,launch}
  gann_support.hit
  indicators.macd.state ("金叉持续" / "死叉持续")
  breakout.breakout_60d ; capital_flow.total_net
  momentum.vol_ratio_5d
  trap_detection.pump_fake.{is_trap,trap_type,details,volume_ratio}
  trap_detection.volume_gap.is_gap
  macro_sentinel.{hard_block,indices.CSI300.features.*}
  crash_signals.panic_reversal.detected ; iron_verdict
"""

from __future__ import annotations

from typing import Any

from engine.v8.neuro.schema import (
    AlphaTensor,
    GlobalRegime,
    IgnitionDimension,
    RiskDimension,
    StructureDimension,
    VolumeDimension,
)

__all__ = ["build_alpha_tensor"]

# Broad-market index used for the Global Regime context.
_MARKET_INDEX = "CSI300"


# --------------------------------------------------------------------------- #
# Safe nested access
# --------------------------------------------------------------------------- #
def _dig(obj: Any, *paths: str, default: Any = None) -> Any:
    """Return the first dotted path that resolves to a non-None value."""
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


def _market_features(snap: dict) -> dict:
    """Broad-market index feature block (macro_sentinel.indices.CSI300.features)."""
    feats = _dig(snap, f"macro_sentinel.indices.{_MARKET_INDEX}.features", default=None)
    return feats if isinstance(feats, dict) else {}


# --------------------------------------------------------------------------- #
# Global regime mapping (broad market, not the stock itself)
# --------------------------------------------------------------------------- #
def _market_regime(snap: dict) -> str:
    """bull / bear / range / crash from broad-market index numeric features."""
    f = _market_features(snap)
    ret20 = _f(f.get("ret_20d"))
    slope = _f(f.get("ma20_slope_pct"))
    above = bool(f.get("ma20_above_ma60", False))
    if ret20 <= -15.0:
        return "crash"
    if above and slope > 0.1:
        return "bull"
    if (not above) and slope < -0.1:
        return "bear"
    return "range"


def _vol_regime(snap: dict) -> str:
    """low / normal / high / extreme from broad-market atr_pct buckets."""
    f = _market_features(snap)
    atr_pct = _f(f.get("atr_pct"), 2.0)
    if atr_pct < 2.0:
        return "low"
    if atr_pct < 4.0:
        return "normal"
    if atr_pct < 7.0:
        return "high"
    return "extreme"


# --------------------------------------------------------------------------- #
# Structure dimension
# --------------------------------------------------------------------------- #
def _chan_bsp(snap: dict) -> str:
    """Compose a Chan buy/sell-point phrase from the best available bsp node.

    Priority: confirmed > latest > candidate. Chan ``types`` are string codes
    (e.g. ["T1p"]); we surface them verbatim alongside the 买/卖 side.
    """
    node = _dig(
        snap,
        "chan.bsp.latest_confirmed",
        "chan.bsp.latest",
        "chan.bsp.latest_candidate",
        default=None,
    )
    if not isinstance(node, dict):
        return "无"
    side = node.get("side")
    types = node.get("types") or []
    side_label = "买点" if str(side) in {"买", "buy", "long"} else ("卖点" if side else "")
    type_str = ("·" + "/".join(str(t) for t in types)) if isinstance(types, (list, tuple)) and types else ""
    if not side_label and not type_str:
        return "无"
    return f"缠论{side_label}{type_str}".rstrip("·") or "无"


def _consolidation_phase(snap: dict) -> str:
    stage = _dig(snap, "chan.stage_code", "chan.stage", default="")
    coiling = bool(_dig(snap, "ls1_supercharged.spring.coiling", default=False))
    compressed = bool(_dig(snap, "compression_setup.is_range_compressed", default=False))
    ready = bool(_dig(snap, "compression_setup.is_ready", default=False))
    stage_map = {
        "forming": "震荡构筑",
        "developing": "洗盘吸收",
        "mature": "洗盘吸收就绪",
        "complete": "结构完成",
    }
    base = stage_map.get(str(stage), str(stage) or "震荡")
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
        setup_score=_f(_dig(snap, "v8_score.setup_score")),
        zs_count=_i(_dig(snap, "chan.zs_count")),
        consolidation_phase=_consolidation_phase(snap),
        gann_support=bool(_dig(snap, "gann_support.hit", default=False)),
        bollinger_squeeze=bool(
            _dig(snap, "compression_setup.is_bb_squeeze", "compression_setup.is_range_compressed", default=False)
        ),
        ma_alignment=str(_dig(snap, "chan_mtf.alignment", "ma_alignment", default="缠绕")),
    )


# --------------------------------------------------------------------------- #
# Ignition dimension
# --------------------------------------------------------------------------- #
def _macd_cross(snap: dict) -> str:
    state = _dig(snap, "indicators.macd.state", "momentum.macd_state", default="")
    s = str(state)
    if "金叉" in s or "golden" in s.lower():
        return "golden"
    if "死叉" in s or "dead" in s.lower():
        return "dead"
    return "none"


def _build_ignition(snap: dict) -> IgnitionDimension:
    return IgnitionDimension(
        ignition_score=_f(_dig(snap, "v8_score.ignition_score")),
        macd_cross=_macd_cross(snap),
        ignition_bar_present=bool(
            _dig(snap, "ls1_supercharged.spring.launch", "intraday_volume_structure.launch_signal", default=False)
        ),
        breakout_confirmed=bool(
            _dig(snap, "breakout.breakout_60d", "ls1_supercharged.spring.breakout_60d", default=False)
        ),
        fund_inflow_intensity=_f(
            _dig(snap, "capital_flow.total_net", "fusion_intel_signals.moneyflow_net_large", default=0.0)
        ),
    )


# --------------------------------------------------------------------------- #
# Volume dimension
# --------------------------------------------------------------------------- #
def _build_volume(snap: dict) -> VolumeDimension:
    # pump/dump ratio lives on the trap detector. Only meaningful when a trap is
    # actually flagged; otherwise default to a neutral/healthy 1.0 so a clean
    # stock (volume_ratio == 0.0, no pump event) is not mislabelled fatal.
    pf = _dig(snap, "trap_detection.pump_fake", default={}) or {}
    if isinstance(pf, dict) and bool(pf.get("is_trap")):
        pump_dump = _f(pf.get("volume_ratio"), 1.0)
    else:
        pump_dump = _f(_dig(snap, "ls1_supercharged.three_push.pump_dump_vol_ratio", default=None), 1.0)

    return VolumeDimension(
        volume_ratio_5d=_f(_dig(snap, "momentum.vol_ratio_5d", "volume.volume_ratio_5d", default=1.0), 1.0),
        turnover_rate=_f(_dig(snap, "price.turnover_rate", "turnover_rate", default=0.0)),
        pump_dump_vol_ratio=pump_dump,
        volume_gap_detected=bool(
            _dig(snap, "trap_detection.volume_gap.is_gap", "crash_signals.volume_gap", default=False)
        ),
    )


# --------------------------------------------------------------------------- #
# Risk dimension
# --------------------------------------------------------------------------- #
def _build_risk(snap: dict) -> RiskDimension:
    toxic = bool(_dig(snap, "v8_score.toxic_breaker", default=False))
    if not toxic:
        factors = _dig(snap, "v8_score.toxic_breaker_factors", default=None)
        toxic = bool(factors) if isinstance(factors, (list, tuple, dict)) else bool(factors)

    pf = _dig(snap, "trap_detection.pump_fake", default=None)
    if isinstance(pf, dict):
        is_trap = bool(pf.get("is_trap", False))
        trap_type = pf.get("trap_type") or "none"
        trap_details = pf.get("details") or ""
    else:
        # Offline fallback: infer a fatal pump_fake from three_push ratio.
        pdr = _f(_dig(snap, "ls1_supercharged.three_push.pump_dump_vol_ratio", default=None), 1.0)
        is_trap = pdr < 0.2
        trap_type = "pump_fake" if is_trap else "none"
        trap_details = _dig(snap, "ls1_supercharged.three_push.details", default="") or ""

    return RiskDimension(
        overheat_index=_i(_dig(snap, "v8_score.overheat_index", default=0)),
        is_trap=is_trap,
        trap_type=str(trap_type),
        trap_details=str(trap_details),
        toxic_breaker=toxic,
    )


# --------------------------------------------------------------------------- #
# Global regime dimension
# --------------------------------------------------------------------------- #
def _build_global(snap: dict) -> GlobalRegime:
    systemic = bool(
        _dig(
            snap,
            "macro_sentinel.hard_block",
            "crash_signals.panic_reversal.detected",
            "crash_signals.systemic_risk",
            default=False,
        )
    )
    return GlobalRegime(
        market_regime=_market_regime(snap),
        vol_regime=_vol_regime(snap),
        iron_verdict=str(_dig(snap, "iron_verdict", default="neutral")),
        systemic_risk_flag=systemic,
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_alpha_tensor(snap: dict) -> AlphaTensor:
    """Project a V8 snapshot dict into the 4-dimensional Alpha Tensor.

    Missing blocks degrade gracefully to documented defaults; never raises on a
    partial snapshot. Raises TypeError only on a non-dict argument.
    """
    if not isinstance(snap, dict):
        raise TypeError(f"build_alpha_tensor expects a snapshot dict, got {type(snap)!r}")

    return AlphaTensor(
        symbol=str(_dig(snap, "symbol", default="UNKNOWN")),
        as_of_date=str(_dig(snap, "as_of_date", "as_of", "timestamp", "data_trust.quote_updated_at", default="")),
        v8_grade=str(_dig(snap, "v8_score.grade", "v8_grade", default="?")),
        global_regime=_build_global(snap),
        structure=_build_structure(snap),
        ignition=_build_ignition(snap),
        volume=_build_volume(snap),
        risk=_build_risk(snap),
    )
