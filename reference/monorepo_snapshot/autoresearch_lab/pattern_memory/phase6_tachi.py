"""Phase 6: Promote selected patterns to HyperTachi semantic memory.

Selects high-quality patterns (archetypal true_S, clear false_trap, Wyckoff spring,
volume climax, divergence trap) and writes natural-language summaries to HyperTachi
with tier=pattern (30,000-day half-life).

HyperTachi's Python client (``engine.v8.infra.tachi_client``) currently exposes
``save_memory / search_memory / recall_context / memory_graph`` — there is no
``save_relation`` tool. To still land semantic edges in Tachi, we encode them
in each saved memory's ``metadata.links`` list and also dump a standalone
graph-edge JSON to ``data/results/phase6_graph_edges.json`` so a future
hypertachi relation API can re-walk them in one pass.

Usage:
    uv run python -m autoresearch_lab.pattern_memory.phase6_tachi --top-n 50
    uv run python -m autoresearch_lab.pattern_memory.phase6_tachi --top-n 50 --dry-run
    uv run python -m autoresearch_lab.pattern_memory.phase6_tachi --edges-only
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _PROJECT_ROOT / "data" / "results"
_GRAPH_EDGES_PATH = _RESULTS_DIR / "phase6_graph_edges.json"

EDGE_TYPES: tuple[str, ...] = ("similar_to", "follows", "supports", "recovered_from")

# ── Archetype selection criteria ──
ARCHETYPES = [
    {
        "name": "classic_true_S",
        "keyword": "true_S_breakout",
        "max_per_symbol": 3,
        "sql_filter": "label_T10 = 'true_S' AND fwd_return_T10 > 15 AND mae_T10 > -5 AND v8_grade IN ('A','B+','B')",
    },
    {
        "name": "classic_false_trap",
        "keyword": "false_trap",
        "max_per_symbol": 3,
        "sql_filter": "label_T10 = 'false_trap' AND mae_T10 < -10 AND v8_grade IN ('A','B+','B')",
    },
    {
        "name": "wyckoff_spring",
        "keyword": "spring_launch",
        "max_per_symbol": 2,
        "sql_filter": "spring_launch = 1 AND label_T20 = 'true_S' AND mae_T5 > -8",
    },
    {
        "name": "volume_climax_top",
        "keyword": "volume_climax",
        "max_per_symbol": 2,
        "sql_filter": "label_T20 = 'stale_S' AND fwd_return_T20 < -5",
    },
    {
        "name": "divergence_trap",
        "keyword": "divergence_trap",
        "max_per_symbol": 2,
        "sql_filter": "chan_divergence_flag = 1 AND label_T10 = 'false_trap'",
    },
    {
        "name": "high_confidence_bsp",
        "keyword": "chan_bsp",
        "max_per_symbol": 2,
        "sql_filter": "chan_bsp_types IS NOT NULL AND v8_grade IN ('S','A') AND label_T10 = 'true_S'",
    },
]


def _escape_md(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("`", "\\`")


def select_patterns(store, max_total: int = 50) -> list[dict]:
    """Select diverse, high-quality patterns from the store."""
    selected: list[dict] = []
    seen_pattern_ids: set[str] = set()
    symbol_counts: dict[str, int] = {}

    for archetype in ARCHETYPES:
        remaining = max_total - len(selected)
        if remaining <= 0:
            break

        rows = store.con.execute(
            f"SELECT pattern_id, symbol, name, as_of_date, v8_grade, v8_score, "
            f"chan_trend_type, chan_bsp_side, chan_bsp_types, spring_coiling, spring_launch, "
            f"label_T10, fwd_return_T10, mae_T10, "
            f"label_T20, fwd_return_T20, mae_T20 "
            f"FROM pattern_snapshot "
            f"WHERE {archetype['sql_filter']} "
            f"ORDER BY v8_score DESC LIMIT {remaining * 3}"
        ).fetchall()

        for row in rows:
            pid = row[0]
            sym = row[1]
            if pid in seen_pattern_ids:
                continue
            if symbol_counts.get(sym, 0) >= archetype["max_per_symbol"]:
                continue

            seen_pattern_ids.add(pid)
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
            selected.append({
                "pattern_id": pid,
                "symbol": sym,
                "name": row[2] or sym,
                "as_of_date": row[3],
                "v8_grade": row[4],
                "v8_score": row[5],
                "chan_trend_type": row[6],
                "chan_bsp_side": row[7],
                "chan_bsp_types": row[8],
                "spring_coiling": row[9],
                "spring_launch": row[10],
                "label_T10": row[11],
                "fwd_return_T10": row[12],
                "mae_T10": row[13],
                "label_T20": row[14],
                "fwd_return_T20": row[15],
                "mae_T20": row[16],
                "archetype": archetype["name"],
                "archetype_keyword": archetype["keyword"],
            })
            if len(selected) >= max_total:
                break

    return selected


def format_memory_text(p: dict) -> str:
    """Generate natural-language memory text for a pattern."""
    parts = [
        f"[{p['as_of_date']}] {p['symbol']} {p['name']}: {p['archetype'].replace('_', ' ')} detected.",
        f"V8={p['v8_grade']}({p['v8_score']:.0f}), "
        f"Chan={p['chan_trend_type'] or '?'} {p['chan_bsp_side'] or ''} {p['chan_bsp_types'] or ''}.",
    ]

    if p.get("spring_coiling"):
        parts.append("Spring coiling active.")
    if p.get("spring_launch"):
        parts.append("Spring launch confirmed.")

    parts.append(
        f"T10: {p['label_T10']}, fwd_return={p['fwd_return_T10']:+.1f}%, MAE={p['mae_T10']:+.1f}%."
    )
    parts.append(
        f"T20: {p['label_T20']}, fwd_return={p['fwd_return_T20']:+.1f}%, MAE={p['mae_T20']:+.1f}%."
    )
    return " ".join(parts)


def promote_to_tachi(
    patterns: list[dict],
    dry_run: bool = False,
    *,
    graph_edges: list[dict] | None = None,
) -> dict:
    """Write selected patterns to HyperTachi memory.

    Parameters
    ----------
    patterns : list[dict]
        Patterns selected by ``select_patterns()``.
    dry_run : bool
        If True, do not write — just return preview payloads.
    graph_edges : list[dict] | None
        Pre-computed edges (output of ``compute_pattern_graph``). Each entry is
        ``{source_pattern_id, target_pattern_id, relation, weight, evidence}``.
        These land in each saved memory's ``metadata.links`` so a future
        ``tachi_save_relation`` tool (or hypertachi edge API) can re-walk them.
    """
    try:
        from engine.v8.infra.tachi_client import save_memory
    except ImportError:
        logger.warning("tachi_client not available, writing to JSON fallback")
        return _fallback_json(patterns, graph_edges)

    edges_by_source: dict[str, list[dict]] = defaultdict(list)
    for edge in graph_edges or []:
        edges_by_source[edge["source_pattern_id"]].append(edge)

    saved = 0
    failed = 0
    results = []

    for p in patterns:
        text = format_memory_text(p)
        path = f"/trading/equity/patterns/{p['symbol']}/{p['as_of_date']}"

        if dry_run:
            results.append({"path": path, "text": text[:120] + "..."})
            continue

        try:
            links = edges_by_source.get(p["pattern_id"], [])
            metadata: dict[str, Any] = {
                "pattern_id": p["pattern_id"],
                "archetype": p["archetype"],
                "v8_grade": p["v8_grade"],
                "v8_score": p["v8_score"],
                "label_T10": p["label_T10"],
                "fwd_return_T10": p["fwd_return_T10"],
                "mae_T10": p["mae_T10"],
                "chan_trend_type": p["chan_trend_type"],
                "chan_bsp_side": p["chan_bsp_side"],
                "source": "phase6_auto_promote",
            }
            if links:
                metadata["links"] = [
                    {
                        "target_pattern_id": e["target_pattern_id"],
                        "relation": e["relation"],
                        "weight": round(float(e.get("weight", 0.0)), 4),
                        "evidence": e.get("evidence", ""),
                    }
                    for e in links
                ]
            save_memory(
                text=text,
                path=path,
                importance=0.85,
                summary=p["archetype"].replace("_", " "),
                keywords=["pattern", p["archetype_keyword"], p["label_T10"] or "unknown", p["symbol"]],
                entities=[p["symbol"], p["name"] or p["symbol"]],
                retention_policy="permanent",
                metadata=metadata,
                project="hyperion",
                domain="equity_trading",
                force=True,
            )
            saved += 1
            results.append({"status": "saved", "path": path,
                            "n_links": len(links)})
        except Exception as e:
            logger.warning("Failed to save %s: %s", p["pattern_id"], e)
            failed += 1
            results.append({"status": "failed", "path": path, "error": str(e)})

    return {"saved": saved, "failed": failed, "dry_run": dry_run, "results": results}


def _fallback_json(patterns: list[dict], graph_edges: list[dict] | None = None) -> dict:
    """Fallback: write to JSON when tachi_client unavailable."""
    out = _PROJECT_ROOT / "data" / "results" / "phase6_patterns.json"
    edges_by_source: dict[str, list[dict]] = defaultdict(list)
    for e in graph_edges or []:
        edges_by_source[e["source_pattern_id"]].append(e)
    entries = [{"path": f"/trading/equity/patterns/{p['symbol']}/{p['as_of_date']}",
                "text": format_memory_text(p),
                "tier": "pattern", "importance": 0.80,
                "keywords": ["pattern", p["archetype_keyword"], p["label_T10"] or "unknown", p["symbol"]],
                "metadata": {"pattern_id": p["pattern_id"], "archetype": p["archetype"],
                             "links": edges_by_source.get(p["pattern_id"], [])}}
               for p in patterns]
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False, default=str))
    return {"saved": 0, "failed": 0, "fallback_json": str(out), "n_entries": len(entries)}


def compute_pattern_graph(
    store: Any,
    patterns: list[dict],
    *,
    follow_window_bars: int = 5,
    follow_max_per_symbol: int = 3,
    similar_top_k: int = 3,
    similar_min_sim: float = 0.7,
    recovery_window_bars: int = 30,
    max_total: int = 2000,
) -> list[dict]:
    """Build semantic edges for the selected patterns.

    Edge types emitted:
    - ``similar_to``: cosine sim of fused_vector >= ``similar_min_sim`` for top-k neighbours
    - ``follows``: same symbol, next chronological pattern within ``follow_window_bars`` trade days
    - ``recovered_from``: same symbol, a true_S pattern that came after a false_trap within
      ``recovery_window_bars`` trade days
    - ``supports``: same archetype, different symbol, within 90 days (cross-symbol corroboration)

    All edges are returned in a flat list so the caller can both embed them in
    ``metadata.links`` and dump a standalone graph JSON.
    """
    import numpy as np

    selected_ids = {p["pattern_id"] for p in patterns}
    meta_by_id: dict[str, dict[str, Any]] = {}
    if selected_ids:
        rows = store.con.execute(
            """
            SELECT pattern_id, symbol, as_of_date, trade_idx, label_T10
            FROM pattern_snapshot
            WHERE pattern_id IN ({})
            """.format(",".join("?" * len(selected_ids))),
            list(selected_ids),
        ).fetchall()
        meta_by_id = {
            r[0]: {
                "symbol": r[1],
                "as_of_date": str(r[2])[:10],
                "trade_idx": int(r[3]),
                "label_T10": r[4],
            }
            for r in rows
        }

    def _trade_idx(p: dict) -> int | None:
        value = p.get("trade_idx", meta_by_id.get(p["pattern_id"], {}).get("trade_idx"))
        return int(value) if value is not None else None

    def _as_of_date(p: dict) -> str:
        return str(p.get("as_of_date", meta_by_id.get(p["pattern_id"], {}).get("as_of_date", "")))[:10]

    def _label_t10(p: dict) -> str | None:
        return p.get("label_T10", meta_by_id.get(p["pattern_id"], {}).get("label_T10"))

    def _gap_bars(left: dict, right: dict) -> int | None:
        left_idx = _trade_idx(left)
        right_idx = _trade_idx(right)
        if left_idx is not None and right_idx is not None:
            return right_idx - left_idx
        try:
            return (date.fromisoformat(_as_of_date(right)) - date.fromisoformat(_as_of_date(left))).days
        except ValueError:
            return None

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for p in patterns:
        by_symbol[p["symbol"]].append(p)
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda p: (_trade_idx(p) if _trade_idx(p) is not None else 10**12, _as_of_date(p)))

    edges: list[dict] = []
    edge_count: dict[str, int] = {et: 0 for et in EDGE_TYPES}

    def _add(source: str, target: str, relation: str, weight: float, evidence: str) -> None:
        if source == target:
            return
        edges.append({
            "source_pattern_id": source,
            "target_pattern_id": target,
            "relation": relation,
            "weight": float(weight),
            "evidence": evidence,
        })
        edge_count[relation] = edge_count.get(relation, 0) + 1

    # ── follows: same-symbol temporal succession ────────────────────────
    for sym, plist in by_symbol.items():
        for i, p in enumerate(plist):
            emitted = 0
            for j in range(i + 1, len(plist)):
                nxt = plist[j]
                bars = _gap_bars(p, nxt)
                if bars is None or bars <= 0:
                    continue
                if bars > follow_window_bars:
                    break
                _add(
                    p["pattern_id"], nxt["pattern_id"], "follows",
                    weight=max(0.0, 1.0 - bars / max(follow_window_bars, 1)),
                    evidence=f"same symbol, +{bars} trade days",
                )
                emitted += 1
                if emitted >= follow_max_per_symbol:
                    break

    # ── recovered_from: true_S after false_trap on the same symbol ──────
    for sym, plist in by_symbol.items():
        for i, p in enumerate(plist):
            if _label_t10(p) != "true_S":
                continue
            for back in plist[:i][::-1]:
                if _label_t10(back) != "false_trap":
                    continue
                bars = _gap_bars(back, p)
                if bars is None or bars <= 0:
                    continue
                if bars > recovery_window_bars:
                    break
                _add(
                    p["pattern_id"], back["pattern_id"], "recovered_from",
                    weight=1.0,
                    evidence=f"same symbol, true_S after false_trap (+{bars} trade days)",
                )
                break

    # ── similar_to: fused vector top-k neighbours ──────────────────────
    if similar_top_k > 0:
        rows = store.con.execute(
            """
            SELECT pattern_id, fused_vector
            FROM pattern_snapshot
            WHERE pattern_id IN ({}) AND fused_vector IS NOT NULL
            """.format(",".join("?" * len(selected_ids))),
            list(selected_ids),
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            mat = np.asarray([r[1] for r in rows], dtype=np.float64)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            unit = mat / norms
            sim = unit @ unit.T
            np.fill_diagonal(sim, -np.inf)
            top_idx = np.argsort(-sim, axis=1)[:, :similar_top_k]
            for i, src in enumerate(ids):
                for j in top_idx[i]:
                    if j == i:
                        continue
                    w = float(sim[i, j])
                    if w < similar_min_sim:
                        continue
                    _add(
                        src, ids[int(j)], "similar_to",
                        weight=w,
                        evidence=f"fused cosine sim={w:.3f}",
                    )

    # ── supports: same archetype, different symbol, within 90 days ──────
    by_arch: dict[str, list[dict]] = defaultdict(list)
    for p in patterns:
        by_arch[p["archetype"]].append(p)
    for arch, plist in by_arch.items():
        for i, p in enumerate(plist):
            for q in plist[i + 1:]:
                if p["symbol"] == q["symbol"]:
                    continue
                try:
                    d0 = _as_of_date(p)
                    d1 = _as_of_date(q)
                    days = abs((date.fromisoformat(d1) - date.fromisoformat(d0)).days)
                except ValueError:
                    continue
                if days > 90:
                    continue
                _add(
                    p["pattern_id"], q["pattern_id"], "supports",
                    weight=max(0.0, 1.0 - days / 90.0),
                    evidence=f"archetype={arch}, cross-symbol, ±{days} days",
                )

    if len(edges) > max_total:
        edges = sorted(edges, key=lambda e: e["weight"], reverse=True)[:max_total]
    return edges


def write_graph_edges_json(edges: list[dict], path: Path = _GRAPH_EDGES_PATH) -> Path:
    """Write the flat edge list to a stable JSON for downstream re-walking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = defaultdict(int)
    for e in edges:
        counts[e["relation"]] += 1
    payload = {
        "version": 1,
        "n_edges": len(edges),
        "counts_by_relation": dict(counts),
        "edges": edges,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return path


def run_phase6(top_n: int = 50, dry_run: bool = False, *, edges_only: bool = False):
    """Run Phase 6: select and promote patterns to HyperTachi.

    Parameters
    ----------
    top_n : int
        Maximum number of patterns to select and promote.
    dry_run : bool
        Preview only; nothing is written to Tachi.
    edges_only : bool
        Build and write the graph-edges JSON but do not promote to Tachi.
    """
    from autoresearch_lab.pattern_memory.store import PatternStore

    t0 = time.monotonic()
    store = PatternStore()

    logger.info("Selecting top %d patterns...", top_n)
    patterns = select_patterns(store, max_total=top_n)

    if not patterns:
        store.close()
        logger.warning("No patterns matched selection criteria")
        return {"error": "no patterns matched"}

    logger.info("Selected %d patterns across %d archetypes", len(patterns),
                len(set(p["archetype"] for p in patterns)))

    for arch in ARCHETYPES:
        count = sum(1 for p in patterns if p["archetype"] == arch["name"])
        if count:
            logger.info("  %s: %d", arch["name"], count)

    logger.info("Computing pattern graph (similar_to/follows/supports/recovered_from)...")
    edges = compute_pattern_graph(store, patterns)
    counts: dict[str, int] = defaultdict(int)
    for e in edges:
        counts[e["relation"]] += 1
    logger.info("Graph edges: %d total (%s)", len(edges), dict(counts))
    edges_path = write_graph_edges_json(edges)

    if edges_only:
        store.close()
        return {
            "edges_only": True,
            "n_patterns": len(patterns),
            "n_edges": len(edges),
            "edges_path": str(edges_path),
            "counts": dict(counts),
            "elapsed_sec": round(time.monotonic() - t0, 2),
        }

    result = promote_to_tachi(patterns, dry_run=dry_run, graph_edges=edges)
    result["graph_edges_path"] = str(edges_path)
    result["graph_edge_counts"] = dict(counts)
    store.close()

    logger.info("Promoted: %d saved, %d failed in %.0fs", result["saved"], result["failed"],
                time.monotonic() - t0)

    if dry_run:
        for r in result.get("results", [])[:5]:
            logger.info("  %s", r)
    elif result.get("fallback_json"):
        logger.info("Fallback written to: %s", result["fallback_json"])

    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Phase 6: Promote patterns to HyperTachi")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--edges-only", action="store_true",
                        help="Compute + write graph edges JSON only; skip Tachi promotion")
    args = parser.parse_args()

    run_phase6(top_n=args.top_n, dry_run=args.dry_run, edges_only=args.edges_only)
