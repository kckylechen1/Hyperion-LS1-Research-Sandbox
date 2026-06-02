"""
Mock LS1 facade for sandbox demos only.

Does NOT implement Warpcore/LS1 physics. Returns pre-shaped contract fields
for tests that need a stand-in producer name.
"""

from __future__ import annotations

from typing import Any


def mock_ls1_snapshot_fields() -> dict[str, Any]:
    """Minimal LS1-shaped block — values are synthetic constants."""
    return {
        "ls1_supercharged": {
            "spring": {"coiling": True, "launch": False, "breakout_60d": False},
            "three_push": {"pump_dump_vol_ratio": 0.85},
        },
        "compression_setup": {
            "is_range_compressed": True,
            "is_bb_squeeze": True,
            "is_ready": False,
        },
        "trap_detection": {
            "pump_fake": {
                "is_trap": False,
                "trap_type": "none",
                "volume_ratio": 1.0,
            },
            "volume_gap": {"is_gap": False},
        },
        "intraday_volume_structure": {
            "launch_signal": False,
            "accel_ratio": 1.0,
            "escape_signal": False,
        },
        "crash_signals": {"panic_reversal": {"detected": False}},
        "chan": {
            "bsp": {
                "latest": {"side": "买", "types": ["T2"]},
                "latest_confirmed": None,
                "latest_candidate": None,
            },
            "stage_code": "developing",
            "zs_count": 2,
        },
    }