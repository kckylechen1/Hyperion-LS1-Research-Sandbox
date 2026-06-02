from typing import List, Optional
from autoresearch_lab.decision_provenance.schema import DecisionAtom, DistilledLesson
from autoresearch_lab.decision_provenance.alpha_binder import bind_alpha_tensor
from autoresearch_lab.decision_provenance.beta_classifier import classify_beta_tensor
from autoresearch_lab.decision_provenance.outcome_validator import validate_outcome
from autoresearch_lab.decision_provenance.causality_diagnoser import diagnose_causality
from autoresearch_lab.decision_provenance.tachi_promote import promote_to_tachi

def run_replay(
    atom: DecisionAtom,
    snapshot_fixture: Optional[dict] = None,
    future_prices: Optional[List[float]] = None
) -> DistilledLesson:
    """Executes the complete Decision Provenance Replay pipeline for a single decision atom.
    
    1. Binds T_0 Alpha facts (using existing snapshot).
    2. Classifies psychological and discipline state (Beta).
    3. Computes objective post-decision price outcomes (Outcome).
    4. Performs causality forensic diagnosis.
    5. Strips conversational context and promotes atomic lesson to HyperTachi.
    """
    if future_prices is None:
        future_prices = [10.0] * 6 # Simple flat future price default
        
    # 1. Bind Alpha
    alpha = bind_alpha_tensor(atom, snapshot_fixture)
    
    # 2. Classify Beta
    beta = classify_beta_tensor(atom)
    
    # 3. Validate Outcome
    outcome = validate_outcome(atom.symbol, future_prices, atom.human_action)
    
    # 4. Diagnose Causality
    diagnosis = diagnose_causality(alpha, beta, outcome)
    
    # 5. Distill and promote to Tachi
    lesson = promote_to_tachi(atom, alpha, beta, outcome, diagnosis)
    
    return lesson
