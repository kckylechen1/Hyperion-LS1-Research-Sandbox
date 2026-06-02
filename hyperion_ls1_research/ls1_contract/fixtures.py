"""Load synthetic redacted snapshot and chat fixtures."""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fixtures"


def fixture_root() -> Path:
    return _FIXTURE_ROOT


def load_snapshot(name: str) -> dict:
    path = _FIXTURE_ROOT / "snapshots" / f"{name}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_chat(name: str) -> list[dict]:
    path = _FIXTURE_ROOT / "chats" / f"{name}.jsonl"
    events: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events