"""Pattern-memory ablation surfaces.

This module keeps both ablation layers that the roadmap now depends on:

1. `rank_ic_ablation()` for the narrow H2/H3 fused-vs-z retrieval gate used by
   the fusion tests and implementation roadmap.
2. `run_ablation()` / `compare_arms()` / `save_ablation_report()` for the
   broader Phase 4 three-way Warpcore/Kronos/Fused report path already merged
   into `main`.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from autoresearch_lab.pattern_memory.bootstrap import bca_bootstrap
from autoresearch_lab.pattern_memory.store import PatternStore

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _PROJECT_ROOT / "data" / "results"
_MIN_GATE_DELTA = 0.02

ARMS: dict[str, str] = {
    "A_warpcore": "z",
    "B_kronos": "kronos",
    "C_fused_pca16": "fused",
}


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation via Pearson on ranks (numpy-only)."""
    if len(x) < 3:
        return float("nan")

    def _rank(a: np.ndarray) -> np.ndarray:
        order = a.argsort()
        ranks = np.empty_like(order, dtype=np.float64)
        ranks[order] = np.arange(len(a), dtype=np.float64)
        return ranks

    rx, ry = _rank(x), _rank(y)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    if denom == 0:
        return float("nan")
    return float((rx * ry).sum() / denom)


def _rank_ic_for(
    store: PatternStore,
    embedding_type: str,
    *,
    k: int,
    purge_bars: int,
    horizon_field: str,
) -> tuple[float, int]:
    """Compute retrieval Rank IC for one embedding type. Returns (ic, n_queries)."""
    horizon = horizon_field.removeprefix("fwd_return_")
    vec_col = {"z": "z_feature_vector", "fused": "fused_vector", "kronos": "kronos_vector"}[
        embedding_type
    ]
    rows = store.con.execute(
        f"""
        SELECT pattern_id, trade_idx, {horizon_field}
        FROM pattern_snapshot
        WHERE {vec_col} IS NOT NULL AND {horizon_field} IS NOT NULL
        ORDER BY pattern_id
        """
    ).fetchall()

    preds: list[float] = []
    actuals: list[float] = []
    for pid, trade_idx, actual_ret in rows:
        hits = store.query_top_k(
            pid,
            query_trade_idx=int(trade_idx),
            embedding_type=embedding_type,
            k=k,
            purge_bars=purge_bars,
            horizon=horizon,
        )
        neighbours = [h[horizon_field] for h in hits if h.get(horizon_field) is not None]
        if not neighbours:
            continue
        preds.append(float(np.mean(neighbours)))
        actuals.append(float(actual_ret))

    if len(preds) < 3:
        return float("nan"), len(preds)
    return _spearman(np.asarray(preds), np.asarray(actuals)), len(preds)


def _select_eval_queries(oos_rows: list[tuple[str, int]], max_queries: int) -> list[tuple[str, int]]:
    """Pick deterministic, time-spread OOS queries instead of the tail regime."""
    if max_queries <= 0 or len(oos_rows) <= max_queries:
        return list(oos_rows)
    idxs = np.linspace(0, len(oos_rows) - 1, num=max_queries, dtype=int)
    return [oos_rows[int(i)] for i in idxs]


def rank_ic_ablation(
    store: PatternStore,
    *,
    k: int = 5,
    purge_bars: int = 20,
    horizon_field: str = "fwd_return_T10",
    gate_delta: float = _MIN_GATE_DELTA,
) -> dict:
    """Run the fused-vs-z Rank IC ablation."""
    z_ic, n_z = _rank_ic_for(
        store, "z", k=k, purge_bars=purge_bars, horizon_field=horizon_field
    )
    fused_ic, n_fused = _rank_ic_for(
        store, "fused", k=k, purge_bars=purge_bars, horizon_field=horizon_field
    )

    delta: Optional[float]
    passes: Optional[bool]
    if np.isnan(z_ic) or np.isnan(fused_ic):
        delta = None
        passes = None
    else:
        delta = fused_ic - z_ic
        passes = delta > gate_delta

    logger.info(
        "rank_ic_ablation: z_ic=%.4f (n=%d) fused_ic=%.4f (n=%d) delta=%s gate=%.3f passes=%s",
        z_ic,
        n_z,
        fused_ic,
        n_fused,
        f"{delta:.4f}" if delta is not None else "n/a",
        gate_delta,
        passes,
    )
    return {
        "z_ic": z_ic,
        "fused_ic": fused_ic,
        "delta": delta,
        "gate_delta": gate_delta,
        "passes_gate": passes,
        "n_z": n_z,
        "n_fused": n_fused,
    }


def _query_metrics(
    store,
    *,
    embedding_type: str,
    top_k: int,
    horizon: str,
    oos_rows: list[tuple[str, int]],
    max_queries: int = 20,
) -> dict[str, Any]:
    """Evaluate one embedding arm on OOS query patterns."""
    label_col = f"label_{horizon}"
    fwd_col = f"fwd_return_{horizon}"
    mae_col = f"mae_{horizon}"

    per_query: list[dict] = []
    true_s_rates: list[float] = []
    trap_rates: list[float] = []
    fwd_returns: list[float] = []
    similarities: list[float] = []

    for pid, tid in _select_eval_queries(oos_rows, max_queries):
        hits = store.query_top_k(
            pid,
            query_trade_idx=tid,
            embedding_type=embedding_type,
            k=top_k,
            horizon=horizon,
            same_symbol_min_gap_bars=30,
        )
        if not hits:
            continue

        row = store.con.execute(
            "SELECT symbol, market_regime FROM pattern_snapshot WHERE pattern_id = ?",
            [pid],
        ).fetchone()
        from autoresearch_lab.pattern_memory.evidence import aggregate_top_k_evidence

        card = aggregate_top_k_evidence(
            hits,
            horizon=horizon,
            query_symbol=row[0] if row else None,
            query_trade_idx=tid,
            query_market_regime=row[1] if row else None,
            embedding_type=embedding_type,
            top_k=top_k,
        )

        avg_ret = card.get("avg_fwd_return")
        worst_mae = card.get("worst_mae")
        avg_sim = float(np.mean([h.get("similarity", 0) or 0 for h in hits]))

        per_query.append({
            "query_id": pid,
            "true_S_rate": card["top_k_true_S_rate"],
            "false_trap_rate": card["top_k_false_trap_rate"],
            "stale_S_rate": card.get("top_k_stale_S_rate"),
            "avg_fwd_return": avg_ret,
            "worst_mae": worst_mae,
            "label_entropy": card.get("label_entropy"),
            "avg_similarity": round(avg_sim, 3),
            "same_symbol_ratio": card.get("same_symbol_ratio"),
            "support_diversity": card.get("support_diversity"),
            "neighbor_age_median": (card.get("neighbor_age_stats") or {}).get("median"),
            "label_distribution": card.get("top_k_label_distribution"),
        })
        true_s_rates.append(card["top_k_true_S_rate"])
        trap_rates.append(card["top_k_false_trap_rate"])
        if avg_ret is not None:
            fwd_returns.append(float(avg_ret))
        similarities.append(avg_sim)

    n = len(per_query)
    same_sym = [q.get("same_symbol_ratio") for q in per_query if q.get("same_symbol_ratio") is not None]
    neighbor_age = [
        q.get("neighbor_age_median") for q in per_query if q.get("neighbor_age_median") is not None
    ]
    aggregate = {
        "n_queries": n,
        "top_k": top_k,
        "horizon": horizon,
        "embedding_type": embedding_type,
        "mean_true_S_rate": round(float(np.mean(true_s_rates)), 3) if n else 0.0,
        "mean_false_trap_rate": round(float(np.mean(trap_rates)), 3) if n else 0.0,
        "mean_stale_S_rate": round(
            float(np.mean([q.get("stale_S_rate", 0) or 0 for q in per_query])), 3
        )
        if n
        else 0.0,
        "mean_avg_fwd_return": round(float(np.mean(fwd_returns)), 2) if fwd_returns else 0.0,
        "mean_similarity": round(float(np.mean(similarities)), 3) if n else 0.0,
        "mean_same_symbol_ratio": round(float(np.mean(same_sym)), 3) if same_sym else 0.0,
        "mean_neighbor_age_median": round(float(np.mean(neighbor_age)), 1) if neighbor_age else None,
        "bca_true_S_rate": bca_bootstrap(true_s_rates) if n else {},
        "per_query": per_query,
    }
    return aggregate


def _label_entropy(labels: list[str]) -> float:
    if not labels:
        return 0.0
    _, counts = np.unique(labels, return_counts=True)
    probs = counts / counts.sum()
    return float(-np.sum(probs * np.log(probs + 1e-12)))


def _arm_available(store, embedding_type: str) -> bool:
    col = {
        "z": "z_feature_vector",
        "kronos": "kronos_vector",
        "fused": "fused_vector",
    }[embedding_type]
    row = store.con.execute(
        f"SELECT COUNT(*) FROM pattern_snapshot WHERE {col} IS NOT NULL"
    ).fetchone()
    return bool(row and row[0] > 0)


def run_ablation(
    *,
    top_k: int = 5,
    horizons: list[str] | None = None,
    max_queries: int = 20,
    train_fraction: float = 0.7,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run all available ablation arms and compare metrics."""
    from autoresearch_lab.pattern_memory import store as store_mod
    from autoresearch_lab.pattern_memory.store import PatternStore

    horizons = horizons or ["T5", "T10", "T20"]
    store = PatternStore(db_path or store_mod._DEFAULT_DB_PATH)

    rows = store.con.execute(
        "SELECT pattern_id, trade_idx FROM pattern_snapshot ORDER BY trade_idx"
    ).fetchall()
    if not rows:
        store.close()
        return {"error": "no patterns in store"}

    split = int(len(rows) * train_fraction)
    oos_rows = [(r[0], int(r[1])) for r in rows[split:]]

    arms_out: dict[str, Any] = {}
    for arm_name, emb_type in ARMS.items():
        if not _arm_available(store, emb_type):
            arms_out[arm_name] = {"skipped": True, "reason": f"no {emb_type} vectors"}
            continue
        arms_out[arm_name] = {
            "skipped": False,
            "horizons": {
                h: _query_metrics(
                    store,
                    embedding_type=emb_type,
                    top_k=top_k,
                    horizon=h,
                    oos_rows=oos_rows,
                    max_queries=max_queries,
                )
                for h in horizons
            },
        }

    store.close()
    decision = compare_arms(arms_out, primary_horizon="T10")
    return {"arms": arms_out, "decision": decision}


def compare_arms(report: dict[str, Any], primary_horizon: str = "T10") -> dict[str, Any]:
    """Apply BCa decision rules across all available arms.

    For each pair (A_warpcore, B_kronos, C_fused_pca16) we ask: does the BCa
    lower bound of arm X strictly exceed the point estimate of arm Y? If yes
    the pair is SIGNIFICANT in X's favour; if only the point estimate wins
    we say UNCERTAIN; if X's point is <= Y's point we say HURTS.

    The final verdict is the arm that wins the most pairwise comparisons,
    prioritised by:
      SIGNIFICANT wins > UNCERTAIN wins > HURTS losses.
    """
    arms_present = {
        name: data
        for name, data in report.items()
        if isinstance(data, dict) and not data.get("skipped")
        and "horizons" in data
    }

    if "A_warpcore" not in arms_present:
        return {
            "verdict": "PENDING",
            "reason": "Warpcore arm missing; cannot evaluate.",
        }
    if len(arms_present) < 2:
        return {
            "verdict": "PENDING",
            "reason": (
                f"Only {list(arms_present.keys())} available; need at least 2 arms for comparison."
            ),
        }

    def _metrics(arm_name: str) -> dict:
        return arms_present[arm_name]["horizons"][primary_horizon]

    def _pair(left: str, right: str) -> dict:
        l = _metrics(left)
        r = _metrics(right)
        l_point = l.get("mean_true_S_rate", 0.0)
        r_point = r.get("mean_true_S_rate", 0.0)
        l_bca = l.get("bca_true_S_rate", {})
        l_lower = l_bca.get("lower", 0.0)
        r_bca = r.get("bca_true_S_rate", {})
        r_lower = r_bca.get("lower", 0.0)
        if l_lower > r_point:
            verdict, sig = "SIGNIFICANT", True
            reason = f"{left} BCa lower ({l_lower}) > {right} point ({r_point})"
        elif l_point > r_point:
            verdict, sig = "UNCERTAIN", False
            reason = f"{left} point ({l_point}) > {right} ({r_point}) but CI overlaps"
        else:
            verdict, sig = "HURTS", False
            reason = f"{left} point ({l_point}) <= {right} point ({r_point})"
        return {
            "verdict": verdict,
            "significant": sig,
            "reason": reason,
            "left_arm": left,
            "right_arm": right,
            "left_point": l_point,
            "right_point": r_point,
            "left_bca": l_bca,
            "right_bca": r_bca,
        }

    pairs: dict[str, dict] = {}
    arm_names = list(arms_present.keys())
    for i, a in enumerate(arm_names):
        for b in arm_names[i + 1:]:
            key = f"{a}_vs_{b}"
            pairs[key] = _pair(a, b)
            pairs[f"{b}_vs_{a}"] = _pair(b, a)

    tally: dict[str, dict[str, int]] = {
        name: {"SIGNIFICANT": 0, "UNCERTAIN": 0, "HURTS": 0} for name in arm_names
    }
    for k, v in pairs.items():
        left = v["left_arm"]
        tally[left][v["verdict"]] += 1

    score: dict[str, tuple[int, int, int]] = {
        name: (tally[name]["SIGNIFICANT"], tally[name]["UNCERTAIN"], tally[name]["HURTS"])
        for name in arm_names
    }
    # Higher SIGNIFICANT / UNCERTAIN is better, but higher HURTS is worse.
    rank_score: dict[str, tuple[int, int, int]] = {
        name: (score[name][0], score[name][1], -score[name][2])
        for name in arm_names
    }
    ranked = sorted(arm_names, key=lambda n: rank_score[n], reverse=True)
    champion = ranked[0]
    champion_metrics = _metrics(champion)
    second = ranked[1] if len(ranked) > 1 else None

    champion_sig_wins = tally[champion]["SIGNIFICANT"]
    champion_hurts = tally[champion]["HURTS"]
    if champion_sig_wins >= (len(arm_names) - 1) and champion_hurts == 0:
        verdict = "SIGNIFICANT"
        reason = f"{champion} won every pairwise comparison (SIG x {champion_sig_wins})."
    elif second is not None and rank_score[champion] == rank_score.get(second, (0, 0, 0)):
        verdict = "TIED"
        reason = f"{champion} and {second} tied on (SIG,UNCERTAIN,HURTS)={score[champion]}."
    else:
        verdict = "UNCERTAIN"
        reason = f"{champion} leads by (SIG,UNCERTAIN,HURTS)={score[champion]} over {second}={score.get(second)}."

    return {
        "verdict": verdict,
        "reason": reason,
        "primary_horizon": primary_horizon,
        "champion": champion,
        "ranking": [{"arm": name, "score": list(score[name])} for name in ranked],
        "pairwise": pairs,
        "tally": tally,
        "champion_metrics": {
            "true_S_rate": champion_metrics.get("mean_true_S_rate", 0.0),
            "false_trap_rate": champion_metrics.get("mean_false_trap_rate", 0.0),
            "avg_fwd_return": champion_metrics.get("mean_avg_fwd_return", 0.0),
            "bca": champion_metrics.get("bca_true_S_rate", {}),
        },
    }


def save_ablation_report(report: dict[str, Any]) -> Path:
    """Write JSON (+ markdown summary) under data/results/."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = _RESULTS_DIR / f"phase4_ablation_{ts}.json"
    md_path = _RESULTS_DIR / f"phase4_ablation_{ts}.md"

    json_path.write_text(json.dumps(report, indent=2, default=str))

    decision = report.get("decision", {})
    lines = [
        "# Phase 4 Ablation Report",
        "",
        f"**Champion**: {decision.get('champion', '?')}",
        "",
        f"**Verdict**: {decision.get('verdict', '?')}",
        "",
        decision.get("reason", ""),
        "",
    ]
    ranking = decision.get("ranking", [])
    if ranking:
        lines.append("## Ranking")
        lines.append("")
        for row in ranking:
            sig, unc, hur = row["score"]
            lines.append(f"- {row['arm']}: SIGNIFICANT={sig} UNCERTAIN={unc} HURTS={hur}")
        lines.append("")

    pairwise = decision.get("pairwise", {})
    if pairwise:
        lines.append("## Pairwise (BCa vs point)")
        lines.append("")
        for k, v in pairwise.items():
            lines.append(f"- {k}: {v['verdict']} — {v['reason']}")
        lines.append("")

    for arm, data in report.get("arms", {}).items():
        if data.get("skipped"):
            lines.append(f"## {arm} — SKIPPED ({data.get('reason')})")
            continue
        lines.append(f"## {arm}")
        for h, metrics in data.get("horizons", {}).items():
            lines.append(
                f"- **{h}**: true_S@5={metrics.get('mean_true_S_rate', 0):.1%}, "
                f"trap={metrics.get('mean_false_trap_rate', 0):.1%}, "
                f"sim={metrics.get('mean_similarity', 0):.3f}"
            )
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n")
    logger.info("Wrote %s and %s", json_path, md_path)
    return json_path


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Phase 4 three-way ablation")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-queries", type=int, default=20)
    args = parser.parse_args()

    result = run_ablation(top_k=args.top_k, max_queries=args.max_queries)
    path = save_ablation_report(result)
    print(f"Report: {path}")
    print(f"Verdict: {result.get('decision', {}).get('verdict')}")
