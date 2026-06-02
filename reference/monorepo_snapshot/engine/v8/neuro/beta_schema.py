"""engine.v8.neuro.beta_schema — BetaTensor (Left-Brain Physics Hemisphere).

The Beta Tensor is the structured numeric representation of the V8 physics
feature space. It is the left-brain counterpart to :class:`AlphaTensor` (right-
brain text chunking for the Observer LLM).

Architecture (PATTERN_MEMORY_INTEGRATION_FULL_SPEC §1.4):
  Left Brain (BetaTensor)  → numeric physics vectors → cosine similarity recall
  Right Brain (AlphaTensor) → structured text dims    → Observer LLM

Both consume the SAME snapshot source. BetaTensor projects the warpcore+
indicators + Chan-theory feature bundle into named, group-addressable dimensions
suitable for:

  • z-normalization (``autoresearch_lab.pattern_memory.normalize``)
  • Cosine k-NN recall (``PatternStore.query_top_k(embedding_type="z")``)
  • PCA+fusion with Kronos (``autoresearch_lab.pattern_memory.fusion``)
  • IC/ablation analysis by domain

Feature dimensions (34D, verified against actual ``pattern_snapshot`` data)
----------------------------------------------------------------------------
  Structure  (8D) : Chan geometry — pivot width, zs/bi/seg counts, trend/stage
  Volume     (5D) : Volume microstructure — CVD, shrink, fake-out, vol ratios
  Momentum   (7D) : Indicator momentum — RSI, MACD, ADX, BB, returns
  Risk       (4D) : Sentinel risk — overheat, toxic breaker, fever/toxic penalties
  ChanBsp    (6D) : Chan buy/sell point — T1/T2/T3 types, divergence, area ratio
  ScoreRef   (4D) : V8 heuristic scores — reference-only appendix (see NOTE below)

NOTE: The 4 V8 heuristic scores (setup_score, ignition_score, left_total,
right_total) exist in the actual ``z_feature_vector`` storage but *must not* be
included in blind cosine-recall comparisons (spec §1.2). They are carried here
for data-integrity / debugging but are sliced out before distance computation by
callers that enforce the blind contract.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "BetaTensor",
    "BetaStructure",
    "BetaVolume",
    "BetaMomentum",
    "BetaRisk",
    "BetaChanBsp",
    "BetaScoreRef",
    "BETA_DOMAINS",
    "BETA_DIM",
    "BETA_BLIND_DIM",
]

# Total dimensionality of the full feature vector.
BETA_DIM = 34

# Blind-safe dimensionality (excludes V8 heuristic scores).
BETA_BLIND_DIM = 30

# Domain → slice mapping (inclusive-exclusive style, back-compat with numpy slicing).
# Indices are zero-based positions in the flat 34D vector.
BETA_DOMAINS: dict[str, tuple[int, int]] = {
    "structure": (0, 8),
    "volume": (8, 13),
    "momentum": (13, 20),
    "risk": (20, 24),
    "chan_bsp": (24, 30),
    "score_ref": (30, 34),
}


# --------------------------------------------------------------------------- #
# Domain Pydantic models
# --------------------------------------------------------------------------- #

class BetaStructure(BaseModel):
    """Chan-theory geometry (8D)."""

    zs_count: float = Field(0.0, description="Number of Chan consolidations (中枢数)")
    bi_count: float = Field(0.0, description="Number of Chan strokes (笔数)")
    seg_count: float = Field(0.0, description="Number of Chan segments (线段数)")
    pivot_pct_in_range: float = Field(0.0, description="% price within pivot range")
    pivot_range_width: float = Field(0.0, description="Width of pivot range (high-low)")
    pivot_core_width: float = Field(0.0, description="Width of pivot core range")
    trend_type_encoded: float = Field(0.5, description="Trend encoded: 2=Up, 1=Consolidation, 0=Down")
    stage_code_encoded: float = Field(0.0, description="Stage encoded: 1=forming, 2=developing, 3=mature, 4=complete")


class BetaVolume(BaseModel):
    """Volume microstructure (5D)."""

    cvd: float = Field(0.0, description="Consecutive volume days")
    vol_ratio_5d: float = Field(1.0, description="5-day volume MA ratio")
    shrink_days: float = Field(0.0, description="Consecutive volume-shrink days")
    fake_out_days: float = Field(0.0, description="Consecutive fake-out days")
    vol_up_down_ratio: float = Field(1.0, description="Up-vs-down volume ratio")


class BetaMomentum(BaseModel):
    """Indicator momentum (7D)."""

    rsi: float = Field(50.0, description="RSI value")
    macd_hist: float = Field(0.0, description="MACD histogram")
    adx: float = Field(0.0, description="ADX trend strength")
    bb_pct_b: float = Field(0.5, description="Bollinger %B position")
    rsi_momentum_5d: float = Field(0.0, description="5-day RSI momentum change")
    consecutive_up_days: float = Field(0.0, description="Consecutive up days")
    return_1d: float = Field(0.0, description="1-day return")


class BetaRisk(BaseModel):
    """Sentinel risk flags (4D)."""

    overheat_index: float = Field(0.0, description="Overheat index (0-10)")
    toxic_breaker_count: float = Field(0.0, description="Count of toxic breaker factors triggered")
    fever_penalty_raw: float = Field(0.0, description="Raw fever penalty value")
    toxic_penalty: float = Field(0.0, description="Toxic breaker penalty value")


class BetaChanBsp(BaseModel):
    """Chan buy/sell-point indicators (6D)."""

    bsp_side_encoded: float = Field(0.0, description="BSP side: 1=buy, -1=sell, 0=none")
    bsp_type_t1: float = Field(0.0, description="Has T1 buy/sell point? (1/0)")
    bsp_type_t2: float = Field(0.0, description="Has T2 buy/sell point? (1/0)")
    bsp_type_t3: float = Field(0.0, description="Has T3 buy/sell point? (1/0)")
    macd_divergence: float = Field(0.0, description="MACD divergence flag (1/0)")
    macd_area_ratio: float = Field(0.0, description="MACD divergence area ratio")


class BetaScoreRef(BaseModel):
    """V8 heuristic scores (4D) — reference appendix, NOT for blind recall.

    Per spec §1.2 System B must be blind to System A's heuristic scores.
    These are carried for data-integrity only.
    """

    setup_score: float = Field(0.0, description="V8 left-side setup score")
    ignition_score: float = Field(0.0, description="V8 right-side ignition score")
    left_total: float = Field(0.0, description="Left-side total score")
    right_total: float = Field(0.0, description="Right-side total score")


# --------------------------------------------------------------------------- #
# BetaTensor — composite
# --------------------------------------------------------------------------- #

class BetaTensor(BaseModel):
    """Left-brain physics tensor — numeric feature vector organised by domain.

    This is the structured serialisation of the 34D physics feature vector
    consumed by z-normalised cosine recall and PCA+Kronos fusion. It is the
    counterpart to :class:`AlphaTensor` (right-brain text chunking).

    Attributes
    ----------
    symbol : str
    as_of_date : str
    structure : BetaStructure (8D)
    volume : BetaVolume (5D)
    momentum : BetaMomentum (7D)
    risk : BetaRisk (4D)
    chan_bsp : BetaChanBsp (6D)
    score_ref : BetaScoreRef (4D) — reference-only appendix

    Methods
    -------
    to_vector(blind=True) → list[float]
        Flatten to a 30-D (blind) or 34-D (full) ordered list.
    domain_vector(domain: str) → list[float]
        Return a single domain slice.
    """

    symbol: str = Field("UNKNOWN")
    as_of_date: str = Field("")
    v8_grade: str = Field("?", description="System A grade (reference only)")
    feature_names_json: str = Field("[]", description="JSON-encoded ordered feature names")

    structure: BetaStructure = Field(default_factory=BetaStructure)
    volume: BetaVolume = Field(default_factory=BetaVolume)
    momentum: BetaMomentum = Field(default_factory=BetaMomentum)
    risk: BetaRisk = Field(default_factory=BetaRisk)
    chan_bsp: BetaChanBsp = Field(default_factory=BetaChanBsp)
    score_ref: BetaScoreRef = Field(default_factory=BetaScoreRef)

    # ------------------------------------------------------------------ #
    # Vector helpers
    # ------------------------------------------------------------------ #

    def to_vector(self, blind: bool = True) -> list[float]:
        """Flatten to ordered list.

        Parameters
        ----------
        blind : bool
            When True (default), omit the ``score_ref`` appendix (30 dims).
            When False, include it (34 dims).
        """
        vec: list[float] = []
        for field_name in ("structure", "volume", "momentum", "risk", "chan_bsp"):
            dom = getattr(self, field_name)
            vec.extend([getattr(dom, name) for name in dom.__fields__])
        if not blind:
            vec.extend([getattr(self.score_ref, name) for name in self.score_ref.__fields__])
        return vec

    def domain_vector(self, domain: str) -> list[float]:
        """Return a single domain slice as a float list."""
        dom_obj = getattr(self, domain, None)
        if isinstance(dom_obj, BaseModel):
            return [getattr(dom_obj, name) for name in dom_obj.__fields__]
        return []

    @property
    def blind_dim(self) -> int:
        """Dimensionality of the blind-safe vector (excludes scores)."""
        return BETA_BLIND_DIM

    @property
    def full_dim(self) -> int:
        """Dimensionality of the full vector (includes scores)."""
        return BETA_DIM
