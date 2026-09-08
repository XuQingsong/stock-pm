# Cursor brief — stock-pm 连续切片

本仓库是**现有生产代码**的原地演进。不要另起第二个 app、shell 或 watchlist。

## 产品哲学（PRD v0.2）

- 自动日循环：规则/模型产出次日偏向，次日对照自动写入。
- **主路径没有每日确认门槛**。用户备注可选、可追溯；确认不是架构默认。
- EmptyHonest：用户 UI 不出现 CLI/运维词；缺数显示「数据暂缺」或隐藏卡片。
- 信息架构：A 结论 / B 展开 / C 折叠 / ④ 校验。晨间扫描 + 个股三区。
- 报价：`quote_quality` 标记延迟/不可用；结论价优先复盘收盘或昨收。

## 切片（连续做到打脸，不要停在 M1）

| 切片 | 焦点 | 说明 |
| --- | --- | --- |
| **A / P0** | 哲学与信任 | 去掉确认门槛、EmptyHonest、预警条、显式状态壳、环境半句第一刀。ACCEPTANCE_M1 的 P0/架构红线在此验收。 |
| **B / 环境** | EnvironmentSnapshot 加深 | 刀 2 已落地：每标的 fundamentals / 三层消息 / 氛围合成 + field-level missingFlags + 盘后追加。同仓下一切片分支。 |
| **C / 盘面** | M2 tape/review 闭环 | 刀 3 已落地：昨盘 TapeAnalysis + ReviewNote 总结/解释。同仓下一切片分支。 |
| **D / 预测打脸** | M3 Prediction | 刀 4 已落地：时间窗口+涨跌边界、状态机、盘后 PredictionCheck 自动打脸、人工改口留痕。 |
| M4 | 周洞察 | 可选薄做（刀 5）。 |

这不是「只做 M1」或「首个 PR 只做 M1」。M1 红线是切片 A 的验收焦点，后面三刀仍在同一生产仓库演进。

## 技术

FastAPI + PostgreSQL + 多页 HTML/JS。可加表：`environment_snapshots`、`severity_alerts`、`job_runs`。历史只追加，不覆盖掉旧半句。

## 切片 A 验收

- 主路径不再被「每日偏向 + 保存确认」挡住
- 用户 UI 无 CLI 词；Cboe/期权缺失则藏卡或「数据暂缺」
- 严重预警条：有则显示，无则隐藏
- 显式状态优先级：打脸 > 逾期 > 缺失（完整预测状态机未接入时不得假装已有边界）
- 晨间总览 / 个股有环境半句或诚实缺失标记（`struct` + `missingFlags` + `publishState`）

## 切片 B / 刀 2 进度

- 每只活跃自选有结构化 `EnvironmentSnapshot`：一年涨跌、财报/营收、行业与估值、宏观·行业·公司消息、路径氛围（不是标题情绪分）、合成句、字段级 `missingFlags`、`publishState`。
- 晨间总览半句可扫；冲突仍是一句因果 `row_thesis`。个股 A 结论 / B 指向 A 的要点 / C 折叠原接口。
- `stock-pm-environment` 盘后追加写入；失败落 missing，不覆盖旧快照、不编数字。
- 晨间总览先结论行（预警 / 显式状态 / 环境半句），期权与新闻下沉为折叠 C，不与 A 抢位置。不编预测边界。
- A 半句按 盘面 → 消息 → 因此 写因果，不再并排口号。收口清单见 `docs/DESIGN_CHECK_刀2_PR3.md`。

## 切片 C / 刀 3 进度

- 每只活跃自选有结构化 `TapeAnalysis`：量价形态（放量涨/缩量涨/放量跌/缩量跌）、筹码带+支撑压力、破位后走法、对照 EnvironmentSnapshot 的诱多/转势/吸筹/逃跑（标推断）、`weak_vs_env`、字段级 `missingFlags`、`publishState`。
- `ReviewNote`：白话总结来自昨盘；解释是 环境 → 昨盘 → 因此，或诚实「解释不了」。不编预测边界。
- 晨间总览 `昨盘半句` 用真实 `one_liner`；缺失写暂缺，不编量价。环境与昨盘冲突时只留一句因果，不并排两列。
- `stock-pm-tape` 盘后追加写入；失败落 missing，不覆盖旧行、不编放量缩量。主路径仍无每日确认门槛。
- 个股壳三区：环境 | 昨盘 | 复盘与预测。K 线 MA5/20/50/200 与原接口留在折叠 C。预测区仍是非假占位。

## 切片 D / 刀 4 进度

- 每只活跃自选可有结构化 `Prediction`：时间窗口、上涨边界、下跌边界（合格例：两周内补涨约10%，期间跌幅不超过5%）。因果链是 环境→昨盘→解释→因此。质量门不过则「到期未产出/缺数」，不编假边界。
- 状态机：auto-gen → pending → active → hit / invalidated(打脸) / superseded。盘后 `PredictionCheck` 破界自动打脸；窗口到期未兑现也打脸。对照价缺失不静默判对。
- 严重预警带人工改口 CTA；`supersedes` 留痕。小噪声不自动改口。
- 晨间总览预测徽章绑真实 Prediction。`llm_outlook` 与旧命中率标「旧口径」。
- `stock-pm-prediction` 盘后追加写入；已有未结束预测只做检查，不叠一条新预测。主路径仍无每日确认门槛。
