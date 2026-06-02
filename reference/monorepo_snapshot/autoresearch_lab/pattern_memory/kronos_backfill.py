"""Point-in-time Kronos vector backfill for pattern_snapshot.

Closes the wiring gap between the Kronos encoder and the fused-recall path
(``autoresearch_lab.pattern_memory.fusion``): ``pattern_snapshot.kronos_vector``
was never populated for historical rows, so ``build_fused_vectors`` had no
inputs.

Correctness contract
---------------------
Each ``pattern_snapshot`` row is point-in-time, anchored on ``as_of_date``
(``trade_idx`` is only a positional index into the *original* bounded kline
load and must NOT be reused against a differently-sized fetch — see
``snapshot_factory._build_snapshot_at``). This backfill therefore:

1. anchors on ``as_of_date`` (absolute, stable);
2. loads each symbol's full daily series ONCE from the offline lab warehouse
   (DuckDB/Parquet + hot SQLite cache via :class:`DuckDBLab`) — never a live
   market API, per ``autoresearch_lab/AGENTS.md`` rule 2;
3. slices the trailing ``length`` bars ending at (and including) ``as_of_date``,
   exactly reproducing the tail of ``df.iloc[:day_idx + 1]``;
4. embeds with the native Kronos encoder and writes back via
   ``store.update_kronos_vector``.

Run ``build_fused_vectors`` afterwards to produce ``fused_vector``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LENGTH = 256


def backfill_kronos_vectors(
    store,
    extractor,
    *,
    period: str = "day",
    length: int = _DEFAULT_LENGTH,
    limit: int = 0,
    only_missing: bool = True,
    commit: bool = True,
    lab=None,
) -> dict[str, Any]:
    """Embed and write ``kronos_vector`` for pattern_snapshot rows.

    Parameters
    ----------
    store : PatternStore
        Open lab.duckdb-backed pattern store.
    extractor : KronosExtractor
        Loaded Kronos encoder (``extractor._model`` must not be None).
    period : str
        Kline period to embed (default ``"day"``; matches snapshot_factory).
    length : int
        Trailing bar count per embedding window (default 256).
    limit : int
        Cap the number of target rows processed (0 = all). Useful for smoke runs.
    only_missing : bool
        When True, only rows with NULL ``kronos_vector`` are processed.
    commit : bool
        When False, embeddings are computed but not written (dry run).
    lab : DuckDBLab, optional
        Offline kline source. Constructed lazily if not supplied.

    Returns
    -------
    dict
        Summary with counts and per-reason skip tallies.
    """
    if getattr(extractor, "_model", None) is None:
        return {
            "status": "failed",
            "error": "Kronos model not loaded",
            "n_targets": 0,
            "n_written": 0,
        }

    targets = store.iter_kronos_targets(only_missing=only_missing)
    if period:
        targets = [t for t in targets if t.get("period", period) == period]
    if limit > 0:
        targets = targets[:limit]

    n_targets = len(targets)
    if n_targets == 0:
        return {
            "status": "ok",
            "n_targets": 0,
            "n_symbols": 0,
            "n_written": 0,
            "n_skipped": 0,
            "skips": {},
        }

    owns_lab = lab is None
    if owns_lab:
        from autoresearch_lab.store.duckdb_lab import DuckDBLab

        lab = DuckDBLab()

    # Group targets by symbol so each daily series is loaded once.
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for t in targets:
        by_symbol[t["symbol"]].append(t)

    n_written = 0
    skips: dict[str, int] = defaultdict(int)

    try:
        for symbol, rows in by_symbol.items():
            df = _load_full_series(lab, symbol, period)
            if df is None or len(df) == 0:
                skips["no_series"] += len(rows)
                logger.warning("backfill: no offline series for %s (%d rows)", symbol, len(rows))
                continue

            # Map as_of_date -> positional index (last occurrence wins).
            date_pos = {str(d)[:10]: i for i, d in enumerate(df["date"].tolist())}

            for r in rows:
                pos = date_pos.get(r["as_of_date"])
                if pos is None:
                    skips["date_not_in_series"] += 1
                    continue
                window = df.iloc[: pos + 1].tail(length)
                if len(window) < 2:
                    skips["insufficient_bars"] += 1
                    continue
                emb = extractor.embed_dataframe(window, label=r["pattern_id"])
                if emb is None:
                    skips["embed_failed"] += 1
                    continue
                if commit:
                    store.update_kronos_vector(r["pattern_id"], [float(x) for x in emb])
                n_written += 1
    finally:
        if owns_lab:
            _close_quietly(lab)

    n_skipped = sum(skips.values())
    logger.info(
        "backfill_kronos_vectors: %d targets, %d symbols, %d written, %d skipped (commit=%s)",
        n_targets, len(by_symbol), n_written, n_skipped, commit,
    )
    return {
        "status": "ok",
        "n_targets": n_targets,
        "n_symbols": len(by_symbol),
        "n_written": n_written,
        "n_skipped": n_skipped,
        "skips": dict(skips),
        "commit": commit,
    }


def _load_full_series(lab, symbol: str, period: str):
    """Load the full ascending daily series for *symbol* from the offline lab."""
    try:
        df = lab.load_kline(symbol, period=period, limit=0)
    except Exception:
        logger.debug("backfill: load_kline failed for %s/%s", symbol, period, exc_info=True)
        return None
    if df is None or len(df) == 0 or "date" not in df.columns:
        return None
    return df


def _close_quietly(lab) -> None:
    close = getattr(lab, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    else:
        con = getattr(lab, "con", None)
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def run_backfill(params: Optional[dict] = None, run_id: str = "") -> dict[str, Any]:
    """Action entry point: backfill kronos_vector then optionally fuse.

    Params: ``period``, ``length``, ``limit``, ``only_missing``, ``model_name``,
    ``fuse`` (default True -> also run build_fused_vectors).
    """
    params = params or {}
    from autoresearch_lab.kronos.extractor import KronosExtractor
    from autoresearch_lab.pattern_memory.store import PatternStore

    model_name = str(params.get("model_name", "kronos-small"))
    period = str(params.get("period", "day"))
    length = int(params.get("length", _DEFAULT_LENGTH))
    limit = int(params.get("limit", 0))
    only_missing = bool(params.get("only_missing", True))
    fuse = bool(params.get("fuse", True))

    try:
        extractor = KronosExtractor(model_name=model_name)
    except Exception as exc:
        return {"run_id": run_id, "action": "kronos_backfill", "status": "failed",
                "error": f"extractor init failed: {exc}"}

    store = PatternStore()
    try:
        result = backfill_kronos_vectors(
            store, extractor,
            period=period, length=length, limit=limit, only_missing=only_missing,
        )
        if fuse and result.get("n_written", 0) > 0:
            from autoresearch_lab.pattern_memory.fusion import build_fused_vectors

            result["fusion"] = build_fused_vectors(store)
    finally:
        store.close()

    result.update({"run_id": run_id, "action": "kronos_backfill", "model_name": model_name})
    return result
