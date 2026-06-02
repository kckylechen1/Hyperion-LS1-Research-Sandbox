from autoresearch_lab.decision_provenance.schema import DecisionAtom

def build_decision_atom(
    symbol: str,
    as_of_time: str,
    raw_text: str,
    agent_reply: str,
    human_action: str,
) -> DecisionAtom:
    """Helper to cleanly build a Pydantic DecisionAtom."""
    return DecisionAtom(
        symbol=symbol,
        as_of_time=as_of_time,
        raw_text=raw_text,
        agent_reply=agent_reply,
        human_action=human_action,
    )
