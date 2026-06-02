# Nightly Replay Pipeline (Conceptual)

This sandbox does **not** run nightly replay. In the private Hyperion monorepo, the intended loop is:

```text
snapshot_factory (offline) → fixture-compatible snapshot dict
    → build_alpha_tensor (projection only)
    → fund_manager / ghost ledger (evidence-masked)
    → outcome_validator → causality_diagnoser
    → promote_lesson (distilled, no raw chat)
```

## Before connecting this contract

1. Versioned snapshot schema + LS1 path stability tests.
2. BetaTensor capture on every human decision.
3. Pattern Memory evidence cards (retrieval metrics, no trade commands).
4. Champion weights / Kronos remain **out of band** for public review.

This repo proves the **contracts and fixtures**; private CI proves **scale and parity**.