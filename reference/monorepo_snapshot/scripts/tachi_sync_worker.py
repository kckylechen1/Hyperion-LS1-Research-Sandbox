#!/usr/bin/env python3
"""Drain `hapi.db.memory_sync_queue` into Tachi.

Background:
    `engine/v8/position/journal.py` writes trading-journal lessons to the
    `memory_sync_queue` table because Python code cannot directly call the
    Memory MCP `save_memory` tool. The original design called for "Agent
    定期消费" — but that consumer was never implemented, leaving N pending
    rows stranded.

This worker is the consumer. It:
  1. Reads pending rows from `hapi.db.memory_sync_queue`.
  2. Pushes each row into Tachi via the Hermes `TachiMemoryProvider` plugin
     (which encapsulates the MCP stdio session, default project=hyperion,
     default domain=equity_trading).
  3. Marks rows synced via `Journal.mark_memory_synced()`.

Usage:
    uv run python scripts/tachi_sync_worker.py            # one-shot drain
    uv run python scripts/tachi_sync_worker.py --watch    # poll forever (60s)
    uv run python scripts/tachi_sync_worker.py --interval 30 --watch
    uv run python scripts/tachi_sync_worker.py --limit 50 # cap per pass

Exit codes:
    0  success (zero or more rows synced)
    1  Tachi provider unavailable
    2  unhandled error during drain
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from engine.v8.infra import tachi_client  # noqa: E402
from engine.v8.position.journal import Journal  # noqa: E402
from runtime_compat import resolve_hapi_db_path  # noqa: E402

logger = logging.getLogger("tachi_sync_worker")


def _parse_keywords(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(k) for k in raw]
    try:
        decoded = json.loads(raw)
        return [str(k) for k in decoded] if isinstance(decoded, list) else []
    except Exception:
        return [k.strip() for k in str(raw).split(",") if k.strip()]


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        decoded = json.loads(raw)
        return dict(decoded) if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _ensure_claim_columns(db_path: str) -> None:
    columns = {
        "status": "TEXT DEFAULT 'pending'",
        "processing_pid": "INTEGER",
        "processing_started_at": "TEXT",
        "last_error": "TEXT",
        "retry_count": "INTEGER DEFAULT 0",
        "last_attempt_at": "TEXT",
        "domain": "TEXT DEFAULT 'equity_trading'",
        "project": "TEXT DEFAULT 'hyperion'",
    }
    with sqlite3.connect(db_path) as db:
        for name, ddl in columns.items():
            try:
                db.execute(f"ALTER TABLE memory_sync_queue ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "duplicate column" in message:
                    continue
                if "no such table" in message:
                    return
                raise


def _claim_row(db_path: str, queue_id: int) -> bool:
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """UPDATE memory_sync_queue
               SET status = 'processing',
                   processing_pid = ?,
                   processing_started_at = datetime('now', 'localtime')
               WHERE id = ?
                 AND (status = 'pending' OR status = '' OR status IS NULL)""",
            (os.getpid(), queue_id),
        )
        return cursor.rowcount > 0


def _mark_failed(db_path: str, queue_id: int, error: str) -> None:
    try:
        with sqlite3.connect(db_path) as db:
            db.execute(
                """UPDATE memory_sync_queue
                   SET status = 'pending',
                       processing_pid = NULL,
                       processing_started_at = NULL,
                       last_error = ?,
                       retry_count = COALESCE(retry_count, 0) + 1,
                       last_attempt_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (error[:1000], queue_id),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to mark queue id=%s failed: %s", queue_id, exc)


def _release_row(db_path: str, queue_id: int) -> None:
    try:
        with sqlite3.connect(db_path) as db:
            db.execute(
                """UPDATE memory_sync_queue
                   SET status = 'pending',
                       processing_pid = NULL,
                       processing_started_at = NULL
                   WHERE id = ?""",
                (queue_id,),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to release queue id=%s for retry: %s", queue_id, exc)


def _memory_path(row: dict[str, Any]) -> str:
    path = str(row.get("path") or "").strip()
    if path and not path.startswith("/hapi/"):
        return path
    symbol = str(row.get("symbol") or "").strip()
    if not symbol and path:
        tail = path.rstrip("/").rsplit("/", 1)[-1]
        symbol = tail if tail and tail not in {"journal", "hapi", "trading", "equity"} else ""
    if symbol:
        return f"/trading/equity/journal/{symbol}"
    return "/trading/equity/journal"


def _pending_rows(db_path: str) -> list[dict[str, Any]]:
    try:
        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT * FROM memory_sync_queue
                   WHERE status = 'pending' OR status = '' OR status IS NULL
                   ORDER BY created_at"""
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _drain_once(journal: Journal, limit: int | None) -> tuple[int, int]:
    """Return (synced, failed) counts."""
    _ensure_claim_columns(journal.db_path)
    rows = _pending_rows(journal.db_path)
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        return 0, 0

    synced_ids: list[int] = []
    failed = 0
    for row in rows:
        queue_id = int(row["id"])
        if not _claim_row(journal.db_path, queue_id):
            continue
        metadata = _parse_metadata(row.get("metadata"))
        metadata.update({
            "queue_id": queue_id,
            "queued_at": row.get("created_at"),
            "source": "memory_sync_queue",
        })
        try:
            decoded = tachi_client.save_memory(
                text=row["text"],
                summary=row.get("summary") or "",
                path=_memory_path(row),
                category=row.get("category") or "experience",
                importance=float(row.get("importance") or 0.7),
                keywords=_parse_keywords(row.get("keywords")),
                metadata=metadata,
                project=str(row.get("project") or "hyperion"),
                domain=str(row.get("domain") or "equity_trading"),
                force=True,
            )
            if isinstance(decoded, dict) and decoded.get("error"):
                error_msg = str(decoded["error"])
                logger.warning("Tachi rejected queue id=%s: %s", queue_id, error_msg)
                _mark_failed(journal.db_path, queue_id, error_msg)
                failed += 1
                continue
            if decoded is None:
                error_msg = "client unavailable"
                logger.warning("Tachi push failed for queue id=%s: %s", queue_id, error_msg)
                _mark_failed(journal.db_path, queue_id, error_msg)
                failed += 1
                continue
            synced_ids.append(queue_id)
        except Exception as exc:
            logger.warning("Tachi push failed for queue id=%s: %s", queue_id, exc)
            _mark_failed(journal.db_path, queue_id, str(exc))
            failed += 1

    if synced_ids:
        journal.mark_memory_synced(synced_ids)
    return len(synced_ids), failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Drain hapi.db.memory_sync_queue into Tachi.")
    parser.add_argument("--watch", action="store_true", help="Loop forever instead of one-shot.")
    parser.add_argument("--interval", type=float, default=60.0, help="Poll interval in seconds (--watch only).")
    parser.add_argument("--limit", type=int, default=None, help="Max rows per pass (default: all pending).")
    parser.add_argument("--db", type=str, default=None, help="Override hapi.db path.")
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = str(resolve_hapi_db_path(args.db))
    if not Path(db_path).exists():
        logger.error("hapi.db not found at %s", db_path)
        return 2

    if not tachi_client.is_available():
        logger.error("Tachi provider not available (binary missing or env disabled).")
        return 1

    journal = Journal(db_path=db_path)

    try:
        if args.watch:
            logger.info("Watch mode: polling every %.1fs (Ctrl-C to stop).", args.interval)
            while True:
                synced, failed = _drain_once(journal, args.limit)
                if synced or failed:
                    logger.info("Drain pass: synced=%d failed=%d", synced, failed)
                time.sleep(args.interval)
        else:
            synced, failed = _drain_once(journal, args.limit)
            logger.info("One-shot drain: synced=%d failed=%d", synced, failed)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error during drain: %s", exc)
        return 2
    finally:
        tachi_client.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
