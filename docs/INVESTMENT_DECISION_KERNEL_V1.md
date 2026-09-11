# Investment Decision Kernel v1

阶段 1 只建立投资分析内核与 Golden Tests。不改页面、API、schema，不接外部数据。

本内核是新的决策主链，不是旧 `impact.macro_impact` / `environment.causal_one_liner` / `prediction.synthesize_prediction` 的平行产品。那些模块继续服务现有页面；宏观→个股方向必须走本内核，不得复用会跳层的 `MACRO_RULES`。

复用：`analytics._number`（缺失保持 `None`，不转 0）、`impact.THEME_NAMES`（行业/主题命名）。

## 主链

```
Facts
  → What Changed / Change Layer
  → Expectation Layer
  → Price / Expectation Tension
  → Causal Impact
  → Thesis
  →（后续阶段）Prediction / UI / Outcome
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

输入：`metric`，previous/current 事实（`value`, `as_of`, `fact_ref`），可选 `comparison_window`、`materiality_rule`。

输出：`id`, `metric`, `previous_value/current_value`, `previous_as_of/current_as_of`, `delta`, `delta_pct`, `comparison_window`, `direction` (`up`/`down`/`unchanged`/`unknown`), `materiality` (`material`/`immaterial`/`unknown`), `fact_refs`, `summary`。

无 previous → `direction=unknown`，禁止「上升/下降」。低于阈值 → 仍可有方向，但 `materiality=immaterial`，summary 可为「今日无重大变化」。

### `ExpectationGap` ← `build_expectation_gap`

输入：`actual`, `latest_consensus`（财报前最新）, `prior_consensus`（更早一次）, 各时点 `as_of`/`source`/`currency`/`basis`（GAAP/non-GAAP）, `fiscal_period`, 可选 `analyst_count`。

输出：`actual_vs_latest_pct`（surprise）, `latest_vs_prior_pct`（revision）, `revision_trend`（仅当 prior 存在且口径一致）, `status` (`ok`/`conflict`/`insufficient`), refs。

口径或币种冲突 → `conflict`，不任选。缺 prior → 无 `revision_trend`。

### `PriceExpectationTension` ← `build_price_expectation_tension`

输入：EPS/营收 revision%、价格变动%、可选估值变动。

输出：`fundamentals_change`, `price_change`, `valuation_change`, `tension` ∈ {`improving_faster_than_price`, `price_ahead_of_fundamentals`, `aligned`, `insufficient`}, `evidence_quality`。

缺核心序列 → `insufficient`。永不输出 `priced_in`。

### `CausalImpact` ← `build_causal_impact`

必填结构：`cause`, `market_confirmation`, `mechanism`, `exposure`, `effect_target`, `direction`, `horizon`, `counter_evidence`, `confidence`, `fact_refs`, `status`。

宏观路径必须 `assess_market_confirmation`。`status=unconfirmed` 时中文理由含「市场未确认」，`direction` 为空。`source_class=social` 且未核实 → `unverified`。Oil 可对能源生产商为正、航空为负；高估值科技仅当利率通道确认才允许负向。

### `ThesisSnapshot` ← `build_thesis_snapshot`

`direction`, `bull_drivers`≤3, `bear_drivers`≤3, `key_disagreement`, `invalidation`, `evidence_quality`, `based_on_change_ids`, `based_on_expectation_ids`, `based_on_causal_impact_ids`, `generated_at`, `status`。

缺核心输入 → `incomplete`，不得给强方向。支持与反方冲突 → `neutral` 或 `incomplete`，反方必须保留。

### `WhatChanged` ← `build_what_changed`

输入：changes、gaps、impacts、previous/current thesis。

每条必须能回答：什么变了、为什么重要、影响什么、是否改变 Thesis、若未改变为什么。全低于 materiality → 唯一摘要「无重大变化，原判断不变」。

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
| J | 非法 OHLC → 事实校验失败，不能进入后续层 | `validate_ohlc` / `require_valid_bar` |

## 明确不在本阶段

Prediction、UI、API、数据库、Outcome 回检、概率、多周期、外部数据源、自动学习。
