"""Ingest static chat transcripts into semantic decision atoms (no raw storage in Tachi)."""
from __future__ import annotations

import re
from typing import Any


def ingest_transcript(text: str, *, source: str = "chat") -> list[dict[str, Any]]:
    """Parse a plain transcript into raw semantic events."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        role = "unknown"
        body = line
        m = re.match(r"^(user|assistant|human|agent|system)\s*:\s*(.+)$", line, re.I)
        if m:
            role = m.group(1).lower()
            body = m.group(2).strip()
        events.append({"source": source, "role": role, "text": body})
    return events


def extract_decision_atoms(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lift watch ideas and decision rationale from ingested events."""
    atoms: list[dict[str, Any]] = []
    watch_re = re.compile(
        r"(watch|观察|关注|跟踪|monitor)\s*[:：]?\s*(\d{6}\.(?:SH|SZ))",
        re.I,
    )
    rationale_re = re.compile(
        r"(because|原因|理由|rationale|decided|决定)\s*[:：]?\s*(.+)",
        re.I,
    )
    for ev in events:
        text = ev.get("text") or ""
        for match in watch_re.finditer(text):
            atoms.append(
                {
                    "atom_type": "watch_idea",
                    "symbol": match.group(2).upper(),
                    "text": text[:500],
                    "role": ev.get("role"),
                }
            )
        rm = rationale_re.search(text)
        if rm:
            atoms.append(
                {
                    "atom_type": "decision_rationale",
                    "text": rm.group(2).strip()[:800],
                    "role": ev.get("role"),
                }
            )
    return atoms


def bind_atoms_to_pattern(
    atoms: list[dict[str, Any]],
    *,
    pattern_id: str,
    symbol: str,
    as_of_date: str,
) -> list[dict[str, Any]]:
    """Attach pattern_snapshot binding metadata (DuckDB numeric evidence stays separate)."""
    bound = []
    for atom in atoms:
        bound.append(
            {
                **atom,
                "pattern_id": pattern_id,
                "symbol": symbol,
                "as_of_date": str(as_of_date)[:10],
            }
        )
    return bound