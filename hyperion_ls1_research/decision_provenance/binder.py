"""Bind chat event + fixture snapshot -> AlphaTensor + provenance bundle."""

from __future__ import annotations

from hyperion_ls1_research.alpha_tensor.builder import build_alpha_tensor
from hyperion_ls1_research.alpha_tensor.schema import AlphaTensor
from hyperion_ls1_research.decision_provenance.atoms import (
    DecisionRationale,
    OutcomeValidation,
    ProvenanceBundle,
    WatchIdea,
)
from hyperion_ls1_research.decision_provenance.validator import diagnose_error_vector


def _redact_user_intent(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) > 120:
        return text[:117] + "..."
    return text or "(redacted)"


def _redact_agent_reply(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) > 200:
        return text[:197] + "..."
    return text or "(redacted)"


def bind_chat_to_snapshot(
    chat_event: dict,
    snapshot: dict,
) -> tuple[ProvenanceBundle, AlphaTensor, dict]:
    """
    Bind one chat line to a fixture snapshot.

    Returns (bundle, alpha_tensor, diagnosis_dict).
    """
    snap = snapshot.copy()
    snap["symbol"] = chat_event.get("symbol") or snap.get("symbol")
    snap["as_of_date"] = chat_event.get("timestamp") or snap.get("as_of_date")

    alpha = build_alpha_tensor(snap)

    bundle = ProvenanceBundle(
        watch_idea=WatchIdea(
            symbol=str(snap["symbol"]),
            as_of_time=str(snap["as_of_date"]),
            user_intent_summary=_redact_user_intent(chat_event.get("user_text", "")),
        ),
        decision_rationale=DecisionRationale(
            agent_summary=_redact_agent_reply(chat_event.get("agent_text", "")),
            human_action=str(chat_event.get("human_action", "NO_BUY")),
            aggregate_grade_ref=alpha.v8_grade,
        ),
        outcome_validation=OutcomeValidation(
            outcome_label=str(snap.get("outcome_label", "NEUTRAL")),
            return_t5=float(snap.get("outcome", {}).get("return_t5", 0.0)),
            return_t10=float(snap.get("outcome", {}).get("return_t10", 0.0)),
            scenario=str(snap.get("scenario", "")),
        ),
    )

    diagnosis = diagnose_error_vector(
        alpha,
        human_action=bundle.decision_rationale.human_action,
        outcome_label=bundle.outcome_validation.outcome_label,
        return_t5=bundle.outcome_validation.return_t5,
        aggregate_discouraged_buy=bool(snap.get("meta", {}).get("aggregate_discouraged_buy", False)),
    )
    return bundle, alpha, diagnosis