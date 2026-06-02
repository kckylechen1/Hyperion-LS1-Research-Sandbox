"""Decision provenance atom model (sanitized, no raw chat promotion)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class WatchIdea(BaseModel):
    symbol: str
    as_of_time: str
    user_intent_summary: str = Field(
        ..., description="Redacted summary of user watch intent — not full transcript"
    )


class DecisionRationale(BaseModel):
    agent_summary: str = Field(..., description="Redacted agent stance summary")
    human_action: str = Field(..., description="Observed action: NO_BUY, HOLD, BUY_NORMAL, etc.")
    aggregate_grade_ref: Optional[str] = None


class OutcomeValidation(BaseModel):
    outcome_label: str
    return_t5: float = 0.0
    return_t10: float = 0.0
    scenario: str = ""


class LessonCandidate(BaseModel):
    """Distilled axiom only — never embed raw chat."""
    lesson_id: str
    verdict_type: str
    core_axiom: str
    evidence_summary: str
    promote_allowed: bool = False


class ProvenanceBundle(BaseModel):
    watch_idea: WatchIdea
    decision_rationale: DecisionRationale
    outcome_validation: OutcomeValidation
    lesson_candidate: Optional[LessonCandidate] = None