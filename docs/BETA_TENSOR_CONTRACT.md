# Beta Tensor Contract (Reference)

Beta captures **human execution discipline** (sizing, panic exit, overrides). The full `BetaTensor` model lives in the private monorepo; this sandbox references it only through:

- `human_action` on chat atoms (`NO_BUY`, `BUY_NORMAL`, …)
- Diagnosis paths in `decision_provenance/validator.py`

## Sandbox diagnosis vectors

| Vector | Typical signal |
|--------|----------------|
| `alpha_error` | Trap / microstructure visible; outcome false breakout |
| `scoring_error` | LS1 ignition vs mediocre aggregate grade; lethal under-weighted |
| `beta_error` | Human bought against aggregate guidance |
| `no_error` | Healthy washout within structure |

Production BetaTensor fields (panic_exit, sizing_discipline_pct, etc.) should be wired before nightly replay.