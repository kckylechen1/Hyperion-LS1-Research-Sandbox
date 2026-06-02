"""Causality diagnosis — alpha vs scoring vs beta (sandbox heuristic)."""

from __future__ import annotations

from hyperion_ls1_research.alpha_tensor.schema import AlphaTensor


def diagnose_error_vector(
    alpha: AlphaTensor,
    *,
    human_action: str,
    outcome_label: str,
    return_t5: float,
    aggregate_discouraged_buy: bool = False,
) -> dict:
    """
    Classify primary error vector for research review.

    Not a production causality engine — explicit sandbox rules.
    """
    scenario_outcome = outcome_label

    # Beta: human bought despite aggregate discouragement and LS1 was not lethal
    if (
        human_action.upper().startswith("BUY")
        and aggregate_discouraged_buy
        and not alpha.is_lethal()
        and return_t5 < -0.02
    ):
        return {
            "diagnosis": "beta_error",
            "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
            "answer": "Beta execution / discipline — entered against aggregate guidance.",
        }

    # Scoring: LS1 showed ignition but aggregate grade stayed mediocre (missed entry)
    if scenario_outcome == "missed_entry":
        if alpha.ignition.ignition_bar_present and alpha.v8_grade in ("B", "C", "D"):
            return {
                "diagnosis": "scoring_error",
                "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
                "answer": "Aggregate scoring lag — LS1 ignition present but grade did not reflect it.",
            }

    # Alpha: trap flagged but day-level looked attractive
    if scenario_outcome == "false_breakout" and alpha.risk.is_trap:
        return {
            "diagnosis": "alpha_error",
            "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
            "answer": "Alpha / microstructure — trap and volume deterioration were visible in LS1 fields.",
        }

    # Healthy washout — structure held
    if scenario_outcome == "healthy_washout":
        if not alpha.is_lethal() and alpha.structure.consolidation_phase:
            return {
                "diagnosis": "no_error",
                "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
                "answer": "No primary error — washout within healthy LS1 structure/coiling context.",
            }

    if alpha.is_lethal() and return_t5 <= -0.02:
        return {
            "diagnosis": "scoring_error",
            "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
            "answer": "Scoring aggregate under-weighted lethal LS1 risk signals.",
        }

    return {
        "diagnosis": "no_error",
        "question": "Was error in Alpha Tensor, aggregate scoring, or Beta Tensor?",
        "answer": "Inconclusive in sandbox rules — needs more labeled fixtures.",
    }


def lesson_from_diagnosis(diagnosis: dict, symbol: str) -> dict | None:
    """Return lesson candidate only for distilled axioms — never raw chat."""
    d = diagnosis.get("diagnosis")
    if d in ("no_error",):
        return None
    return {
        "lesson_id": f"sandbox-{symbol}-{d}",
        "verdict_type": d.upper(),
        "core_axiom": diagnosis.get("answer", ""),
        "evidence_summary": f"diagnosis={d}",
        "promote_allowed": True,
    }