# Code Review Index (Full PR #37 / #39 mirror)

> **Warpcore / Rust LS1 core is intentionally excluded.** Everything below is Python/Go lab + gateway surface for external audit.

## Runnable sandbox

| Path | Role |
|------|------|
| [hyperion_ls1_research/](../hyperion_ls1_research/) | LS1 contract, synthetic fixtures, AlphaTensor, provenance demo |
| [data/fixtures/](../data/fixtures/) | Synthetic snapshots + chat |
| [examples/](../examples/) | Demos |
| [tests/](../tests/) | Sandbox + `tests/reference/` mirror tests |

## Full monorepo mirror (`reference/monorepo_snapshot/`)

### LS1 / Alpha / Beta

| File |
|------|
| `engine/v8/neuro/builder.py` |
| `engine/v8/neuro/schema.py` |
| `engine/v8/neuro/beta_schema.py` |
| `engine/v8/neuro/beta_builder.py` |
| `docs/Spec/LS1_DECISION_PROVENANCE_REPLAY.md` |

### Kronos

| File |
|------|
| `autoresearch_lab/kronos/extractor.py` |
| `autoresearch_lab/kronos/embedding_config.py` |
| `autoresearch_lab/kronos/pca_fusion.py` |
| `autoresearch_lab/kronos_probe/run_causality_probe.py` |
| `autoresearch_lab/kronos_probe/probe_model.py` |

### Pattern Memory

| File |
|------|
| `autoresearch_lab/pattern_memory/store.py` |
| `autoresearch_lab/pattern_memory/vectorize.py` |
| `autoresearch_lab/pattern_memory/fusion.py` |
| `autoresearch_lab/pattern_memory/kronos_backfill.py` |
| `autoresearch_lab/pattern_memory/leakage_guard.py` |
| `autoresearch_lab/pattern_memory/evidence.py` |
| `autoresearch_lab/pattern_memory/evidence_card.py` |
| `autoresearch_lab/pattern_memory/late_fusion.py` |
| `autoresearch_lab/pattern_memory/ablation.py` |
| `autoresearch_lab/pattern_memory/phase6_tachi.py` |

### Fund Manager

| File |
|------|
| `autoresearch_lab/fund_manager/episode_runner.py` |
| `autoresearch_lab/fund_manager/pattern_recall.py` |
| `autoresearch_lab/fund_manager/ledger.py` |
| `autoresearch_lab/fund_manager/journal_rag.py` |

### Decision Provenance + Semantic Memory

| File |
|------|
| `autoresearch_lab/decision_provenance/*` |
| `autoresearch_lab/semantic_memory/*` |

### Gateway / Lab CLI / Ops

| File |
|------|
| `internal/mcpserver/facades.go` |
| `internal/gateway/memory_ingest.go` |
| `engine/v8/autoresearch_lab/cli.py` |
| `docs/Spec/HYPERTACHI_RUNBOOK.md` |
| `scripts/tachi_sync_worker.py` |

### Results + tests

Canonical path: **[`data/results/`](../../data/results/)** (not duplicated under `reference/`).

| Artifact |
|----------|
| `phase4_ablation_20260601_084331.{json,md}` … `phase4_ablation_20260602_005541.{json,md}` |
| `kronos_causality_experiment_results_base.json` (redacted tickers) |

| Tests |
|-------|
| `tests/test_pattern_memory_leakage_guard.py` |
| `tests/test_kronos_probe_schema.py` |

## Review order

1. `LS1_DECISION_PROVENANCE_REPLAY.md` + `engine/v8/neuro/builder.py`
2. `pattern_memory/store.py` + `leakage_guard.py` + `evidence_card.py`
3. `fund_manager/pattern_recall.py` + `episode_runner.py` + `ledger.py`
4. `decision_provenance/replay.py` + `tachi_promote.py`
5. `kronos/extractor.py` + redacted causality JSON
6. `ablation.py` + [`data/results/phase4_ablation_*`](../../data/results/)

See [NOTICE.md](NOTICE.md) — mirror is read-only; not installable without private deps.