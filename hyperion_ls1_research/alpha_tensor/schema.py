"""Sanitized AlphaTensor — five orthogonal domains for Observer / provenance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StructureDimension(BaseModel):
    chan_bsp: str = Field(..., description="Chan buy/sell point phrase (projected)")
    setup_score: float = Field(..., description="Left-side setup score (reference only)")
    zs_count: int = Field(..., description="Chan consolidation count")
    consolidation_phase: str = Field(..., description="Washout / compression phase label")
    gann_support: bool = False
    bollinger_squeeze: bool = False
    ma_alignment: str = "缠绕"


class IgnitionDimension(BaseModel):
    ignition_score: float = Field(..., description="Right-side ignition score (reference)")
    macd_cross: Literal["none", "golden", "dead"] = "none"
    ignition_bar_present: bool = False
    breakout_confirmed: bool = False
    fund_inflow_intensity: float = 0.0


class VolumeDimension(BaseModel):
    volume_ratio_5d: float = 1.0
    turnover_rate: float = 0.0
    pump_dump_vol_ratio: float = 1.0
    volume_gap_detected: bool = False


class RiskDimension(BaseModel):
    overheat_index: int = 0
    is_trap: bool = False
    trap_type: str = "none"
    trap_details: str = ""
    toxic_breaker: bool = False


class GlobalRegime(BaseModel):
    market_regime: Literal["bull", "bear", "range", "crash"] = "range"
    vol_regime: Literal["low", "normal", "high", "extreme"] = "normal"
    iron_verdict: str = "neutral"
    systemic_risk_flag: bool = False


class AlphaTensor(BaseModel):
    symbol: str
    as_of_date: str
    v8_grade: str = Field(..., description="Aggregate grade reference only — not a trade command")
    global_regime: GlobalRegime
    structure: StructureDimension
    ignition: IgnitionDimension
    volume: VolumeDimension
    risk: RiskDimension

    def is_lethal(self) -> bool:
        if self.global_regime.systemic_risk_flag:
            return True
        return self.risk.is_trap or self.risk.overheat_index >= 6 or self.risk.toxic_breaker