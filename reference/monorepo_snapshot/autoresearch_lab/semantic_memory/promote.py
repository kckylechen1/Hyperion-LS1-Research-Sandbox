"""Promote distilled lessons to HyperTachi (never raw transcript or vectors)."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH_PREFIX = "/trading/equity/decisions/provenance"


def distill_lesson(
    atom: dict[str, Any],
    *,
    outcome: dict[str, Any] | None = None,
) -> str:
    """Build a short lesson string from a bound atom + optional T5/T10 outcome."""
    symbol = atom.get("symbol", "?")
    as_of = atom.get("as_of_date", "?")
    atom_type = atom.get("atom_type", "note")
    base = f"[{atom_type}] {symbol} @ {as_of}: {atom.get('text', '')[:400]}"
    if outcome:
        parts = []
        for h in ("T5", "T10", "T20"):
            if h in outcome and outcome[h].get("label"):
                parts.append(f"{h}={outcome[h]['label']}")
        if parts:
            base += " | validated: " + ", ".join(parts)
    return base


def promote_validated_lesson(
    lesson_text: str,
    *,
    symbol: str,
    as_of_date: str,
    dry_run: bool = True,
    importance: float = 0.7,
) -> dict[str, Any]:
    """Write distilled lesson via engine Tachi client (sidecar; no runtime fork)."""
    path = f"{_DEFAULT_PATH_PREFIX}/{symbol}/{str(as_of_date)[:10]}"
    payload = {
        "path": path,
        "text": lesson_text,
        "category": "lesson",
        "importance": importance,
        "dry_run": dry_run,
    }
    if dry_run:
        return {"status": "dry_run", **payload}

    try:
        from engine.v8.infra.tachi_client import save_memory

        ok = save_memory(
            text=lesson_text,
            path=path,
            category="lesson",
            importance=importance,
            strict=False,
        )
        return {"status": "ok" if ok else "failed", **payload}
    except Exception as exc:
        logger.warning("promote_validated_lesson failed: %s", exc)
        return {"status": "error", "error": str(exc), **payload}


def validate_outcome_from_labels(labels: dict[str, Any]) -> dict[str, Any]:
    """Normalize labeler output for promotion gate."""
    out: dict[str, Any] = {}
    for horizon in ("T5", "T10", "T20"):
        block = labels.get(horizon) or {}
        if block.get("label"):
            out[horizon] = {
                "label": block.get("label"),
                "fwd_return": block.get("fwd_return"),
                "mae": block.get("mae"),
            }
    return out