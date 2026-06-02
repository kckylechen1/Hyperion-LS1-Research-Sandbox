#!/usr/bin/env python3
"""Compare three synthetic LS1 scenarios side by side."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperion_ls1_research.alpha_tensor import build_alpha_tensor
from hyperion_ls1_research.ls1_contract import load_snapshot, project_ls1_facts

SCENARIOS = (
    ("missed_entry", "dongshan_missed_entry"),
    ("healthy_washout", "xinyisheng_healthy_washout"),
    ("false_breakout", "xinyuan_false_breakout"),
)


def main() -> None:
    for label, fixture in SCENARIOS:
        snap = load_snapshot(fixture)
        ls1 = project_ls1_facts(snap)
        alpha = build_alpha_tensor(snap)
        print(f"\n--- {label} ({fixture}) ---")
        print(f"  grade(ref): {alpha.v8_grade}  lethal: {alpha.is_lethal()}")
        print(f"  ignition_bar: {alpha.ignition.ignition_bar_present}  trap: {alpha.risk.is_trap}")
        print(f"  spring.coiling: {ls1.get('ls1_supercharged.spring.coiling')}")
        print(f"  launch: {ls1.get('ls1_supercharged.spring.launch')}")
        print(f"  pump_dump_ratio: {ls1.get('ls1_supercharged.three_push.pump_dump_vol_ratio')}")
        print(f"  outcome: {snap.get('outcome_label')}")


if __name__ == "__main__":
    main()