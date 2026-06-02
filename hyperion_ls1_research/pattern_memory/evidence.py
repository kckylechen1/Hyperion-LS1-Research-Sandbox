"""Minimal pattern-memory evidence aggregation (evidence-only, not trade commands)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from hyperion_ls1_research.alpha_tensor.schema import AlphaTensor
from hyperion_ls1_research.pattern_memory.leakage_guard import filter_past_neighbors
from hyperion_ls1_research.pattern_memory.store import PatternCase


def _alpha_similarity_placeholder(_query: AlphaTensor, _case: PatternCase) -> float:
    """Placeholder — real system uses embedding retrieval; not in public sandbox."""
    return 0.0


def aggregate_evidence(
    query_alpha: AlphaTensor,
    neighbors: list[PatternCase],
    *,
    query_trade_idx: int = 9999,
    diagnosis_candidates: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize similar cases for fund-manager-style review (no BUY/SELL output)."""
    safe = filter_past_neighbors(
        [{"case_id": n.case_id, "trade_idx": n.trade_idx} for n in neighbors],
        query_trade_idx=query_trade_idx,
        min_gap_bars=1,
    )
    safe_ids = {row["case_id"] for row in safe}
    filtered = [n for n in neighbors if n.case_id in safe_ids]

    dist = dict(Counter(c.outcome_label for c in filtered))
    similar_ids = [c.case_id for c in filtered]

    card: dict[str, Any] = {
        "evidence_version": "sandbox_pm_v1",
        "similar_case_ids": similar_ids,
        "outcome_distribution": dist,
        "alpha_tensor_similarity": round(
            sum(_alpha_similarity_placeholder(query_alpha, c) for c in filtered)
            / max(1, len(filtered)),
            4,
        ),
        "diagnosis_candidates": diagnosis_candidates
        or ["alpha_error", "scoring_error", "beta_error", "no_error"],
        "warnings": [],
        "is_trading_command": False,
    }
    if not filtered:
        card["warnings"].append("no neighbors after leakage guard")
    return card