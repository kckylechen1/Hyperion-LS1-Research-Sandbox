"""PatternRecallEvidenceCard — fund-manager-safe retrieval summary."""
from __future__ import annotations

import json
from typing import Any, Optional

from autoresearch_lab.pattern_memory.evidence import aggregate_top_k_evidence

EVIDENCE_VERSION = "pm_v1"

ARM_EMBEDDING_MAP = {
    "warpcore_only": "z",
    "kronos_only": "kronos",
    "fused_concat_v1": "fused",
}


def build_arm_evidence(
    store,
    *,
    pattern_id: str,
    query_trade_idx: int,
    arm: str = "warpcore_only",
    top_k: int = 5,
    horizon: str = "T10",
    same_symbol_min_gap_bars: int = 30,
    stats_id: str | None = None,
) -> dict[str, Any]:
    """Run leakage-safe top-k for one arm and return an evidence card."""
    embedding_type = ARM_EMBEDDING_MAP.get(arm, arm)
    row = store.con.execute(
        "SELECT symbol, market_regime FROM pattern_snapshot WHERE pattern_id = ?",
        [pattern_id],
    ).fetchone()
    query_symbol = row[0] if row else None
    query_regime = row[1] if row else None

    hits = store.query_top_k(
        pattern_id,
        query_trade_idx=query_trade_idx,
        embedding_type=embedding_type,
        k=top_k,
        horizon=horizon,
        stats_id=stats_id,
        same_symbol_min_gap_bars=same_symbol_min_gap_bars,
    )
    card = aggregate_top_k_evidence(
        hits,
        horizon=horizon,
        query_symbol=query_symbol,
        query_trade_idx=query_trade_idx,
        query_market_regime=query_regime,
        embedding_type=embedding_type,
        top_k=top_k,
    )
    card["arm"] = arm
    card["pattern_id"] = pattern_id
    return card


def build_pattern_recall_evidence_card(
    store,
    *,
    pattern_id: str,
    query_trade_idx: int,
    symbol: str,
    as_of: str,
    top_k: int = 5,
    horizon: str = "T10",
    arms: list[str] | None = None,
    stats_id: str | None = None,
    pca_artifact_id: str | None = None,
) -> dict[str, Any]:
    """Multi-arm evidence card (no raw cosine trading signals)."""
    arms = arms or ["warpcore_only", "kronos_only", "fused_concat_v1"]
    arm_cards: dict[str, Any] = {}
    warnings: list[str] = []

    for arm in arms:
        emb = ARM_EMBEDDING_MAP.get(arm, arm)
        col = {
            "z": "z_feature_vector",
            "kronos": "kronos_vector",
            "fused": "fused_vector",
        }.get(emb)
        if col:
            has_vec = store.con.execute(
                f"SELECT {col} IS NOT NULL FROM pattern_snapshot WHERE pattern_id = ?",
                [pattern_id],
            ).fetchone()
            if not has_vec or not has_vec[0]:
                arm_cards[arm] = {"skipped": True, "reason": f"missing {emb} vector"}
                continue
        try:
            arm_cards[arm] = build_arm_evidence(
                store,
                pattern_id=pattern_id,
                query_trade_idx=query_trade_idx,
                arm=arm,
                top_k=top_k,
                horizon=horizon,
                stats_id=stats_id,
            )
            for w in arm_cards[arm].get("warnings", []):
                if w not in warnings:
                    warnings.append(w)
        except Exception as exc:
            arm_cards[arm] = {"skipped": True, "reason": str(exc)}

    return {
        "symbol": symbol,
        "as_of": str(as_of)[:10],
        "pattern_id": pattern_id,
        "evidence_version": EVIDENCE_VERSION,
        "horizon": horizon,
        "stats_id": stats_id,
        "pca_artifact_id": pca_artifact_id,
        "arms": arm_cards,
        "warnings": warnings,
    }


def interpret_evidence_for_fund_manager(card: dict[str, Any]) -> dict[str, str]:
    """Map evidence card to analyst stance — never BUY/SELL."""
    arms = card.get("arms") or {}
    fused = arms.get("fused_concat_v1") or arms.get("A_warpcore") or {}
    if fused.get("skipped"):
        fused = next(
            (a for a in arms.values() if isinstance(a, dict) and not a.get("skipped")),
            {},
        )
    trap = float(fused.get("top_k_false_trap_rate") or 0.0)
    true_s = float(fused.get("top_k_true_S_rate") or 0.0)
    same_sym = float(fused.get("same_symbol_ratio") or 0.0)
    n_returned = int(fused.get("top_k_returned") or 0)

    if n_returned == 0:
        return {
            "stance": "abstain",
            "interpretation": "No historical support after leakage guards.",
        }
    if trap >= 0.35:
        return {
            "stance": "caution",
            "interpretation": f"Elevated false-trap rate in support set ({trap:.0%}).",
        }
    if same_sym >= 0.5:
        return {
            "stance": "lower_confidence",
            "interpretation": "Support dominated by same-symbol neighbors; down-weight recall.",
        }
    if true_s >= 0.5 and trap < 0.2:
        return {
            "stance": "confirm",
            "interpretation": f"Support skews true_S ({true_s:.0%}) with low trap rate.",
        }
    return {
        "stance": "caution",
        "interpretation": "Mixed historical labels; use as context only.",
    }


def format_evidence_for_prompt(card: dict[str, Any], interpretation: dict[str, str]) -> str:
    """Compact prompt block — evidence layer, not execution authority."""
    lines = [
        "## Pattern Recall Evidence (historical cases, NOT trade signals)",
        f"Stance: {interpretation.get('stance', 'abstain')} — {interpretation.get('interpretation', '')}",
        f"Version: {card.get('evidence_version', EVIDENCE_VERSION)} | horizon: {card.get('horizon', 'T10')}",
    ]
    for arm_name, metrics in (card.get("arms") or {}).items():
        if not isinstance(metrics, dict) or metrics.get("skipped"):
            lines.append(f"- {arm_name}: skipped ({metrics.get('reason', '?')})")
            continue
        lines.append(
            f"- {arm_name}: true_S={metrics.get('top_k_true_S_rate', 0):.0%}, "
            f"false_trap={metrics.get('top_k_false_trap_rate', 0):.0%}, "
            f"same_symbol={metrics.get('same_symbol_ratio', 0):.0%}, "
            f"n={metrics.get('top_k_returned', 0)}"
        )
    for w in card.get("warnings") or []:
        lines.append(f"Warning: {w}")
    lines.append(
        "You may use this to adjust confidence or request more context. "
        "Do NOT treat similarity as a buy/sell command; PositionPolicy owns sizing."
    )
    return "\n".join(lines)


def evidence_card_to_ledger_fields(
    card: dict[str, Any],
    interpretation: dict[str, str],
    *,
    embedding_arm: str = "fused_concat_v1",
) -> dict[str, Any]:
    """Flatten card for DecisionLedger persistence."""
    case_ids: list[str] = []
    arms = card.get("arms") or {}
    primary = arms.get(embedding_arm) or {}
    if isinstance(primary, dict):
        case_ids = list(primary.get("case_ids") or [])

    return {
        "pattern_recall_version": card.get("evidence_version", EVIDENCE_VERSION),
        "embedding_arm": embedding_arm,
        "stats_id": card.get("stats_id"),
        "pca_artifact_id": card.get("pca_artifact_id"),
        "top_k_case_ids": json.dumps(case_ids, ensure_ascii=False),
        "evidence_card_json": json.dumps(card, ensure_ascii=False, default=str),
        "fund_manager_interpretation": json.dumps(interpretation, ensure_ascii=False),
    }