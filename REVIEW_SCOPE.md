# Review Scope

## In scope for external researchers

1. Whether the **LS1 output contract** is sufficient for structural audit (`docs/LS1_CONTRACT.md`).
2. Whether **AlphaTensor projection** preserves the right information without recomputing physics.
3. Whether **Decision Provenance** can separate alpha / scoring / beta errors on fixtures.
4. **Pattern Memory** data layer: `reference/monorepo_snapshot/autoresearch_lab/pattern_memory/{store,vectorize,fusion,leakage_guard}.py`.
5. **Kronos offline probe**: `extractor.py`, redacted `data/results/kronos_causality_experiment_results_base.json`, `docs/InProgress/KRONOS_800K_POSTMORTEM_PROBE.md`.
6. **Runtime boundaries**: `internal/mcpserver/facades.go`, `internal/gateway/memory_ingest.go`, `docs/Spec/HYPERTACHI_RUNBOOK.md` (mirrored).
7. Code map: `docs/InProgress/PATTERN_MEMORY_CODE_MAP.md`.

## Out of scope

- LS1 / Warpcore Rust algorithm internals
- Live `hapi-edge` deployment, real symbols in production DBs
- Champion weights, full fund_manager episode runner, Agent RAG prompts

## Code review bundle (file index)

See [reference/CODE_REVIEW_INDEX.md](reference/CODE_REVIEW_INDEX.md).

| Category | Key paths |
|----------|-----------|
| Runnable sandbox | `hyperion_ls1_research/`, `data/fixtures/`, `examples/`, `tests/test_*.py` |
| Pattern Memory (mirror) | `reference/monorepo_snapshot/autoresearch_lab/pattern_memory/` |
| Kronos (mirror) | `reference/monorepo_snapshot/autoresearch_lab/kronos/extractor.py` |
| Lab CLI (mirror) | `reference/monorepo_snapshot/engine/v8/autoresearch_lab/cli.py` |
| Go gateway (mirror) | `reference/monorepo_snapshot/internal/{mcpserver,gateway}/` |
| Causality narrative | `docs/InProgress/KRONOS_800K_POSTMORTEM_PROBE.md` (redacted) |
| Probe metrics | `data/results/kronos_causality_experiment_results_base.json` (redacted tickers) |
| Mirror tests | `tests/reference/test_pattern_memory_leakage_guard.py` |

## Pre-push security checklist

```bash
grep -RInE 'api_key|apikey|secret|token|password|TUSHARE|LONGBRIDGE|OPENAI|HF_TOKEN|github_pat|ghp_|sk-' . \
  --exclude-dir=.venv --exclude-dir=.git
find . -type f \( -name '*.db' -o -name '*.duckdb' -o -name '*.sqlite' -o -name '*.parquet' \
  -o -name '*.pt' -o -name '*.pth' -o -name '*.safetensors' -o -name '*.bin' -o -name '.env' \) \
  ! -path './.venv/*'
```

Anything sensitive → `QUARANTINE_NOT_FOR_UPLOAD/` and remove from tree before publish.