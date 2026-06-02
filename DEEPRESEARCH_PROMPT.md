# DeepResearch Evaluation Prompt

You are reviewing **Hyperion-LS1-Research-Sandbox**. Read [reference/CODE_REVIEW_INDEX.md](reference/CODE_REVIEW_INDEX.md) first.

## Questions

1. **LS1 contract** (`docs/LS1_CONTRACT.md`) — sufficient for external audit without algorithm internals?

2. **AlphaTensor** (`hyperion_ls1_research/alpha_tensor/builder.py` + fixtures) — correct orthogonal split? Missing fields for nightly replay?

3. **Decision Provenance** — can fixtures separate alpha vs scoring vs beta? See `examples/run_decision_provenance_demo.py`.

4. **Pattern Memory data layer** — review mirrored `store.py`, `vectorize.py`, `fusion.py`, `leakage_guard.py`:
   - Is `query_top_k` leakage-safe by construction?
   - Is evidence (`return_evidence_card`) fund-manager-safe (no trade commands)?
   - Does `PATTERN_MEMORY_CODE_MAP.md` hot/cold path split make sense?

5. **Kronos causality probe** — read redacted `data/results/kronos_causality_experiment_results_base.json` and `KRONOS_800K_POSTMORTEM_PROBE.md`:
   - Does 15m micro similarity contradict daily macro similarity (trap vs accumulation)?
   - Is `extractor.py` clearly **representation / retrieval**, not proven alpha?
   - What calibration is missing before `insufficient_calibration` → production?

6. **Runtime / memory boundary** — `facades.go`, `memory_ingest.go`, `HYPERTACHI_RUNBOOK.md`:
   - Correct split between DuckDB pattern store vs HyperTachi lessons?
   - Risk of promoting raw chat vs distilled lessons?

7. **Test gaps** — compare `tests/` sandbox tests vs `tests/reference/` mirror tests. What contract tests should block nightly replay promotion?

## Constraints

- Mirrored code under `reference/monorepo_snapshot/` is **not runnable** here without the private monorepo.
- Tickers in JSON/postmortem are **synthetic/redacted**.
- LS1 fields are structural facts, not buy/sell commands.
- `v8_score.grade` is aggregate reference only.