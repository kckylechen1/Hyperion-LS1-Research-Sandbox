# Reference Mirror Notice

Files under `reference/monorepo_snapshot/` are **read-only mirrors** copied from the private
Hyperion-Quant-SRC monorepo for **external code review**. They are **not** runnable in isolation:

- Imports assume `engine.*`, `autoresearch_lab.*`, `warpcore`, DuckDB paths, and Go modules.
- No Rust Warpcore / LS1 core sources are included.
- No databases, API keys, or model weight files are included.

## Purpose

Let DeepResearch / reviewers audit **interfaces and data-layer design** (Pattern Memory store,
Kronos extractor contract, MCP facades, memory ingest) without publishing the full production tree.

## Runnable surface in this repo

| Path | Runs in sandbox CI? |
|------|-------------------|
| `hyperion_ls1_research/` | Yes — `pytest -q` |
| `reference/monorepo_snapshot/` | No — review-only |
| `tests/reference/` | Optional — leakage guard tests only |

Do not treat mirrored Python as an installable package unless you vendor the full private monorepo.