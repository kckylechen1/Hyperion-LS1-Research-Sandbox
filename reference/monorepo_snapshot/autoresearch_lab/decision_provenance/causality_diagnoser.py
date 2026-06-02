from engine.v8.neuro.schema import AlphaTensor
from autoresearch_lab.decision_provenance.schema import BetaTensor, OutcomeMetrics, CausalityDiagnosis

def diagnose_causality(
    alpha: AlphaTensor, 
    beta: BetaTensor, 
    outcome: OutcomeMetrics
) -> CausalityDiagnosis:
    """Diagnoses the true root cause of failure/success using the decision provenance matrix."""
    
    is_alpha_fatal = alpha.is_lethal()
    grade = alpha.v8_grade.upper()
    overheat = alpha.risk.overheat_index
    
    # 1. Healthy / Perfect execution (No Error)
    if not is_alpha_fatal and outcome.outcome_label == "TRUE_POSITIVE" and not beta.panic_exit:
        return CausalityDiagnosis(
            diagnosis="no_error",
            explanation="Alpha setup was healthy, and execution was successful. Perfect True Positive."
        )
        
    # 2. Avoided fatal risk (No Error / True Negative)
    if is_alpha_fatal and outcome.outcome_label == "TRUE_NEGATIVE":
        return CausalityDiagnosis(
            diagnosis="no_error",
            explanation="Model signaled critical risk, and human correctly avoided it. Perfect True Negative."
        )

    # 3. Beta Error: Violation of Model Alerts (Human FOMO)
    if is_alpha_fatal and outcome.outcome_label == "TRUE_POSITIVE":
        # Model warned, human still entered, and forward return collapsed.
        if outcome.return_t5 <= -0.02:
            return CausalityDiagnosis(
                diagnosis="beta_error",
                explanation=f"Model flagged danger (Grade={grade}, Overheat={overheat}), but human violated discipline and entered. Pure Beta Failure."
            )
            
    # 4. Beta Error: Panic Exit
    if beta.panic_exit and outcome.return_t10 >= 0.02:
        return CausalityDiagnosis(
            diagnosis="beta_error",
            explanation="Model setup was structurally sound, but human exited prematurely due to panic during a healthy washout. Pure Beta Failure."
        )

    # 5. Alpha/Scoring Error: False Breakout
    if not is_alpha_fatal and outcome.outcome_label == "FALSE_POSITIVE" and not beta.panic_exit:
        # Model said A/B (healthy), human followed rules, but stock crashed
        return CausalityDiagnosis(
            diagnosis="alpha_error",
            explanation=f"Model gave a clean signal (Grade={grade}, Overheat={overheat}), but market collapsed. Statistical alpha failure or regime shift."
        )

    # 6. Scoring Error: Wrong weighting or lag
    if grade in ("S", "A") and is_alpha_fatal and outcome.return_t5 <= -0.02:
        # Score was high but it was actually lethal/trap. Scoring lag!
        return CausalityDiagnosis(
            diagnosis="scoring_error",
            explanation=f"Model scored Grade={grade} but overlooked critical microstructure trap/overheat warnings. Scoring aggregate error."
        )

    # 7. Mixed Failure
    if is_alpha_fatal and beta.sizing_discipline_pct > 0.8:
        return CausalityDiagnosis(
            diagnosis="mixed_error",
            explanation=f"Model had warnings (Grade={grade}, Overheat={overheat}), human violated sizing limits, and market outcome was negative."
        )

    # Fallback
    return CausalityDiagnosis(
        diagnosis="no_error",
        explanation="Standard trade lifecycle outcome without significant rule violations."
    )
