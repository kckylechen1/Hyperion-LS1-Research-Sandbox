# LS1 Output Contract

LS1 (with Warpcore) is a **structural fact source** in Hyperion. It describes market microstructure and Chan context already computed upstream. It is **not** a trading command layer.

This document lists **output fields only**. It does not describe proprietary calculation internals.

## Contract paths

| Path | Meaning (public) |
|------|------------------|
| `ls1_supercharged.spring.coiling` | Spring coil / compression energy present |
| `ls1_supercharged.spring.launch` | Intraday launch / ignition bar signal |
| `ls1_supercharged.spring.breakout_60d` | 60-day breakout context flag |
| `ls1_supercharged.three_push.pump_dump_vol_ratio` | Push/dump volume structure ratio |
| `compression_setup.is_range_compressed` | Range compression active |
| `compression_setup.is_bb_squeeze` | Bollinger squeeze active |
| `compression_setup.is_ready` | Compression setup ready |
| `trap_detection.pump_fake.is_trap` | Pump-fake trap flagged |
| `trap_detection.pump_fake.trap_type` | Trap classifier label |
| `trap_detection.pump_fake.volume_ratio` | Trap volume ratio |
| `trap_detection.volume_gap.is_gap` | Volume gap anomaly |
| `intraday_volume_structure.launch_signal` | Intraday launch signal |
| `intraday_volume_structure.accel_ratio` | Volume acceleration ratio |
| `intraday_volume_structure.escape_signal` | Escape / distribution signal |
| `crash_signals.panic_reversal.detected` | Panic reversal detected |
| `chan.bsp.latest` | Latest Chan BSP node |
| `chan.bsp.latest_confirmed` | Confirmed BSP node |
| `chan.bsp.latest_candidate` | Candidate BSP node |
| `chan.stage_code` | Chan stage code |
| `chan.zs_count` | Consolidation (中枢) count |

## Non-goals

- No formulas, weights, or Rust/Python LS1 implementation here.
- No automatic BUY/SELL mapping from LS1 booleans alone.

## Fixture scenarios

| Fixture | Teaching intent |
|---------|-----------------|
| `dongshan_missed_entry` | LS1 ignition early; aggregate grade mediocre → missed opportunity |
| `xinyisheng_healthy_washout` | Long-cycle structure holds through intraday chop |
| `xinyuan_false_breakout` | Day breakout looks good; trap + volume deteriorate |