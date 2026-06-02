#!/usr/bin/env python3
"""Bind dongshan chat -> fixture -> AlphaTensor -> diagnosis."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperion_ls1_research.decision_provenance import bind_chat_to_snapshot
from hyperion_ls1_research.decision_provenance.validator import lesson_from_diagnosis
from hyperion_ls1_research.ls1_contract import load_chat, load_snapshot


def main() -> None:
    chat = load_chat("dongshan_chat")[0]
    snap = load_snapshot("dongshan_missed_entry")
    bundle, alpha, diagnosis = bind_chat_to_snapshot(chat, snap)

    print("=== Original idea (redacted) ===")
    print(bundle.watch_idea.user_intent_summary)
    print("\n=== Agent decision (redacted) ===")
    print(bundle.decision_rationale.agent_summary)
    print("\n=== Alpha Tensor at time ===")
    print(json.dumps(alpha.model_dump(), ensure_ascii=False, indent=2))
    print("\n=== Later outcome ===")
    print(bundle.outcome_validation.model_dump())
    print("\n=== Diagnosis ===")
    print(diagnosis["question"])
    print(diagnosis["answer"])
    print(f"vector: {diagnosis['diagnosis']}")

    lesson = lesson_from_diagnosis(diagnosis, bundle.watch_idea.symbol)
    print("\n=== Lesson candidate (no raw chat) ===")
    print(lesson or "(none — no promotion)")


if __name__ == "__main__":
    main()