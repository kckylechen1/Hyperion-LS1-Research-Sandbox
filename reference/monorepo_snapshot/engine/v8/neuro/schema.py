from typing import List, Optional, Literal
from pydantic import BaseModel, Field

# ==============================================================================
# Dimension 1: Structural Setup (左侧结构场)
# Focus: Base solidity, Chan geometry, Washout state.
# ==============================================================================
class StructureDimension(BaseModel):
    chan_bsp: str = Field(..., description="Chan Buy/Sell Point Phase (e.g., 缠论一买)")
    setup_score: float = Field(..., description="Raw left-side setup score (0-40)")
    zs_count: int = Field(..., description="Number of Chan consolidations (中枢数)")
    consolidation_phase: str = Field(..., description="e.g., 洗盘吸收就绪, 破位, 震荡")
    gann_support: bool = Field(False, description="Did price hit mathematical Gann support?")
    bollinger_squeeze: bool = Field(False, description="Is volatility extremely compressed?")
    ma_alignment: str = Field(..., description="Moving Average alignment (e.g., 多头排列, 空头, 缠绕)")

# ==============================================================================
# Dimension 2: Ignition Momentum (右侧点火场)
# Focus: Current money flow, breakouts, catalysts.
# ==============================================================================
class IgnitionDimension(BaseModel):
    ignition_score: float = Field(..., description="Raw right-side ignition score (0-20)")
    macd_cross: Literal["none", "golden", "dead"] = Field("none", description="MACD crossing state")
    ignition_bar_present: bool = Field(False, description="Is there a confirmed ignition k-line?")
    breakout_confirmed: bool = Field(False, description="Did it break out of the consolidation zone?")
    fund_inflow_intensity: float = Field(0.0, description="Money flow intensity proxy")

# ==============================================================================
# Dimension 3: Volume Microstructure (量能微观场)
# Focus: True buying vs fake volume, absorption rates.
# ==============================================================================
class VolumeDimension(BaseModel):
    volume_ratio_5d: float = Field(..., description="5-day volume moving average ratio")
    turnover_rate: float = Field(..., description="Current turnover rate (换手率)")
    pump_dump_vol_ratio: float = Field(..., description="Volume ratio of latest pump vs previous dump (e.g., 0.08 is fatal, >1.0 is healthy)")
    volume_gap_detected: bool = Field(False, description="Is there a sudden suspicious volume gap?")

# ==============================================================================
# Dimension 4: Trap & Risk (暗雷与风控场)
# Focus: Pump fakes, overheat state, lethal anomalies.
# ==============================================================================
class RiskDimension(BaseModel):
    overheat_index: int = Field(..., description="0-10 scale. >=6 is dangerously overheated.")
    is_trap: bool = Field(..., description="Is the current pattern a detected trap?")
    trap_type: str = Field("none", description="e.g., pump_fake (骗炮), none")
    trap_details: str = Field("", description="Detailed explanation of the trap (e.g., 砸盘7根，拉升1根量比8%)")
    toxic_breaker: bool = Field(False, description="Has it triggered a toxic circuit breaker (e.g., flash crash)?")

# ==============================================================================
# Dimension 5: Global Market Context (大盘风控与铁律场)
# Focus: Market-wide risk, Iron Rules, Systemic crash detection.
# ==============================================================================
class GlobalRegime(BaseModel):
    market_regime: Literal["bull", "bear", "range", "crash"] = Field("range", description="Overall market trend")
    vol_regime: Literal["low", "normal", "high", "extreme"] = Field("normal", description="Market volatility state")
    iron_verdict: str = Field("neutral", description="Iron Rules verdict (e.g., 大盘破位，绝对禁买)")
    systemic_risk_flag: bool = Field(False, description="Is the broad market currently crashing?")

# ==============================================================================
# The Alpha Tensor (奇点张量)
# The complete 4-Dimensional physics object fed to The Observer (27B LLM) and DuckDB.
# ==============================================================================
class AlphaTensor(BaseModel):
    symbol: str = Field(..., description="Stock symbol (e.g., 688256.SH)")
    as_of_date: str = Field(..., description="Snapshot date (YYYY-MM-DD HH:MM:SS)")
    v8_grade: str = Field(..., description="Legacy System A Grade (S/A/B/C/D) - kept for reference only")
    
    # Global Context
    global_regime: GlobalRegime
    
    # The 4 Orthogonal Dimensions
    structure: StructureDimension
    ignition: IgnitionDimension
    volume: VolumeDimension
    risk: RiskDimension
    
    def is_lethal(self) -> bool:
        """Returns True if the Risk Dimension OR Global Market triggers a fatal veto."""
        if self.global_regime.systemic_risk_flag:
            return True
        return self.risk.is_trap or self.risk.overheat_index >= 6 or self.risk.toxic_breaker
