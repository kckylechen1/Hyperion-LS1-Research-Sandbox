> **PUBLIC REDACTED COPY** for Hyperion-LS1-Research-Sandbox.
> Synthetic tickers; no live positions or raw chats. Full private doc in Hyperion-Quant-SRC.

# Causality Post-Mortem: The ~~800k RMB (redacted) (redacted magnitude) Lesson

> **Date of Incident**: 2026-05-28 to 2026-06-02
> **Total Cost**: ~~~800k RMB (redacted) (redacted magnitude) (Unnecessary realized losses + Missed upside gains)
> **Core Dilemma**: The complete fracture between Alpha (Quantitative Signals) and Beta (Semantic Discipline), leading to a cascading psychological collapse (Causality Chain).
> **Purpose**: This document serves as the absolute baseline specification for the Hyperion system's automated post-mortem workflow. It is the blood-stained blueprint of how a minor entry mistake cascades into total operational deformation.

---

## 1. The "Causality" Overview (因果链全貌)

This 800k lesson was not caused by a single wrong trade, but by a **chain reaction of uncorrected errors**. The core insight is: **Short-term risks must be resolved by T+0 (tactical agility), while long-term risks must be resolved by position sizing at entry (strategic defense).** Mixing these two up guarantees destruction.

### The Macro Context
*   The semiconductor/chip sector (合成芯片股B, 合成芯片股A) was already heavily overextended (涨飞了).
*   The user's vision for Hyperion: "To build an AI system that helps humans trade better." Yet, both the human (fear/greed) and the AI (giving weak long-term excuses for short-term breakdowns) failed entirely.

---

## 2. Step-by-Step Anatomy of the 800k Lesson

### Step 1: The Entry Mistake (Thursday, May 28) - "The Original Sin"
*   **The Action**: Short-term FOMO entries at the morning peak.
*   **The Targets & Alpha (Quant) Features**:
    *   **合成芯片股A (SYNTH_CHIP_A.SH)**:
        *   *Price/Vol*: Opened ~250, surged to 269.88. The first 15m (09:30-09:45) saw an extreme **10.39亿 turnover**, bleeding to 5.09亿 by 10:15.
        *   *V8 Features*: `overheat_index` spiked to **>= 6 (Overheated)**. `trend_mode` shifted to extreme acceleration but `left_pct` (left-side energy) was rapidly exhausted.
    *   **合成芯片股B (SYNTH_CHIP_B.SH)**:
        *   *Price/Vol*: Opened ~1361, surged to 1398. The first 15m saw a staggering **42.63亿 turnover**, which sharply dropped to 14.78亿 and 10.64亿 in the next two 15m bars.
        *   *V8 Features*: Structural `iron_verdict` triggered **WARNING**. Left-side `chan.bsp.latest` (Chan theory) showed a top divergence forming.
    *   **合成光模块股 (SYNTH_OPTICAL_A.SZ)**:
        *   *Price/Vol*: 695 -> 676 -> 688. 15m turnover was **36.33亿**, then halved to 19.52亿.
        *   *V8 Features*: High `right_pct` (ignition) but mixed `left_pct`, creating a classic Wyckoff Spring trap setup.
    *   **合成制造龙头 (SYNTH_SynthFII_A.SH)**:
        *   *Price/Vol*: 70 -> 73. Consistent massive volume (**34.82亿 -> 36.88亿** in first 30m).
*   **The Error**: Buying heavy positions in SynthChipB and SynthChipA despite knowing the chip sector was structurally overextended.
*   **The Correct Operation**: **Strict Position Sizing (仓位控制)**. If entering an overextended sector on an impulse, it must be sized as a small speculative bet, not a core position.

### Step 2: The Reaction Failure (Friday, May 29) - "Denial & Inaction"
*   **The Action**: Held everything. No T+0, no stop-losses.
*   **The Breakdown & Alpha (Quant) Features**:
    *   **合成制造龙头**:
        *   *Price/Vol*: Touched 79.18 on a massive **80.5亿 15m turnover** at open. Then it bled all day to 73.40 while volume dried up to 11.68亿.
        *   *V8 Features*: `crash_signals.rebound_exhaustion` likely triggered due to the massive volume without price continuation.
    *   **合成光模块股**:
        *   *Price/Vol*: Chopped violently (718 -> 701 -> 730 -> 706). Open volume was **49.87亿**, dropping to 23.03亿.
        *   *V8 Features*: `momentum.trend_mode` showed erratic range-bound chop.
    *   **合成芯片股A**:
        *   *Price/Vol*: Shrank dramatically in volume (**from 10.39亿 on Thursday to just 1.5亿-3.28亿 on Friday**). Price bled linearly to 246.
        *   *V8 Features*: `v8_score.grade` downgraded to **D (剧毒)**. Left-side energy (`left_pct`) completely shattered.
    *   **合成芯片股B**:
        *   *Price/Vol*: Bled from 1400 to 1310. Open volume was **26.99亿**, steadily declining.
        *   *V8 Features*: Long-term trend was technically intact, but short-term structure was breaking.
*   **The Error**:
    *   *Human*: Refused to execute T+0 on the massive intraday volatility of SynthFII and SynthOptical. Refused to clear SynthChipA despite the obvious V8 Grade D breakdown and volume collapse.
    *   *AI System*: The AI told the Captain that SynthChipB "还可以拿拿" (can still be held). **Fatal Mistake**: Using a long-term structural excuse to justify holding a short-term deteriorating position.
*   **The Correct Operation**:
    *   For volatile strong stocks (SynthFII, SynthOptical): **Execute T+0 aggressively** using the 15m volume climax (e.g., selling SynthFII into the 80.5亿 open pump) to lower cost basis.
    *   For broken weak stocks (SynthChipA): **Clear the position (清仓)** immediately when 15m volume shrinks below historical thresholds and the V8 Grade downgrades to D.

### Step 3: The Operational Collapse (Monday, June 1) - "Action Deformation"
*   **The Action**: The psychological pressure from Friday's inaction boiled over on Monday's morning dip.
*   **The Breakdown & Alpha (Quant) Features**:
    *   **合成制造龙头**:
        *   *Price/Vol*: Dipped to 72.3, then showed extreme relative strength, rallying to 76.3. Open volume was solid at **46.59亿**, showing strong buying support during the market dip.
        *   *V8 Features*: `momentum.trend_mode` showed strong resilience (diverging positively from the broader market index). *The user sold it.*
    *   **合成光模块股**:
        *   *Price/Vol*: Panic dropped to 673.2. The opening 15m saw a capitulation volume of **53.87亿** (massive washout).
        *   *V8 Features*: A classic Wyckoff Spring setup. The extreme volume spike on a breakdown indicated panic selling absorbed by institutions, creating a fake breakdown. *The AI advised reducing, the user cut the position at the exact bottom.*
    *   **合成芯片股A & 合成芯片股B**:
        *   *Price/Vol*: Plunged to 227 and 1238 respectively. SynthChipA's volume remained anemic (**9.86亿 -> 2.9亿**), showing zero institutional buying interest. SynthChipB bled steadily with 36亿 -> 14亿 volume.
        *   *V8 Features*: Left-side energy effectively dead for SynthChipA. SynthChipB entered a confirmed short-term downtrend. *The user held them both (gave up).*
*   **The Error**: **Capitulation (卖强留弱).**
    1.  Sold SynthFII (the ONLY rising stock) to lock in psychological relief, ignoring the strong 46亿 support volume.
    2.  Cut SynthOptical at the absolute panic bottom, misinterpreting the 53.87亿 washout volume as a real breakdown.
    3.  Held the worst losers (SynthChipA, SynthChipB) because the loss was too painful to realize, despite their dead volume profiles.
*   **The Correct Operation**:
    *   If Friday's T+0 and cuts were executed properly, the user would have cash and emotional stability on Monday.
    *   Monday's dip should have been the moment to **Buy/Add** (买入/加仓) the strong stocks (SynthFII, SynthOptical) at the washout volume climax, while strictly avoiding/cutting the weak ones.

### Step 4: The Face-Rip (Tuesday, June 2) - "The Price of Causality"
*   **The Result**:
    *   合成制造龙头: Rocketed to **80.00**. (Missed upside).
    *   合成光模块股: Skyrocketed to **750.16**. (Missed upside + realized floor loss).
    *   合成芯片股B: Bounced weakly to 1300. (Trapped).
    *   合成芯片股A: Bounced weakly to 240. (Trapped).

---

## 3. The "Alpha-Beta Tensor" Paradigm (终极教训)

This 800k loss defines the strict boundary between Alpha and Beta Tensors in the Hyperion architecture:

*   **Alpha Tensor (Quantitative/Warpcore)**: Gives us the 15m volume shrinkage, the V8 overheat score, the geometric breakdown.
*   **Beta Tensor (Semantic/Discipline)**: Dictates the operational logic.

**The Golden Rules (To be automated by the system):**
1.  **Mismatch Prevention**: Short-term risk MUST be managed via T+0. Long-term risk MUST be managed via initial position sizing. Never use a long-term outlook to excuse a short-term failure.
2.  **Anti-Capitulation Protocol (绝不卖强留弱)**: The system must hard-block any manual command to sell a stock with rising relative strength (e.g., SynthFII) while holding a stock with crashing left-side energy (e.g., SynthChipA).
3.  **The "Denial" Circuit Breaker**: If a stock drops > 5% intraday from its high on shrinking volume (like SynthFII on Friday) and no T+0 is executed, the AI must escalate an alert, forcing the user to acknowledge the passivity.

## 4. Automation Specification (自动化执行要求)

Going forward, a script or an AI Agent workflow must simulate this exact post-mortem behavior via a **Neuro-Symbolic Pipeline**:

1.  **Scan (Alpha Tensor)**: Check `real_positions` and daily 15m/60m K-lines for the past 3 days. Reconstruct V8 overheat and left_pct features.
2.  **Identify (Logic Mismatch)**: Did the user hold through a massive intraday swing without T+0? Did the user sell the highest V8 score stock while keeping the lowest V8 score stock?
3.  **Kronos Fusion (Right-Brain Vibe)**: The automated post-mortem MUST attach the Kronos 3D UMAP `vibe` vectors to the entry and exit points. This captures the high-dimensional "scent" of a trap or washout that simple scalar numbers (like `overheat=6`) miss.
4.  **Atomic Chunking & Semantic Sync**: Do not dump the entire causality chain as a single monolithic block into Tachi. The script must split the chain into specific atomic lessons (e.g., "FOMO Entry", "Missed T+0", "Panic Sell") with hard YAML metadata and Kronos embeddings.
5.  **Alert (Journal RAG)**: When the live intraday Kronos embedding + V8 structure matches these stored atomic vectors, generate a "Causality Warning" immediately. Slap this 800k lesson on the screen to intercept the user before they execute a panic sell.

---

## 5. Time-Slice Vector Embedding (高维时间切片架构)

This 800k lesson fundamentally upgrades our Journal RAG system from a generic text retriever into a **Cross-Dimensional Pattern Recognition Engine**. We no longer label an entire day or an entire action as a generic "mistake". We slice the space-time continuum.

### The True Positive vs. False Positive Dilemma
On Thursday (May 28) morning, buying 合成制造龙头 (SynthFII) was mathematically and fundamentally **CORRECT**, while buying 合成芯片股A (SynthChipA) was purely an emotional **MISTAKE**. Traditional quantitative labels (e.g., "both spiked on high volume") cannot easily differentiate them without context.

### Kronos Time-Slice Embeddings
We solve this by taking a **Time-Slice Vector** of the exact entry window (e.g., 09:30-09:45) and passing it through Kronos UMAP to generate distinct Vibe embeddings:

#### Vector A: The Institutional Accumulation (SynthFII 5.28 Morning Slice)
*   **Alpha (Quant)**: `v8_left_feature.bull_align = True`, 15m volume explosion (34.8亿).
*   **Beta (Semantic)**: AI PC/Server supply chain intel, strong relative strength.
*   **Kronos (Vibe)**: Deep UMAP signature indicating institutional accumulation (True Breakout).
*   **Memory Label**: `TRUE_POSITIVE`. When this vector is matched in the future, the system will actively encourage heavy entry.

#### Vector B: The Retail FOMO Trap (SynthChipA 5.28 Morning Slice)
*   **Alpha (Quant)**: `overheat_index >= 6`, left-side energy rapidly exhausted.
*   **Beta (Semantic)**: Sector-wide retail euphoria.
*   **Kronos (Vibe)**: Deep UMAP signature indicating institutional distribution into retail buying (Wyckoff Trap).
*   **Memory Label**: `FALSE_POSITIVE_TRAP`. When matched, the system triggers the 800k Lesson causality warning and blocks entry.

**Conclusion**: By saving these distinct Time-Slice Vectors into HyperTachi, Hyperion gains the ability to "smell" the difference between a real breakout and a fake pump, bridging the gap between raw math and human intuition.

---

## 6. Empirical Validation (Kronos 实证与高维空间分化)

2026年6月2日，我们使用本地预训练、高达 **1.02 亿参数规模** 的时序基础大模型 `NeoQuasar/Kronos-base`（**832维** Dense Hidden State 表征空间，基于 MPS/GPU 硬件加速），针对这 4 个目标股票在 5月28日至6月2日期间进行了更深高维空间下的特质分化实证。

我们利用网关 `hapi-edge (private runtime)` 强行击穿并实时重构了 SQLite 的 K 线热缓存（Priming），在 GPU 上进行单次前向推理（隐式 OpenBLAS 信号与多线程锁完全隔离），获取了终极、无偏的高维时空特征向量。

---

### 实证 A：15m 级别的微观结构相似度 (Peak Climax at 2026-05-28 10:00)

在 5月28日（星期四）上午 10:00，全情绪最 FOMO、发生买入动作的黄金切片。我们在 `Kronos-base` 15分钟高维微观结构表征中，计算了 128 根 bar 的 Cosine 相似度矩阵：

| 个股 (15m 10:00) | 合成芯片股A (SYNTH_CHIP_A.SH) | 合成芯片股B (SYNTH_CHIP_B.SH) | 合成光模块股 (SYNTH_OPTICAL_A.SZ) | 合成制造龙头 (SYNTH_SynthFII_A.SH) |
| --- | :---: | :---: | :---: | :---: |
| **合成芯片股A (SYNTH_CHIP_A.SH)** | **1.0000** | -0.2383 | **-0.4221** | **-0.5245** |
| **合成芯片股B (SYNTH_CHIP_B.SH)** | -0.2383 | 1.0000 | **0.7064** | 0.3577 |
| **合成光模块股 (SYNTH_OPTICAL_A.SZ)** | **-0.4221** | **0.7064** | 1.0000 | **0.6990** |
| **合成制造龙头 (SYNTH_SynthFII_A.SH)** | **-0.5245** | 0.3577 | **0.6990** | 1.0000 |

#### 💡 Base 模型下的微观暴击 (Supercharged Microstructure Clues):
1.  **合成芯片股A与合成制造龙头的微观负相关骤降至 `-0.5245`**：
    *   在 102M 参数大模型的法医视角下，同样的冲高大阳线，**合成芯片股A的微观交易结构与大牛股合成制造龙头呈现出极强的反向强相关（`-0.5245`）**！
    *   **真相解析**：这彻底在数学上判了死刑。同样的阳线，合成芯片股A在微观上完全是合成制造龙头的完美镜像反面 —— 一个是极其纯粹的**“借高潮情绪高位分发派发（Distribution）”**，另一个则是绝对无死角的**“主力天量强行扫货建仓（Accumulation）”**。
2.  **合成光模块股与合成制造龙头的同质性高达 `0.6990`（约等于 0.70）**：
    *   两只主线上攻同盟股的微观博弈轨迹在 832 维特征空间里展现了高度一致性，合成芯片股B与合成光模块股的微观相似度也达到了 **0.7064**。

---

### 实证 B：日线级的长周期多头位置相似度 (Entry Close at 2026-05-28 Close)

如果仅仅观察日线大周期 (Daily K-line, trailing 256 bars)，`Kronos-base` 提取出来的多头大趋势和筹码纠缠相似度矩阵如下：

| 个股 (Day Close) | 合成芯片股A (SYNTH_CHIP_A.SH) | 合成芯片股B (SYNTH_CHIP_B.SH) | 合成光模块股 (SYNTH_OPTICAL_A.SZ) | 合成制造龙头 (SYNTH_SynthFII_A.SH) |
| --- | :---: | :---: | :---: | :---: |
| **合成芯片股A (SYNTH_CHIP_A.SH)** | 1.0000 | 0.7429 | 0.6986 | **0.8955** |
| **合成芯片股B (SYNTH_CHIP_B.SH)** | 0.7429 | 1.0000 | **0.9749** | 0.6451 |
| **合成光模块股 (SYNTH_OPTICAL_A.SZ)** | 0.6986 | **0.9749** | 1.0000 | 0.6059 |
| **合成制造龙头 (SYNTH_SynthFII_A.SH)** | **0.8955** | 0.6451 | 0.6059 | 1.0000 |

#### 💡 日线宏观障眼法 (Supercharged Macro-Trend Trap):
1.  **日线 0.90 相似度的终极蒙骗**：
    *   如果光看日线慢速慢变特征，**合成芯片股A与合成制造龙头的相似度高达 `0.8955`**！
    *   **终极警示**：这科学地解释了为什么人类会踩大坑。日线上看，它们都是突破年线压力的强势形态，相似度高达 90%。散户几乎必定会在这里产生 FOMO，把假龙头当真主线。**但高维微观切片上，它们在博弈本质上的真伪（`-0.5245` 强负相关）早已判定了胜负！**
2.  **合成芯片股B与合成光模块股日线多头共识高达 `0.9749`**：
    *   两者的多头拔高结构极其同质，是绝对的板块灵魂主线共识。

---

### 实证 C：状态转移时空漂移分析 (Temporal State Drift Analysis)

我们计算了 `5月28日收盘 (Entry)` -> `5月29日大分歧 (Reaction)` -> `6月1日割肉 (Exit)` 连续三个交易日的日线级高维状态漂移（Cosine 相似度越接近 1.0 说明大趋势状态越稳定）：

| 个股状态转移 | Entry -> Reaction (5.28 -> 5.29) | Reaction -> Exit (5.29 -> 6.1) | Entry -> Exit (5.28 -> 6.1) |
| --- | :---: | :---: | :---: |
| **合成芯片股A (SYNTH_CHIP_A.SH)** | 0.9215 | 0.9349 | 0.7835 |
| **合成芯片股B (SYNTH_CHIP_B.SH)** | 0.9313 | 0.9272 | 0.7819 |
| **合成光模块股 (SYNTH_OPTICAL_A.SZ)** | **0.9990** | 0.9729 | 0.9701 |
| **合成制造龙头 (SYNTH_SynthFII_A.SH)** | **0.9828** | 0.9502 | 0.9746 |

#### 💡 漂移轨迹研判 (State Transition Clues):
1.  **合成光模块股超凡的多头金身稳定性 (0.9990)**：
    *   在 `Kronos-base` 832 维时空视角下，合成光模块股在周五剧烈的分歧洗盘大震荡中，**其日线高维特征的稳定性高达 `0.9990`（近乎完美纯净）**！
    *   **操作指引**：这证明周四的大涨和周五的下砸，在大资金和长筹码表征上完全是**同质健康**的。周一的 panic dip 是一次极其完美的黄金买入点，在底部割肉属于严重的操作变形。
2.  **合成制造龙头的极强主线承接力 (0.9828)**：
    *   在周五冲高回落中，合成制造龙头保持了 **0.9828** 的稳定性，洗盘极稳，这属于主线绝对的持股核心，周一绝不能割肉抛售。
3.  **合成芯片股A与合成芯片股B在周一彻底“散架变质” (跌至 0.78 左右)**：
    *   虽然它们周五看似抗跌，但到了周一，其整体趋势特征相比 Entry 发生了严重的退潮劣化（漂移相似度仅为 0.7835 和 0.7819）。大资金已呈作鸟兽散，没有任何死扛价值。

---

## 7. 结语：让 约80万（脱敏）成为 Hyperion 神经-符号之锚

这 约80万（脱敏）并非亏在行情，而是亏在“用宏观的日线大阳线去麻痹微观的资金派发（合成芯片股A），用微观的剧烈洗盘大阴线去恐惧宏观的稳定同质（合成光模块股）”。

本实证数据应作为**金标准病例 (Gold-Standard Pattern Case)** 同步到 `data/tachi/projects/hyperion/memory.db (private — not in this repo)`，目标路径为 `/trading/equity/lessons/800k_causality`。在同步完成并读回确认前，本文档只作为离线实证记录。

研究阶段，当 Hyperion 在回放或仿真中发现某只股票开盘 30 分钟内的 `15min/5min` 高维时间切片特征，与本病例中 `合成芯片股A 5.28 10:00 (Distribution Trap)` 的 Cosine 相似度大于 **0.85** 时，应触发高优先级 Causality Warning 并弹出该报告。该阈值必须经过大样本校准后，才允许晋升为实盘硬阻断规则。
