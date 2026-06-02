"""Aggregate pattern-recall top-k neighbors into an auditable evidence card."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Optional


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total > 0 else 0.0


def _quantile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered)) - 1)))
    return round(ordered[idx], 6)


def aggregate_top_k_evidence(
    results: list[dict],
    *,
    horizon: str = "T10",
    query_symbol: str | None = None,
    query_trade_idx: int | None = None,
    query_market_regime: str | None = None,
    embedding_type: str = "z",
    top_k: int | None = None,
) -> dict[str, Any]:
    """Summarize raw ``query_top_k`` neighbors into retrieval-layer metrics."""
    label_col = f"label_{horizon}"
    fwd_col = f"fwd_return_{horizon}"
    mae_col = f"mae_{horizon}"

    n = len(results)
    effective_k = top_k if top_k is not None else n
    labels = [r.get(label_col) for r in results]
    label_dist = dict(Counter(lbl for lbl in labels if lbl is not None))

    true_s = sum(1 for lbl in labels if lbl == "true_S")
    stale_s = sum(1 for lbl in labels if lbl == "stale_S")
    false_trap = sum(1 for lbl in labels if lbl == "false_trap")

    fwd_vals = [float(r[fwd_col]) for r in results if r.get(fwd_col) is not None]
    mae_vals = [float(r[mae_col]) for r in results if r.get(mae_col) is not None]

    same_symbol = 0
    if query_symbol:
        same_symbol = sum(1 for r in results if r.get("symbol") == query_symbol)

    symbols = {r.get("symbol") for r in results if r.get("symbol")}
    support_diversity = round(len(symbols) / n, 4) if n else 0.0

    neighbor_ages: list[int] = []
    if query_trade_idx is not None:
        for r in results:
            cand_idx = r.get("trade_idx")
            if cand_idx is None:
                continue
            neighbor_ages.append(int(query_trade_idx) - int(cand_idx))

    regime_vals = [r.get("market_regime") for r in results if r.get("market_regime")]
    regime_match_rate = None
    if query_market_regime and regime_vals:
        matches = sum(1 for rg in regime_vals if rg == query_market_regime)
        regime_match_rate = _rate(matches, len(regime_vals))

    label_entropy = 0.0
    if n > 0 and label_dist:
        for count in label_dist.values():
            p = count / n
            if p > 0:
                label_entropy -= p * math.log(p)
        label_entropy = round(label_entropy, 4)

    card: dict[str, Any] = {
        "evidence_version": "pm_v1",
        "embedding_type": embedding_type,
        "horizon": horizon,
        "top_k_requested": effective_k,
        "top_k_returned": n,
        "top_k_label_distribution": label_dist,
        "top_k_true_S_rate": _rate(true_s, n),
        "top_k_stale_S_rate": _rate(stale_s, n),
        "top_k_false_trap_rate": _rate(false_trap, n),
        "label_entropy": label_entropy,
        "avg_fwd_return": round(sum(fwd_vals) / len(fwd_vals), 6) if fwd_vals else None,
        "median_fwd_return": _quantile(fwd_vals, 0.5),
        "worst_mae": round(min(mae_vals), 6) if mae_vals else None,
        "mae_quantiles": {
            "p25": _quantile(mae_vals, 0.25),
            "p50": _quantile(mae_vals, 0.5),
            "p75": _quantile(mae_vals, 0.75),
        },
        "neighbor_age_stats": {
            "median": _quantile([float(x) for x in neighbor_ages], 0.5) if neighbor_ages else None,
            "min": min(neighbor_ages) if neighbor_ages else None,
            "max": max(neighbor_ages) if neighbor_ages else None,
        },
        "same_symbol_ratio": _rate(same_symbol, n),
        "support_diversity": support_diversity,
        "regime_match_rate": regime_match_rate,
        "case_ids": [r.get("pattern_id") for r in results if r.get("pattern_id")],
        "warnings": [],
    }

    if card["same_symbol_ratio"] > 0.5:
        card["warnings"].append(
            "same-symbol support ratio high; treat confidence as lower"
        )
    if n == 0:
        card["warnings"].append("no neighbors returned after leakage guards")
    elif n < max(1, (effective_k or 1) // 2):
        card["warnings"].append("sparse support set")

    return card