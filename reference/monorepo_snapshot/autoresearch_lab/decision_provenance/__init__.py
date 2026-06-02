"""LS1 Decision Provenance Replay Framework.

Provides forensic analysis of human-agent decisions by binding LS1 state (Alpha)
and execution/discipline state (Beta) to post-decision price outcomes.
"""

from autoresearch_lab.decision_provenance.schema import (
    DecisionAtom,
    BetaTensor,
    OutcomeMetrics,
    CausalityDiagnosis,
    DistilledLesson,
)
from autoresearch_lab.decision_provenance.atoms import build_decision_atom
from autoresearch_lab.decision_provenance.alpha_binder import bind_alpha_tensor
from autoresearch_lab.decision_provenance.beta_classifier import classify_beta_tensor
from autoresearch_lab.decision_provenance.outcome_validator import validate_outcome
from autoresearch_lab.decision_provenance.causality_diagnoser import diagnose_causality
from autoresearch_lab.decision_provenance.tachi_promote import promote_to_tachi
from autoresearch_lab.decision_provenance.replay import run_replay

__all__ = [
    "DecisionAtom",
    "BetaTensor",
    "OutcomeMetrics",
    "CausalityDiagnosis",
    "DistilledLesson",
    "build_decision_atom",
    "bind_alpha_tensor",
    "classify_beta_tensor",
    "validate_outcome",
    "diagnose_causality",
    "promote_to_tachi",
    "run_replay",
]
