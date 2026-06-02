"""LS1 output contract — structural facts only, not trading commands."""

from __future__ import annotations

from typing import Any

# Public contract: allowed LS1/Warpcore snapshot paths (values only, no algo).
LS1_REQUIRED_PATHS: tuple[str, ...] = (
    "ls1_supercharged.spring.coiling",
    "ls1_supercharged.spring.launch",
    "ls1_supercharged.spring.breakout_60d",
    "ls1_supercharged.three_push.pump_dump_vol_ratio",
    "compression_setup.is_range_compressed",
    "compression_setup.is_bb_squeeze",
    "compression_setup.is_ready",
    "trap_detection.pump_fake.is_trap",
    "trap_detection.pump_fake.trap_type",
    "trap_detection.pump_fake.volume_ratio",
    "trap_detection.volume_gap.is_gap",
    "intraday_volume_structure.launch_signal",
    "intraday_volume_structure.accel_ratio",
    "intraday_volume_structure.escape_signal",
    "crash_signals.panic_reversal.detected",
    "chan.bsp.latest",
    "chan.bsp.latest_confirmed",
    "chan.bsp.latest_candidate",
    "chan.stage_code",
    "chan.zs_count",
)

# Minimal snapshot envelope for sandbox fixtures.
SNAPSHOT_ENVELOPE_KEYS: tuple[str, ...] = (
    "symbol",
    "as_of_date",
    "scenario",
    "outcome_label",
)


def dig(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur