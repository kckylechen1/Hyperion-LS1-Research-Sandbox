#!/usr/bin/env python3
"""Load synthetic fixtures and print AlphaTensor projections."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperion_ls1_research.alpha_tensor import build_alpha_tensor
from hyperion_ls1_research.ls1_contract import load_snapshot, validate_snapshot

FIXTURES = (
    "dongshan_missed_entry",
    "xinyisheng_healthy_washout",
    "xinyuan_false_breakout",
)


def main() -> None:
    for name in FIXTURES:
        snap = load_snapshot(name)
        report = validate_snapshot(snap)
        alpha = build_alpha_tensor(snap)
        print(f"\n=== {name} ===")
        print("validate:", report)
        print(json.dumps(alpha.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()