from typing import Literal, Optional
from pydantic import BaseModel, Field
from engine.v8.neuro.schema import AlphaTensor

class DecisionAtom(BaseModel):
    """Raw input capturing the state and intent of a trade decision at T_0."""
    symbol: str = Field(..., description="Stock symbol (e.g., 688256.SH)")
    as_of_time: str = Field(..., description="Decision timestamp in YYYY-MM-DDTHH:MM:SSZ format")
    raw_text: str = Field(..., description="Raw human chat text / intent description")
    agent_reply: str = Field(..., description="Raw agent reply text / alert text")
    human_action: str = Field(..., description="The action taken (e.g., BUY_FULL, BUY_NORMAL, PANIC_SELL, NO_BUY)")

class BetaTensor(BaseModel):
    """The psychological and execution discipline dimension of the decision."""
    short_term_risk_should_T0: bool = Field(False, description="Did the short-term risk require T+0 hedging?")
    long_term_risk_should_position_size: bool = Field(False, description="Did long-term risk require smaller positioning?")
    selling_winner_holding_loser: bool = Field(False, description="Selling a winner early or holding onto a loser?")
    panic_exit: bool = Field(False, description="Was this exit triggered by panic rather than structural breakdown?")
    fundamental_override: bool = Field(False, description="Did the human override rules based on basic fundamental research?")
    sizing_discipline_pct: float = Field(1.0, description="Position size ratio actually used (e.g., 1.0 = full, 0.5 = half)")

class OutcomeMetrics(BaseModel):
    """Post-decision price performance metrics across multiple horizon limits."""
    return_t1: float = Field(0.0, description="T+1 returns")
    return_t5: float = Field(0.0, description="T+5 returns")
    return_t10: float = Field(0.0, description="T+10 returns")
    return_t20: float = Field(0.0, description="T+20 returns")
    mfe: float = Field(0.0, description="Maximum Favorable Excursion")
    mae: float = Field(0.0, description="Maximum Adverse Excursion")
    outcome_label: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "TRUE_NEGATIVE", "FALSE_NEGATIVE", "NEUTRAL"] = "NEUTRAL"

class CausalityDiagnosis(BaseModel):
    """Forensic diagnosis of the primary failure vector."""
    diagnosis: Literal["alpha_error", "scoring_error", "beta_error", "mixed_error", "no_error"]
    explanation: str = Field(..., description="Detailed explanation of the diagnosis reasoning")

class DistilledLesson(BaseModel):
    """The final highly-compressed axiom promoted to HyperTachi memory."""
    lesson_id: str = Field(..., description="Unique generated key for this lesson")
    timestamp: str = Field(..., description="Generation time")
    symbol: str = Field(..., description="Stock symbol")
    verdict_type: str = Field(..., description="e.g., BETA_ERROR, ALPHA_ERROR, etc.")
    core_axiom: str = Field(..., description="Immutable discipline or strategic takeaway")
    evidence: str = Field(..., description="Condensed statistical evidence mapping Alpha, Beta and Outcome")
