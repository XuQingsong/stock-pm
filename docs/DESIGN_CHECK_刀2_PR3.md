# 刀2 三项收口清单（PR #3，不合并）

对照 gate。每条都有证据路径 + 中文样句。不编预测 / 打脸，不进入刀 3。

```text
1) 半句因果: template 盘面→消息→因此; conflict still ONE sentence with who-overrides-whom; forbid two slogan halves / dual columns.
2) 材料后置: options/news are C, default folded; must not steal conclusion row (A: half-sentence / explicit state / alerts).
3) 环境 A/B/C + §2.4: A synthesis always on; B bullets point to A; C folded; §2.4 fields complete OR honest missingFlags (no fabrication).
```

---

## 1) 半句因果

**Gate：** template 盘面→消息→因此；冲突仍是**一句**写清谁压过谁；禁止两截口号 / 双列。

**证据路径**

- `src/stock_pm/environment.py` — `causal_one_liner`、`is_causal_chain`、`conclusion_from_stances`、`_as_clause`
- `src/stock_pm/philosophy.py` — `stock_row_thesis`、`synthesize_environment`（期权只进 `struct`，不打 A 句头）
- `tests/test_environment.py` — `test_causal_chain_rejects_slogan_halves`、`test_snapshot_answers_acceptance_environment_questions`
- `tests/test_philosophy.py` — `test_conflict_row_is_one_sentence`、`test_environment_one_liner_joins_facts`

`is_causal_chain`：`盘面` < `消息` < `因此`，且第一个 `。` 必须在 `因此` 之后；拒绝 `可能相关`。

**中文样句**

| 角色 | 句子 |
| --- | --- |
| 禁止（两截口号） | `走坏，放量有效跌破。可能相关：芯片股获上调。` |
| 禁止（材料抢 A / 双列） | `期权认沽偏多…；自选趋势健康…；宏观降息。` |
| 冲突 · 谁压过谁同一句 | `盘面：走坏，放量有效跌破；消息：偏多（芯片股获上调）；因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。` |
| 同向 · 不是预测 | `盘面：趋势健康，近20日+6.0%，氛围观察；消息：行业利多（行业缺货延续），公司利多（行业缺货延续）；因此：盘面与消息同向，只作环境理解，不写成预测或打脸。` |
| 诚实缺失 | `盘面：结论不足；消息：暂缺，不编方向；因此：盘面与消息都暂缺，不编结论，也不编预测。` |
| 市场半句（期权不打头） | `盘面：自选1只里1只趋势健康、0只走坏、0只过热；消息：非农弱于预期 → 降息预期升温，利多高估值成长（NVDA）；因此：盘面与消息同向，只作环境理解，不写成预测或打脸。` |

---

## 2) 材料后置

**Gate：** options/news 是 C，默认折叠；不得抢走结论行（A：半句 / 显式状态 / 预警）。

**证据路径**

- `src/stock_pm/static/overview.html` — `#stock-pm-shell`（A：预警+状态+半句）→ `#briefing-panel` / `#rows`（结论行）→ `<details class="fold zone-c materials">`（无 `open`）包 `#options-panel`、`#impact-panel`、`#news-mapped`
- `src/stock_pm/static/shell.js` — 个股 `<details class="fold zone-c"` 无 `open`
- `src/stock_pm/static/shell.css` — `details.fold`、`.zone-c`
- `tests/test_api.py` — `test_static_shell_assets`：`#rows` 下标 < options/news；C opening tag 无 `open`

**中文样句（C 摘要，不是 A）**

| 角色 | 句子 |
| --- | --- |
| 总览 C 折叠条 | `折叠材料（期权 / 宏观 / 新闻 / 异动）` |
| 总览 C 说明 | `这些是支撑材料，不是晨间结论。缺数就藏或写「数据暂缺」，不编影响。` |
| 个股 C 折叠条 | `折叠材料（财报 / 估值 / 资讯原接口，不在结论区铺开）` |

打开 `/`：先 A（预警 / 显式状态 / 环境半句）和结论表，期权与新闻在页面下方且默认收起。

---

## 3) 环境 A/B/C + §2.4

**Gate：** A 合成始终可见；B 要点指向 A；C 折叠；§2.4 字段齐或诚实 `missingFlags`（不编造）。

**证据路径**

- `src/stock_pm/static/shell.js` — `data-zone="A"` 结论始终渲染；B `env-bullets` + `→ 支撑结论`；C `<details>` 无 `open`
- `src/stock_pm/environment.py` — `SYMBOL_FIELD_FLAGS`（`fundamentals.year_move|earnings|industry|valuation`、`news.macro|sector|company`、`sentiment`）、`synthesize_symbol_environment`、`failed_snapshot`；bullets `points_to: "A"`
- `src/stock_pm/environment_job.py`、`src/stock_pm/persist.py` — 只追加，失败写 missing
- `tests/test_environment.py` — 字段或 flag 覆盖、`points_to == "A"`、无 PE/持续超预期编造
- `tests/test_environment_job.py` — 失败可见 missing，不静默

**中文样句**

| 角色 | 句子 |
| --- | --- |
| A 始终可见（冲突合成） | `盘面：走坏，放量有效跌破；消息：偏多（芯片股获上调）；因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。` |
| B 指向 A | `消息面 · 宏观 … → 支撑结论` |
| B 诚实缺字段 | `基本面 · 估值 估值暂缺，不编造 → 支撑结论` |
| C | `折叠材料（财报 / 估值 / 资讯原接口，不在结论区铺开）` |
| 失败 / 不编造 | `环境快照生成失败，数据暂缺，未编造数字。` |

`prediction_ready` 保持 `false`。

---

## 本地怎么核

```text
pytest -q
```

重点：`tests/test_environment.py`、`tests/test_philosophy.py`、`tests/test_api.py`。
