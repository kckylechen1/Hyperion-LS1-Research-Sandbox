# Pattern Memory — Hyperion Code Map

> Status: Active reference
> Last updated: 2026-06-01
> Purpose: 代码分区块地图，为 Pattern Memory / Kronos / 相似病例检索提供落地方向

---

## 0. 总架构 / 热路径边界

### 对照文件

```
README.md
docs/Spec/RUNTIME_MAP.md
AGENTS.md
internal/gateway/snapshot_core.go
internal/gateway/rpc.go
internal/mcpserver/facades.go
```

### 当前代码真相

Hyperion 现在已经明确拆成四层：Warpcore 是 Rust 计算核心，Hapi-Edge 是 Go 路由网关，AutoResearch Lab 是 Python 离线投研沙盘，HyperTachi 是记忆系统。

Runtime Map 明确：行情数据先进 `warpcore/radar + radar_daemon`，写入 `data/cache/rust_gateway.db`，由 `hapi-edge` 读缓存，对外提供 MCP/CLI。

AGENTS.md 写死：Go/Rust 拥有默认 runtime gateway、market-data refresh、cache reads、control plane 和 snapshot core；Python 只保留 LS1 oracle、lab/runtime compatibility surface 和测试目标。

### 对 Pattern Memory 的结论

Pattern Memory / Kronos 第一阶段不能碰 hot path。Kronos 只能进 AutoResearch 冷路径。Go 的 `snapshot_core` 最多以后读取预计算好的 `pattern_recall_cache`，不能在盘中跑 Python、torch、LLM 或 Kronos。

---

## 1. Snapshot Core / Go 热路径

### 对照文件

```
internal/gateway/snapshot_core.go
internal/gateway/rpc.go
internal/mcpserver/facades.go
```

### 核心代码位置

`snapshotCorePayloadWithOptions()` 是当前 Go/Rust snapshot 主入口。构建 evidence bundle，调用 Rust features，补充：

```
risk, indicators, compression_setup, chan, crash_signals,
trap_detection, intraday_volume_structure, ichimoku,
gann_support, ls1_supercharged, feature_errors
```

RPC 层注册了：`snapshot.core`, `snapshot.core_batch`, `snapshot.probe`, `snapshot.parity`, `analysis.full`, `analysis.triage`, `analysis.deep_dive`。

MCP facade `hapi_analyst` 封装了 `triage / snapshot / core / core_batch / batch / parity / analyze`。

### 对 Pattern Memory 的结论

以后新增 `pattern_recall` 时最合理路径：

```
离线 AutoResearch 生成 pattern_recall_cache
        ↓
Go RPC 新增 memory.pattern_recall
        ↓
MCP hapi_memory 或 hapi_analyst 暴露只读 action
        ↓
snapshot_core 可选 include_pattern_recall=true 时读取
```

不要默认注入。先做显式开关。

---

## 2. 缠论 / Chan 区块

### 对照文件

```
docs/Spec/RUNTIME_MAP.md
autoresearch_lab/snapshot_factory.py
internal/gateway/snapshot_core.go
engine/v8/core/v8_score.py
```

### 当前代码真相

离线 snapshot 工厂 import：

```python
from engine.v8.core.chan_analysis import analyze_chan
from engine.v8.core.chan_semantic import build_chan_semantic
```

同时 import `objective_tensions`, `check_entry_rules`, `check_exit_rules`, `classify_lifecycle`，说明缠论不只做指标，还进入语义、张力、铁律和生命周期判断。

V8 score 侧读取 `raw_chan = snap.get("chan", {})` 并通过 `feature_card["chan"]` 参与因子计算。

### 第一版 Pattern Snapshot 至少要抽

```
chan_bsp_side, chan_bsp_types, chan_trend_type,
chan_bi_count, chan_zs_count, chan_pivot_position,
chan_semantic_facts
```

---

## 3. 因子 / V8 Score 区块

### 对照文件

```
engine/v8/core/v8_score.py
engine/v8/core/factor_registry.py
autoresearch_lab/prepare.py
docs/InProgress/AUTORESEARCH_EVAL_AUDIT.md
```

### 当前代码真相

`v8_score.py` 已被重构成 facade：objective extraction 在 `feature_card.py`，`v8_score.py` 负责 raw features → deterministic 0–100 score。

因子注册结构：`id, default_weight, bucket, axis, fever_penalty, toxic_penalty, description`。

`calculate_v8_score()` 支持 `factor_weights / trace / horizon / prior_memory / weights_source / relief_policy / factor_trigger_policy`。

### 第一版 Warpcore-only / V8-only vectorizer 核心字段

```
v8_grade, v8_score, left_total, right_total,
interaction_score, setup_state, missing_confirmation,
toxic_breaker_factors, overheat_index, fresh_count,
factor_exposures / effective_contributions
```

---

## 4. AutoResearch / 离线投研区块

### 对照文件

```
engine/v8/autoresearch_lab/cli.py
autoresearch_lab/prepare.py
autoresearch_lab/labeler.py
autoresearch_lab/pattern_discriminator.py
autoresearch_lab/research_data_backend.py
internal/research/runner.go
```

### 当前代码真相

`cli.py` 已注册 action handler：`evaluate, evolve, fund_manager, forensics_tag, promote_lesson, pattern`。

Go 侧 `runner.go` 启动：`uv run python -m engine.v8.autoresearch_lab.cli <action> --run-id ... --params-json ...`。

### Pattern Memory 新增 action 建议

```
pattern_store_build
pattern_similarity_eval
kronos_probe
kronos_embed
pattern_ablation
```

---

## 5. Labeler / 防泄露 / 训练标签区块

### 对照文件

```
autoresearch_lab/labeler.py
autoresearch_lab/prepare.py
docs/InProgress/AUTORESEARCH_EVAL_AUDIT.md
```

### 当前代码真相

Triple-Horizon Labeler：T5/T10/T20 标签，使用 T+1 open 作为入场价，扣双边 friction，计算 forward return 和 MAE。

阈值：T5: true_S >= 3.0, stale_S <= -2.0; T10: true_S >= 5.0, stale_S <= -3.0; T20: true_S >= 8.0, stale_S <= -5.0。

`prepare.py` 已实现 temporal walk-forward split + purge gap。

### Pattern Memory 额外防泄露

```python
candidate_trade_idx <= query_trade_idx - max_label_horizon_bars - purge_bars
# 默认: max_label_horizon_bars=20, purge_bars=1
```

---

## 6. Pattern Discriminator / 当前"类 Pattern Memory"区块

### 对照文件

```
autoresearch_lab/pattern_discriminator.py
tests/test_pattern_discriminator.py
engine/v8/autoresearch_lab/cli.py
```

### 当前代码真相

当前是 LLM 规则归纳器。抽 price/indicators/chan/volume/momentum/compression/v8_score/iron_rules，让 LLM 总结 bull_flags/bear_flags/discriminators。

### 缺少

```
embedding, z-score normalization, top-k historical retrieval,
pattern_snapshot 表, pattern_embedding 表, pattern_recall_cache,
Warpcore-only / Kronos-only / Fused ablation
```

建议新建 `autoresearch_lab/pattern_memory/` 和 `autoresearch_lab/kronos_adapter/`。

---

## 7. Memory / HyperTachi 区块

### 对照文件

```
internal/gateway/memory_ingest.go
internal/gateway/memory_lessons.go
internal/gateway/rpc.go
internal/mcpserver/facades.go
```

### 当前代码真相

实盘交易/同步/盘后总结写入 HyperTachi，domain=`equity_trading`, scope=`project`, retention=`durable`。

MCP `hapi_memory` 暴露 `search / recall / save`。

### 分工

- DuckDB: 数值特征、embedding、similarity、top-k case
- HyperTachi: LLM Historian 病例叙事、失败教训、交易复盘

---

## 8. DuckDB / 数据仓库区块

### 对照文件

```
autoresearch_lab/research_data_backend.py
autoresearch_lab/store/duckdb_lab.py
README.md
AGENTS.md
```

### 当前代码真相

数据库分工：`hapi.db`(交易核心), `rust_gateway.db`(热缓存), `intel.db`(战情中枢), `lab.duckdb`(离线分析), Tachi Server(记忆)。

`DuckDBLab` 是 in-memory DuckDB + Parquet warehouse + attach hot SQLite cache。

### Pattern Memory 新增表

```
pattern_snapshot
pattern_feature_stats
pattern_embedding
pattern_recall_cache
```

---

## 9. Fund Manager / 交易实验区块

### 对照文件

```
autoresearch_lab/fund_manager/episode_runner.py
autoresearch_lab/fund_manager/journal_rag.py
```

### 接入方式

```
Pattern Memory 先在 AutoResearch 独立跑 ablation
        ↓
证明 Fused > Warpcore-only
        ↓
Fund Manager prompt 里增加 pattern_recall 摘要
        ↓
PositionPolicy 把 pattern_recall 当额外 risk/confirmation evidence
```

---

## 10. 推荐代码落点

```
autoresearch_lab/pattern_memory/
    __init__.py
    schema.py
    store.py
    vectorize.py
    normalize.py
    leakage_guard.py
    similarity.py
    build_snapshots.py
    evaluate_similarity.py

autoresearch_lab/kronos_probe/
    probe_model.py
    README.md

autoresearch_lab/kronos_adapter/
    __init__.py
    extractor.py
    dataset.py
    cache.py

tests/
    test_pattern_memory_store.py
    test_pattern_memory_normalize.py
    test_pattern_memory_leakage_guard.py
    test_pattern_memory_similarity.py
    test_kronos_adapter_contract.py

docs/InProgress/
    PATTERN_MEMORY_IMPLEMENTATION.md
    KRONOS_PROBE_REPORT.md
```

Go 侧等 Phase 1–4 跑完再动：

```
internal/gateway/pattern_recall.go
internal/gateway/rpc.go          (新增 pattern_recall action)
internal/mcpserver/facades.go    (暴露 hapi_memory.recall)
internal/mcpserver/tools.go
```

---

## 落地优先级

1. `lab.duckdb + pattern_snapshot + z-score stats + leakage guard`
2. Warpcore-only similarity baseline
3. Kronos probe
4. Warpcore-only / Kronos-only / Fused ablation
5. Pattern Recall 只读接入 Go
6. LLM Historian / HyperTachi 病例叙事

核心原则：**先把 Pattern Memory 变成可审计的数据层，而不是再加一个黑箱。**
