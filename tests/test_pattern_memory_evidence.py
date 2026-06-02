from hyperion_ls1_research.alpha_tensor import build_alpha_tensor
from hyperion_ls1_research.ls1_contract import load_snapshot
from hyperion_ls1_research.pattern_memory import InMemoryPatternStore, PatternCase, aggregate_evidence


def test_evidence_returns_summary_not_trading_command():
    store = InMemoryPatternStore()
    for name in ("dongshan_missed_entry", "xinyisheng_healthy_washout", "xinyuan_false_breakout"):
        snap = load_snapshot(name)
        store.register(
            PatternCase(
                case_id=name,
                symbol=snap["symbol"],
                scenario=snap["scenario"],
                outcome_label=snap["outcome_label"],
                trade_idx=100,
            )
        )
    alpha = build_alpha_tensor(load_snapshot("dongshan_missed_entry"))
    card = aggregate_evidence(alpha, store.list_cases(), query_trade_idx=200)
    assert card["is_trading_command"] is False
    assert "similar_case_ids" in card
    assert "outcome_distribution" in card
    assert "BUY" not in str(card).upper() or "NO_BUY" in str(card)