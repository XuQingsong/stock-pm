# Investment Decision Kernel v1

本内核是新的决策主链，不是旧 `impact.macro_impact` / `environment.causal_one_liner` / `prediction.synthesize_prediction` 的平行产品。那些模块继续服务现有页面；宏观→个股方向必须走本内核，不得复用会跳层的 `MACRO_RULES`。阶段范围只维护在文末「阶段边界」，此处不重复。

复用：`analytics._number`（缺失保持 `None`，不转 0）、`impact.THEME_NAMES`（行业/主题命名）。

## 主链

```
Facts
  → What Changed / Change Layer
  → Expectation Layer
  → Price / Expectation Tension
  → Causal Impact
  → Thesis
  →（阶段 2）现有 `/stock/{symbol}` 页面 + 只读 decision endpoint
  →（后续阶段）Prediction / Outcome
```

禁止跨层跳跃：没有通过事实校验的 OHLC 不得生成 Change；没有比较基准不得声称涨跌；没有最新财报前共识不得把 actual 去跟更早预期比；没有传导机制+exposure 不得从宏观得出个股方向；没有市场确认不得把宏观印成有效 CausalImpact；未确认新闻不得改 Thesis。

## 每层职责

| 层 | 职责 | 不做什么 |
| --- | --- | --- |
| Facts | 校验原始点：OHLC 不等式、币种/口径、来源 refs | 不解释、不定方向 |
| Change | 同一指标 previous vs current：delta 与重要性分离 | 无基准不说上升/下降；missing ≠ 0 |
| Expectation | actual vs **最新**财报前共识；共识修订 vs 更早共识 | 不把 surprise 写成「超预期利好」；缺历史共识无 revision trend |
| Tension | 基本面修订 vs 价格 vs 估值，描述谁跑得更快 | 不输出 `priced_in` |
| Causal | cause + 机制 + exposure + 市场确认 → 对**该**标的的方向 | 宏观事实不直接跳个股；未确认新闻只做线索 |
| Thesis | 同时保留多空、核心分歧、失效条件 | 不给涨跌区间或概率 |
| WhatChanged | 回答变了什么、为何重要、影响谁、Thesis 变没变 | 不用旧新闻或条目数量填充 |

## 输入输出契约

对象均为纯函数结果（dataclass → dict）。测试 fixture 必须标 `synthetic: true`。

### `ChangeSnapshot` ← `build_change_snapshot`

输入：`metric`；**价格类指标**（close/open/high/low/price/last）必须消费 `ValidatedBar`，禁止把原始 `current_value` 送进 Change；公司级非价格序列必须消费 `ValidatedFact`；仅全局宏观序列允许原始数值。可选 `comparison_window`、`materiality_rule`。

输出：`id`, `metric`, `previous_value/current_value`, `previous_as_of/current_as_of`, `delta`, `delta_pct`, `comparison_window`, `direction` (`up`/`down`/`unchanged`/`unknown`), `materiality` (`material`/`immaterial`/`unknown`), `fact_refs`, `summary`。

`FactRef` 必须具备非空 `ref_table` / `ref_id` / `as_of` / `source`，且 `as_of` 必须是可解析的 ISO 日期/时间；空壳或 `not-a-date` 不得构造。`ValidatedBar` / `ValidatedFact` 必须有可解析 `as_of`。`ValidatedBar` / `ValidatedFact` / `ExpectationPoint` 自身携带 `scope`/`subject`；symbol scope 缺 subject 失败。builder 与 `require_valid_bar` 从输入推导身份：row 已标明 subject/symbol 时，参数不得重贴为另一个标的（`identity_override`）。previous/current 身份不一致失败。证据 `id` 必须包含 scope + 规范化 subject。

`ValidatedBar` / `ValidatedFact` 在 `__post_init__` 内强制校验，直接构造非法实例会失败。价格 Change 必须消费已通过校验的 `ValidatedBar`。`MaterialityRule.abs_delta` / `pct_delta` 必须是有限且 `>= 0` 的阈值，负数不得让任意变化变成 material。

Change / Expectation 带 `scope`（global/sector/symbol）与 `subject`。公司 Thesis 只能直接引用同标的公司级证据；全局宏观必须经 CausalImpact。bull/bear driver 必须与方向性 CausalImpact 极性一致。合格证据必须有可追溯 FactRef；无 refs 的 material Change / ok Gap / valid-looking Impact 不得进入 Thesis（`missing_provenance`）。

### `ExpectationGap` ← `build_expectation_gap`

输入：`actual`, `latest_consensus`（财报前最新）, `prior_consensus`（更早一次）, 各时点 `as_of`/`source`/`currency`/`basis`（GAAP/non-GAAP）, `fiscal_period`（gap 与各 point 必须一致）, 可选 `analyst_count`。

输出：`actual_vs_latest_pct`（surprise）, `latest_vs_prior_pct`（revision）, `revision_trend`（仅当 prior 存在且口径一致）, `status` (`ok`/`conflict`/`insufficient`), refs。

必须解析并验证 **UTC** 下 `prior_as_of < latest_as_of < actual_as_of`，且 latest 在财报前。缺失或非法 `as_of` → `insufficient`；时间颠倒 → `conflict`；不同或缺失 fiscal period → `insufficient`。同一快照两个 latest consensus 超容差 → `conflict`，两个 source refs 均保留。actual(company) 与 consensus(street) 的来源不同不视为冲突。缺 latest.value → `insufficient`，即使 prior 有值。

### `PriceExpectationTension` ← `build_price_expectation_tension`

输入：EPS/营收 revision%、价格变动%、可选估值变动。

输出：`fundamentals_change`, `price_change`, `valuation_change`, `tension` ∈ {`improving_faster_than_price`, `price_ahead_of_fundamentals`, `aligned`, `divergence`, `price_decline_ahead_of_fundamentals`, `deteriorating_faster_than_price`, `insufficient`}, `divergence_kind`, `evidence_quality`, `code`。

先处理方向背离：基本面与价格符号相反 → `divergence`。正同号才使用 improving/涨幅语义；负同号使用 deterioration/price_decline 语义，不得复用涨幅文案。缺核心序列 → `insufficient`。永不输出 `priced_in`。

### `CausalImpact` ← `build_causal_impact`

必填结构：`cause`, `market_confirmation`, `mechanism`, `exposure`, `effect_target`, `direction`, `horizon`, `counter_evidence`, `confidence`, `fact_refs`, `status`。

宏观路径必须 `assess_market_confirmation`。确认序列按规范化指标去重，要求独立通道 ≥2，**comparison_window 与 UTC as_of 均在容差内**（缺 as_of 不得 confirmed）。`fact_refs` 合并 cause 与**实际采用**的 confirmation channel refs，未采用序列不得冒充证据。cause 必须 material 且自身带完整 refs；cause 指标必须与 mechanism 兼容。

`MarketConfirmation(status="confirmed")` 不可伪造：`__post_init__` 与 `build_causal_impact` 均重新验证 `used`（≥2 个去重合格独立通道、方向、materiality、窗口、as_of、refs）。空 `used`、重复指标、无 refs 或方向不合均不得 confirmed/valid。

### `ThesisSnapshot` ← `build_thesis_snapshot`

`direction`, `bull_drivers`≤3, `bear_drivers`≤3, `key_disagreement`, `invalidation`, `evidence_quality`, `based_on_change_ids`, `based_on_expectation_ids`, `based_on_causal_impact_ids`, `generated_at`, `status`。

每个 driver 必须引用存在且合格的 ID：material Change、ok Expectation、valid CausalImpact，且均须带完整 FactRef。自由文本、引用不存在、跨标的、缺来源、重复证据 ID → `incomplete`（`free_text` / `missing_citation` / `cross_symbol` / `missing_provenance` / `duplicate_evidence_id`）。`_catalog` 遇到同一 ID 指向不同对象必须 conflict，禁止静默覆盖。权重规则：两侧都引用了方向相反的 valid CausalImpact → `neutral`，保留两侧；无对立的 cited valid causal 可以给方向，仍保留反方 driver。未引用的 valid impact 不得决定方向。

### `WhatChanged` ← `build_what_changed`

输入：changes、gaps、impacts、previous/current thesis。

每条必须能回答：什么变了、为什么重要、影响什么、是否改变 Thesis、若未改变为什么。解释只许来自 `change.summary` / `gap.reason` / `impact.reason` / Thesis semantic diff，禁止编造「数值变化未跨过判断阈值」「已有判断已覆盖该机制」「预期修订尚未单独推翻 Thesis」。Thesis 比较 direction、drivers、key_disagreement、invalidation、evidence_quality、citations，不只比方向。按 materiality、recency、影响层级（causal > expectation > change > thesis）稳定排序。全低于 materiality 且 Thesis 未变 → 唯一摘要「无重大变化，原判断不变」。

## 不允许跨层跳跃

1. OHLC 不满足 `high>=open/close`、`low<=open/close`、`high>=low` → `FactValidationError`，后续层不得吞掉。
2. Change 不得把 `None` 当 0。
3. Surprise 只对 **latest pre-print consensus**。
4. `MACRO_RULES` / 新闻标题不得替代 CausalImpact。
5. 无机制或缺 exposure 不得给个股 `direction`。
6. 未确认新闻不得写入有效 CausalImpact，也不得把 Thesis 标成已改变。

## Golden Tests 映射

| ID | 断言 | 入口 |
| --- | --- | --- |
| A | CPI 略高但 US2Y/实际利率/降息预期/VIX 未确认 → 「市场未确认」，无科技股偏空 CausalImpact | `assess_market_confirmation` + `build_causal_impact` |
| B | CPI 显著超预期且利率路径确认 + `high_valuation_duration` → 通胀→利率→折现率→高估值短期承压 | `build_causal_impact` |
| C | 1.18→1.28→1.30 → revision≈+8.47%，surprise≈+1.56%，不是「超预期利好」 | `build_expectation_gap` |
| D | EPS+7.6%、股价+22%、PE 31→36 → `price_ahead_of_fundamentals` | `build_price_expectation_tension` |
| E | 油价上涨：能源生产商可正、航空可负；高估值科技仅利率通道确认才允许负 | `build_causal_impact` |
| F | 未核实战争/制裁社媒 → `unverified`/`insufficient`，Thesis 不变 | `build_causal_impact` + `build_what_changed` |
| G | 多空冲突 → `neutral`/`incomplete`，反方仍在 | `build_thesis_snapshot` |
| H | 全低于 materiality → 「无重大变化，原判断不变」 | `build_what_changed` |
| I | 缺历史共识 → 无 `revision_trend` | `build_expectation_gap` |
| J | 非法 OHLC → 不能生成 `ValidatedBar`；绕过校验把价格传入 Change 失败；合法 bar 才能生成价格 Change | `validate_ohlc` / `require_valid_bar` / `build_change_snapshot` |
| K | latest 在 actual 之后 → `conflict`，不得 status=ok | `build_expectation_gap` |
| L | prior 晚于 latest → `conflict` | `build_expectation_gap` |
| M | fiscal period 不同 → `insufficient`，禁止比较 | `build_expectation_gap` |
| N | 同一 us2y 重复两次不得 confirmed | `assess_market_confirmation` |
| O | immaterial cause 即使确认序列齐备也不得 valid | `build_causal_impact` |
| P | WTI 不得套用 `inflation_to_rates_to_discount` | `build_causal_impact` |
| Q | 方向不变但核心论据改变 → `thesis_changed=True` 并列出 changed fields | `build_what_changed` |
| R | fund=-10%、price=+5% → `divergence` / `fundamentals_down_price_up` | `build_price_expectation_tension` |
| S | fund=+10%、price=-5% → `divergence` / `fundamentals_up_price_down` | `build_price_expectation_tension` |
| T | 直接构造非法 ValidatedBar 必须失败，不能生成 Change | `ValidatedBar` / `build_change_snapshot` |
| U | NVDA Thesis 引用 AAPL EPS gap → incomplete | `build_thesis_snapshot` |
| V | 宏观 CPI Change 直接作为 NVDA driver → incomplete | `build_thesis_snapshot` |
| W | bull driver 引用 bearish impact → incomplete | `build_thesis_snapshot` |
| X | 两个 latest consensus 同快照超容差 → conflict，两个 refs 均保留 | `build_expectation_gap` |
| Y | 跨时区 as_of 按 UTC 排序正确 | `build_expectation_gap` |
| Z | 相隔数月但同为 1d 窗口不得 confirmed | `assess_market_confirmation` |
| AA | valid rates impact.fact_refs 含 CPI 与实际确认通道，不含未采用序列 | `build_causal_impact` |
| AB | fund=-10%、price=-30% → price_decline 语义，不是涨幅 | `build_price_expectation_tension` |
| AC | fund=-20%、price=-5% → deteriorating，不是 improving | `build_price_expectation_tension` |
| AD | 无 refs 的 material Change / ok Gap / valid-looking Impact 不得形成 Thesis，`code=missing_provenance` | `build_thesis_snapshot` |
| AE | AAPL 与 NVDA 同期 EPS/price 的证据 ID 必须不同 | `build_change_snapshot` |
| AF | 强制重复证据 ID → Thesis `incomplete`，`code=duplicate_evidence_id` | `build_thesis_snapshot` |
| AG | AAPL ValidatedFact/ExpectationPoint 重贴 NVDA 标签必须失败 | `build_change_snapshot` / `build_expectation_gap` |
| AH | 输入点 subject 不一致 → `conflict`，`code=subject_mismatch` | `build_expectation_gap` |
| AI | 伪造 confirmed / 空 used 不得 valid | `MarketConfirmation` / `build_causal_impact` |
| AJ | used 含重复指标、无 refs 或方向不合不得 valid | `MarketConfirmation` / `assess_market_confirmation` |
| AK | row 标明 AAPL、参数传 NVDA → `identity_override` | `require_valid_bar` |
| AL | 无 as_of / 不可解析 as_of 的 ValidatedBar 与 FactRef 不得进入后续层 | `ValidatedBar` / `FactRef` |
| AM | 负数 materiality 阈值不得构造，不能把任意变化变成 material | `MaterialityRule` |

## 阶段边界

- **阶段一**：只建立本内核与 Golden Tests A–AM。不含 UI、API、schema migration、外部数据源。
- **阶段二**：只把本内核接到现有 `/stock/{symbol}` 页面，并增加只读 `GET /api/stock/{symbol}/decision`。生产路径只读现有表；缺 US2Y/VIX/前次共识时必须显示 gap。合成 A/B/C 必须 `ENABLE_DECISION_PREVIEW=true` 且 `APP_ENV` 为 development/test/local，页面标注「合成演示数据」；缺省或生产环境绝不返回 fixture。
- **明确不含**：schema migration、Alpha Vantage / SEC / 新闻等新外部数据源、预测价格/概率、Outcome 回检、多周期、自动学习。不合并阶段 1 Draft。

数据集时钟只使用 `observed_at` / `ingested_at` / `synced_at` / `source_as_of` / 已成交 `bar_time`。`event_time`、`release_date`、`fiscal_period` 是事件或计划时间，不得推进时钟；无可靠观察时间返回 `clock_insufficient`，不得用 `date.today()` 或未来日程代替。
