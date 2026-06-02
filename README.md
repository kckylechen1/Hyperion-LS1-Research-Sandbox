# Hyperion-LS1-Research-Sandbox

A **public-safe, LS1-centered research sandbox** for external reviewers (e.g. DeepResearch). It is **not** Hyperion-Quant-SRC and does **not** ship proprietary Warpcore/LS1 calculation code.

## Two layers

| Layer | Path | Purpose |
|-------|------|---------|
| **Runnable sandbox** | `hyperion_ls1_research/`, `data/fixtures/` | LS1 contract, synthetic fixtures, AlphaTensor projection, provenance demos |
| **Code review mirror** | `reference/monorepo_snapshot/`, `docs/InProgress/` | Read-only copies of Pattern Memory / Kronos / MCP files for audit |

Start with [reference/CODE_REVIEW_INDEX.md](reference/CODE_REVIEW_INDEX.md) for the **full PR #37/#39 mirror** (fund_manager, decision_provenance, evidence_card, ablation, neuro builders — **no Warpcore**).

## What this repo exposes

| Layer | Purpose |
|-------|---------|
| **LS1 output contract** | Documented snapshot field paths (structural facts only) |
| **Synthetic fixtures** | Three redacted scenarios: missed entry, healthy washout, false breakout |
| **Alpha Tensor projection** | Read-only mapping from fixture snapshot → `AlphaTensor` |
| **Decision Provenance** | Chat atom → snapshot bind → diagnosis (alpha / scoring / beta) |
| **Pattern Memory evidence** | Minimal case aggregation demo |
| **Review mirrors** | `store.py`, `vectorize.py`, `fusion.py`, `kronos_backfill.py`, `extractor.py`, Go facades, redacted Kronos JSON |

## What this repo does **not** expose

- Private databases, API keys, model weights, broker APIs
- Real trade records, real chat transcripts, or live market history
- Full production engine, V8 weight tuning, Agent RAG, or LS1 / Warpcore Rust internals
- Runnable `kronos_probe` pipeline (test skipped unless private deps present)

## Quick start

```bash
cd Hyperion-LS1-Research-Sandbox
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                    # sandbox tests (10+)
pytest -q tests/reference  # + leakage guard mirror tests
python examples/run_alpha_tensor_demo.py
python examples/run_decision_provenance_demo.py
python examples/run_ls1_replay_demo.py
```

## Layout

| Doc | Content |
|-----|---------|
| [REVIEW_SCOPE.md](REVIEW_SCOPE.md) | Scope + security checklist |
| [DEEPRESEARCH_PROMPT.md](DEEPRESEARCH_PROMPT.md) | External reviewer questions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Sandbox architecture |
| [docs/InProgress/PATTERN_MEMORY_CODE_MAP.md](docs/InProgress/PATTERN_MEMORY_CODE_MAP.md) | Pattern Memory code map |
| [docs/InProgress/KRONOS_800K_POSTMORTEM_PROBE.md](docs/InProgress/KRONOS_800K_POSTMORTEM_PROBE.md) | Redacted causality postmortem |
| [reference/NOTICE.md](reference/NOTICE.md) | Mirror usage rules |

## Security

All data under `data/fixtures/` is **synthetic**. `data/results/` includes **redacted** `kronos_causality_experiment_results_base.json` and the full **`phase4_ablation_*`** run series (5 JSON + 5 MD). Run the checklist in `REVIEW_SCOPE.md` before any public push.