# 刀 2 / PR #3 设计核对（不合并）

对照 live-site 反馈与 USER DECISION：三条必须能在代码和文档里核验。不编预测边界，不进入刀 3。

## 1) 半句因果：盘面 → 消息 → 因此

**规则**

- `row_thesis` / `one_liner` / `synthesis` 同一条 A 句：先盘面、再消息、最后因此。
- 冲突时「谁压过谁」写在**同一句**里（先以收盘盘面为准），禁止 `走坏。可能相关：标题。` 这种两截漂亮半句。
- 期权口号不得打头。

**证据路径**

| 作用 | 路径 |
| --- | --- |
| 因果模板 / 同句校验 | `src/stock_pm/environment.py`（`causal_one_liner`、`is_causal_chain`、`conclusion_from_stances`） |
| 个股扫描半句 | `src/stock_pm/philosophy.py`（`stock_row_thesis`） |
| 市场半句（期权进 struct，不进 A 句头） | `src/stock_pm/philosophy.py`（`synthesize_environment`） |
| 每标的合成 | `src/stock_pm/environment.py`（`synthesize_symbol_environment`） |
| 测试 | `tests/test_environment.py`、`tests/test_philosophy.py` |

**文案前后**

| | 文案 |
| --- | --- |
| 旧（并排口号，禁止） | `走坏，放量有效跌破。可能相关：芯片股获上调。` |
| 旧（材料抢 A） | `期权认沽偏多，市场偏谨慎（Cboe 一家交易所 P/C 1.20）；自选1只里1只趋势健康…；非农弱于预期 → 降息预期升温。` |
| 新 · 冲突（谁压过谁在同一句） | `盘面：走坏，放量有效跌破；消息：偏多（芯片股获上调）；因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。` |
| 新 · 同向（环境理解，不是预测） | `盘面：趋势健康，近20日+6.0%，氛围观察；消息：行业利多（行业缺货延续），公司利多（行业缺货延续）；因此：盘面与消息同向，只作环境理解，不写成预测或打脸。` |
| 新 · 诚实缺失 | `盘面：结论不足；消息：暂缺，不编方向；因此：盘面与消息都暂缺，不编结论，也不编预测。` |

`is_causal_chain` 要求「盘面」<「消息」<「因此」，且第一个句号必须在「因此」之后。

## 2) 材料下沉为 C（默认折叠）

**规则**

- 期权 / 宏观 / 新闻 / 异动 / 财报原文是 C，默认收起，不得压过总览结论行或个股环境区 A。
- `<details>` 不带 `open`。

**证据路径**

| 作用 | 路径 |
| --- | --- |
| 总览 DOM 顺序：shell → 结论表 → 折叠 C | `src/stock_pm/static/overview.html`（`#stock-pm-shell`、`#briefing-panel`、`#rows`，然后 `<details class="fold zone-c materials">` 包 `#options-panel` / `#news-mapped`） |
| 个股 C 折叠 | `src/stock_pm/static/shell.js`（`<details class="fold zone-c"`，无 `open`） |
| 折叠样式 | `src/stock_pm/static/shell.css`（`details.fold`、`.zone-c`） |
| 测试 | `tests/test_api.py`（`test_static_shell_assets`：rows 在 options/news 之前；C 的 opening tag 无 `open`） |

打开 `/`：先预警 / 显式状态 / 环境半句 / 隔日简报行；「折叠材料（期权 / 宏观 / 新闻 / 异动）」默认关闭。

## 3) 环境 A / B / C 与 §2.4 诚实缺失

**规则**

- A：合成句始终可见（`zone-a` / `.env-line`）。
- B：结构化要点带 `points_to: A` / 「→ 支撑结论」。
- C：折叠，复用既有财报 / 估值 / 资讯接口。
- §2.4 字段（一年涨跌、财报、行业估值、宏观·行业·公司、氛围）有则写入 `struct`，无则 `missingFlags`，不编 PE / 达标 / 标题情绪分。

**证据路径**

| 作用 | 路径 |
| --- | --- |
| A/B/C 壳 | `src/stock_pm/static/shell.js`（`data-zone="A|B|C"`，B 为 `env-bullets`） |
| 字段与 missingFlags | `src/stock_pm/environment.py`（`SYMBOL_FIELD_FLAGS`、`synthesize_symbol_environment`、`failed_snapshot`） |
| 追加历史、失败可见 | `src/stock_pm/environment_job.py`、`src/stock_pm/persist.py`（`append_environment_snapshot` 无 `ON CONFLICT`） |
| 测试 | `tests/test_environment.py`（bullets→A、字段或 flag 覆盖、无编造）；`tests/test_environment_job.py` |

`prediction_ready` 保持 `false`。刀 3 / 打脸状态机不在本 PR。

## 本地怎么核

```text
pytest -q
```

重点：`tests/test_environment.py`、`tests/test_philosophy.py`、`tests/test_api.py` 里总览折叠断言。
