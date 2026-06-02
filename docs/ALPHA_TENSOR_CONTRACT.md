# Alpha Tensor Contract (Sandbox)

`AlphaTensor` is the **Observer-facing** compression of an existing snapshot. The sandbox builder:

1. Reads the snapshot dict only.
2. Never calls Warpcore or recomputes LS1 physics.
3. Maps LS1/Warpcore/trap/compression paths into five domains:

| Domain | Source examples |
|--------|-----------------|
| `structure` | Chan BSP, `chan.zs_count`, compression/coiling phase |
| `ignition` | `spring.launch`, `launch_signal`, breakout flags |
| `volume` | `pump_dump_vol_ratio`, turnover, volume gap |
| `risk` | `trap_detection`, overheat, toxic breaker |
| `global_regime` | `macro_sentinel`, `iron_verdict`, panic reversal |

`v8_grade` is retained as a **reference aggregate only** — external reviewers must not treat it as ground-truth alpha.