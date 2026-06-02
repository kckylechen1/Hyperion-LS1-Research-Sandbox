"""Late fusion skeleton — separate retrieval per space, merge evidence scores."""
from __future__ import annotations

from typing import Any

from autoresearch_lab.pattern_memory.evidence_card import (
    build_arm_evidence,
    interpret_evidence_for_fund_manager,
)

_LATE_ARMS = ("warpcore_only", "kronos_only")


def query_late_fusion_evidence(
    store,
    *,
    pattern_id: str,
    query_trade_idx: int,
    top_k: int = 5,
    horizon: str = "T10",
    stats_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve warpcore + kronos arms separately and fuse calibrated scores."""
    arm_cards: dict[str, Any] = {}
    scores: dict[str, float] = {}

    for arm in _LATE_ARMS:
        card = build_arm_evidence(
            store,
            pattern_id=pattern_id,
            query_trade_idx=query_trade_idx,
            arm=arm,
            top_k=top_k,
            horizon=horizon,
            stats_id=stats_id,
        )
        arm_cards[arm] = card
        true_s = float(card.get("top_k_true_S_rate") or 0.0)
        trap = float(card.get("top_k_false_trap_rate") or 0.0)
        diversity = float(card.get("support_diversity") or 0.0)
        scores[arm] = round(true_s * (1.0 - trap) * (0.5 + 0.5 * diversity), 4)

    total = sum(scores.values()) or 1.0
    weights = {k: round(v / total, 4) for k, v in scores.items()}
    fused_score = round(sum(scores[k] * weights[k] for k in scores), 4)

    pseudo_card = {
        "evidence_version": "pm_v1_late",
        "fusion_mode": "fused_late",
        "horizon": horizon,
        "arms": arm_cards,
        "late_fusion_weights": weights,
        "late_fusion_score": fused_score,
    }
    interpretation = interpret_evidence_for_fund_manager(
        {
            "arms": {
                "fused_concat_v1": max(
                    arm_cards.values(),
                    key=lambda c: float(c.get("top_k_true_S_rate") or 0),
                    default={},
                )
            }
        }
    )
    interpretation["late_fusion_score"] = str(fused_score)
    return {
        "card": pseudo_card,
        "interpretation": interpretation,
        "weights": weights,
        "score": fused_score,
    }