# HyperTachi Runbook

> HyperTachi is the **finance-first memory provider** for Hyperion (`project=hyperion`, `domain=equity_trading`). It is **not** the engineering documentation organizer — that belongs to **Sigil (Tachi)**. See [TACHI_AND_SIGIL_PRODUCT_BOUNDARY.md](TACHI_AND_SIGIL_PRODUCT_BOUNDARY.md).

Do not use host-provided generic `tachi_*` or `mcp4_tachi_*` tools unless they are routed through hapi-edge or the Quant DB paths. Use the HAPI bridge, `HAPI_MEMORY_*` MCP settings, or `engine.v8.infra.tachi_client` so writes target `data/tachi/projects/hyperion/memory.db`.

## Product boundary (short)

| HyperTachi **does** | HyperTachi **does not** |
|---|---|
| Save/search/recall trading lessons, daily handoffs | Organize Quant `docs/Spec` / `InProgress` / git doc trees |
| Ingest/index broker research, intel summaries ([RESEARCH_REPORTS_MODULE.md](RESEARCH_REPORTS_MODULE.md)) | Replace MCP contracts or skill protocols |
| Paths under `/trading/equity/...` | Engineering `tachi_wiki_organize` on Hyperion agent profile |

Engineering doc lifecycle: [DOC_GOVERNANCE.md](../DOC_GOVERNANCE.md). Coding-project organize: Sigil repo (`tachi_wiki_organize`).

## Default Semantics

| Field | Default |
|---|---|
| project | `hyperion` |
| domain | `equity_trading` |
| scope | `project` |
| path prefix | `/trading/equity/...` |

Use finance paths for trading memories:

```text
/trading/equity/decisions/{symbol}/{date}
/trading/equity/experience/{topic}/{date}
/trading/equity/daily/{date}
/trading/equity/engineering/{topic}/{date}
/trading/equity/agent/hapi/{topic}
```

Old `/hapi/...` paths are historical. Prefer `/trading/equity/...` for new durable memory.

## Surfaces

| Surface | Files / tools | Notes |
|---|---|---|
| MCP bridge | `.mcp.json`, `internal/mcpserver/tools.go` | `hapi-edge` resolves product `bin/hyperion-tachi` / `bin/hypertachi` / `bin/tachi`, then Quant source build output (`hypertachi/target/release/hyperion-tachi`, `hypertachi`, `tachi`, or `memory-server`), then developer fallback `~/bin/tachi`; `HAPI_MEMORY_MCP_COMMAND` / `HAPI_MEMORY_MCP_URL` override this, and old `HAPI_TACHI_*` names are compatibility aliases |
| Python client | `engine/v8/infra/tachi_client.py` | Thin sync wrapper around productized Hermes memory provider |
| Compatibility provider | `memory/tachi_bridge.py` | Stable Quant import path for Hermes provider |
| Queue worker | `scripts/tachi_sync_worker.py` | Consumes queued memory events when used |
| Path helpers | `engine/v8/infra/tachi_paths.py` | Preferred path naming helpers |

## Tool Name Mapping

Different surfaces expose different names.

| Operation | MCP memory server | MCP bridge tool | Python wrapper |
|---|---|---|---|
| Save | `save_memory` | `hypertachi_save_memory` | `save_memory()` |
| Search | `search_memory` | `hypertachi_search_memory` | `search_memory()` |
| Recall | `recall_context` | `hypertachi_recall_context` | `recall_context()` |
| Graph | `memory_graph` | `hypertachi_memory_graph` | `memory_graph()` |
| Inbox | `check_inbox` | `hypertachi_check_inbox` | MCP only |
| Card | `post_card` | via `delegate_codex_task` | MCP only |
| Handoff | `handoff_leave`, `handoff_check` | `hypertachi_handoff_*` | MCP only |

## When To Save Memory

Save durable memory after **trading-relevant** outcomes:

1. Trading lessons that should affect future decisions (entries, exits, regime mistakes).
2. Daily close/open handoffs with durable tactical information.
3. Research report takeaways after ingest ([RESEARCH_REPORTS_MODULE.md](RESEARCH_REPORTS_MODULE.md)).
4. Promoted intel/news summaries worth recalling next week (`/trading/equity/intel/...`).
5. V8 / iron-rule semantics changes that affect **live agent judgment** (link to Spec path in text).

For **engineering-only** work (refactors, architecture, bug fixes without trading impact), prefer Sigil/Tachi on the coding profile or Quant `docs/Spec/` PRs — do not rely on HyperTachi organize.

Do not save noisy routine command output.

## Spec vs Memory

Memory is an **index**, not a second Spec store.

| Write in git | Write in memory |
|---|---|
| Full contract, gates, API shapes | One-line decision + **path to doc** |
| `docs/Spec/`, promoted skills | `keywords`, `entities`, verify command |

Do **not** paste entire spec files into `save_memory`. After changing a Spec, save an atom like:

```text
[decision] Gate 2 failed — Warpcore-only top-k below threshold
spec: docs/InProgress/PATTERN_MEMORY_FULL_SPEC.md (Phase 2 gate)
verify: uv run pytest autoresearch_lab/pattern_memory/ -q
keywords: [pattern-memory, gate-2, phase2]
```

Authority: [DOC_GOVERNANCE.md §4](../DOC_GOVERNANCE.md#4-spec-vs-memory-best-practice).

## Recommended Payload Shape

```json
{
  "path": "/trading/equity/engineering/docs/2026-04-29",
  "category": "decision",
  "importance": 0.8,
  "scope": "project",
  "project": "hyperion",
  "domain": "equity_trading",
  "force": true,
  "text": "[decision] Phase 2 gate failed; see docs/InProgress/PATTERN_MEMORY_FULL_SPEC.md §Gate 2. Root: … verify: uv run pytest …",
  "keywords": ["pattern-memory", "gate-2", "PATTERN_MEMORY_FULL_SPEC"],
}
```

### Save Contract (mandatory fields)

Every call to `save_memory` from Quant Python must explicitly pass the
following kwargs. Relying on `TachiMemoryProvider` defaults is fragile —
hypertachi's capture gate (`hypertachi/crates/memory-server/src/capture_gate.rs`)
rejects writes without a `domain`, and the absence of `project` breaks
search/recall filtering.

| Field | Value | Reason |
|---|---|---|
| `project` | `"hyperion"` | Routes to `data/tachi/projects/hyperion/memory.db`, not `.tachi/memory.db` |
| `domain` | `"equity_trading"` | Satisfies capture gate Rule 1; enables `domain` filter in recall |
| `force` | `True` | Bypasses capture gate violations in `Enforce` mode (text length, markdown heuristic) |

Call sites currently enforcing this contract (audited 2026-06-02):

| File | Line | Project | Domain | Force |
|---|---|---|---|---|
| `engine/research_kb.py` | 118 | `_PROJECT` | `_DOMAIN` | `True` |
| `engine/v8/infra/tachi_client.py` (default) | 170 | optional | optional | optional |
| `tools/import_legacy_trading_memory.py` | 303 | `"hyperion"` | `"equity_trading"` | `True` |
| `tools/import_trading_knowledge.py` | 179 | `"hyperion"` | `"equity_trading"` | `True` |
| `scripts/tachi_sync_worker.py` | 170 | `"hyperion"` | `"equity_trading"` | `True` |
| `autoresearch_lab/pattern_memory/phase6_tachi.py` | 228 | `"hyperion"` | `"equity_trading"` | `True` |

Test gate: `tests/test_tachi_write_contract.py` fails CI if any call site
drops `project` / `domain` / `force`.

## Python Usage

```python
from engine.v8.infra.tachi_client import save_memory, search_memory

save_memory(
    text="Trading lesson or engineering decision...",
    path="/trading/equity/experience/risk/2026-04-29",
    category="experience",
    importance=0.8,
)

hits = search_memory("688981 entry rationale", top_k=5, path_prefix="/trading/equity")
```

The Python client swallows errors by default to avoid blocking trading pipelines. Use `strict=True` only for diagnostics.

## Failure Modes

| Symptom | Likely cause | Action |
|---|---|---|
| Provider import fails | `hermes-agent` path missing or not synced | Check `pyproject.toml` workspace and `memory/tachi_bridge.py` |
| MCP connect fails | `HAPI_MEMORY_MCP_COMMAND` wrong or binary missing | Build source HyperTachi with `cd hypertachi && cargo build -p memory-server --release`, run `tools/build_release_products.py hyperion`, set `HAPI_MEMORY_MCP_COMMAND` to the built binary, or set `HAPI_MEMORY_MCP_URL` |
| Timeout | Memory server slow/down | Retry later; do not block trading action |
| Wrong domain/path | Old `/hapi` convention copied forward | Rewrite to `/trading/equity/...` |

## Separation From SQLite

| Store | Purpose |
|---|---|
| `data/hapi.db.daily_summaries` | Deterministic daily handoff and structured trading state |
| `data/hapi.db.journal` | Trade/decision log with snapshots |
| HyperTachi | Semantic recall, lessons, handoffs, diary, skill/eval context |

Do not replace operational database writes with vector memory. Use both when appropriate.
