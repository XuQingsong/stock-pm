# Stock-PM Brain V1：设计与改造计划

> 状态：设计冻结草案（本文件只定架构与 Sprint 1 文件级计划，不改生产主流程）。
> 目标：把系统从「信息展示 / 新闻聚合 / 日循环判断」升级为「Evidence → Assumption → Thesis → Valuation → Monitoring → Review」的可持续研究系统。
> AVGO 只是 Golden Case 测试数据，禁止任何 ticker 专属流程代码。

本文回答五件事：

1. 现有模块哪些可以复用
2. 需要新增哪些表 / 模型
3. 需要新增哪些 service / module
4. 哪些现有逻辑需要重构
5. Sprint 1 的具体文件级开发计划

---

## 0. 结论先行

现有仓库已经是一套可用的 **日循环决策台**：自选、行情、财报数字、可信事件、宏观传导、个股五段页、预测打脸。它 **不是** 投资研究系统：没有可版本化的 Investment Thesis，没有可动态生成的 Assumption，没有可追溯的研究级 Evidence，也没有可插拔 Agent Runtime。

Brain V1 **不要替换**现有总览 / 个股日判断 / 复盘。在旁边加一条研究主链，共用数据源，禁止共用「新闻直接改判断」的捷径。

三条硬决定：

1. **新包 `stock_pm.research`**，不把 Brain 对象塞进 `decision/`、`pack/`、`events/`。
2. **不引入 VoltAgent TypeScript 运行时**。只借用角色隔离、JSON 契约、supervisor 委托、workflow-as-config。运行时用现有 FastAPI + PostgreSQL + 轻量 Python Agent Runtime。
3. **两套 Thesis 共存，名字不许混用**：
   - `decision.thesis.ThesisSnapshot`：日循环因果判断（现网继续服务 `/stock/{symbol}`）。
   - `research.InvestmentThesis`：版本化投资命题（Brain 主对象）。

POC 通过标准不是「用了多少 Agent 框架」，而是：通用 Workflow 能否从财报/电话会 **自行发现**管理层长期承诺（例如 30GW），并生成 Assumption + ResearchTask + 正反 Evidence。代码和 Prompt 里不得出现该承诺。

---

## 1. 现有系统画像

### 1.1 现在实际在做什么

主链是日循环，不是研究循环：

```
Alpaca / FMP / Nasdaq / FRED / AV / SEC
  → PostgreSQL（bars, earnings, news, trusted_events, snapshots）
  → Decision Kernel（Facts → Change → Expectation → Tension → Causal → ThesisSnapshot）
  → Pack（overview / stock / review 页面）
  → Prediction（短窗口涨跌边界 + 打脸）
```

对应代码位置：

| 层 | 路径 | 现状 |
| --- | --- | --- |
| HTTP | `src/stock_pm/api.py` | FastAPI；`/api/desk/*` 是主路径；`/api/stock/{symbol}/decision` 只读内核 |
| DB | `sql/schema.sql` + `sql/migrations/0002–0003` | 行情、财报数字、新闻、watchlist、日循环快照、可信事件 |
| 读取 | `queries.py`（`QueryMixin`，约 2800 行） | 已过大；Brain 禁止再往这里堆方法 |
| 写入 | `persist.py`（`PersistMixin`） | ingest / upsert；历史只追加 |
| 日判断内核 | `decision/` | 纯函数，强 provenance；**不落库** |
| 日页面装配 | `pack/` | overview / stock / review view-model |
| 事件 | `events/` | 可信事件、claim、earnings evidence、SEC/AV |
| LLM | `llm.py` | OpenAI/Anthropic chat；**只服务 daily review 文案** |
| 前端 | `static/stock.html` + `desk.js` | 五段：当前判断 · 昨→今/中期 · 驱动 · 风险 · 观察/失效 |

### 1.2 现有「Thesis」不是 Brain Thesis

`ThesisSnapshot`（`decision/thesis.py`）是：方向 + 最多 3 个多头/空头 driver + 核心分歧 + 失效条件。它强制每个 driver 引用 material Change / ok Expectation / valid CausalImpact，且必须有 `FactRef`。

这套约束 **值得 Brain 借鉴**，但对象粒度不对：

- 没有 short / mid / long view
- 没有 Assumption 层
- 没有 Valuation
- 没有 version
- 新闻未确认不得改 Thesis（好约束），但整个对象是当日装配结果，刷新即丢

`queries.fundamentals_thesis_view` 更不是 Thesis：它是 YoY、同主题中位、回推 PE 的规则摘要。

`predictions.thesis` 是短窗口预测因果句，也不是投资命题。

### 1.3 已有 ticker 耦合（Sprint 6 必须清）

这些不是业务流程 if/else，但已经是「名单写死在代码里」：

| 位置 | 内容 | 风险 |
| --- | --- | --- |
| `config.DEFAULT_WATCHLIST` | AVGO/NVDA/XOM 等种子行 | 可接受：这是数据种子，不是流程 |
| `events/earnings.py` `FISCAL_YEAR_END_MONTH` | AAPL=9, AVGO=10, NVDA=1… | 新 ticker 缺 FYE 就跳过 transcript |
| `events/av_earnings.py` `WATCH_CIKS` | 种子股 CIK | 未知 issuer 无法挂 SEC |
| `events/resolve.py` `ENTITY_ALIASES` | nvda/nvidia/aapl… | 事件实体识别漏新票 |
| `events/exposure.py` `SEMIS_MARKERS` | 含 `nvda` | 主题暴露带公司名 |
| `impact.py` `NEWS_THEME_KEYWORDS["semis"]` | nvidia, broadcom | 新闻打标带公司名 |

Brain 主流程 **禁止再增加** 这类词典。Sprint 6 把 CIK / FYE / 别名迁到 issuer 数据表。

---

## 2. 现有模块哪些可以复用

原则：复用 **数据、校验、I/O、页面壳**；不复用 **日判断语义、MACRO_RULES、新闻改口、daily LLM prompt**。

### 2.1 直接复用（几乎不改）

| 模块 | 给 Brain 什么 |
| --- | --- |
| `watchlist` + `POST /api/watchlist` | 新 ticker 入口；`_backfill_symbol` 可挂研究 workflow |
| `price_bars` / `daily_price_bars` / `bars.py` | 价格、event window、相对指数 |
| `earnings_reports` + `analytics.earnings_scorecard` / `yoy_from_rows` | 近 4–6 季增长、beat/miss |
| `fundamentals_snapshots` + `providers.FMPProvider` | 公司资料、TTM 比率 |
| `news_articles` | 新闻原文（只能进 Evidence，不能改 Thesis） |
| `macro_events` + FRED | 宏观事实 |
| `trusted_events` / `trusted_event_sources` / `trusted_event_claims` | 高信任事件与出处 |
| `events/av_earnings.py` | AV EARNINGS / ESTIMATES / TRANSCRIPT（长期承诺的主要发现口） |
| `events/evidence.py` | publisher identity、excerpt 必须真正支撑 claim |
| `decision.types.FactRef` 规则 | 无 `ref_table` / `source` / `as_of` 不得进结论 |
| `decision.expectation` | Guidance vs actual 的时间顺序与口径冲突检测 |
| `decision.tension` | 「基本面 vs 价格谁跑得更快」——Quant price-in 的规则底座（永不输出 `priced_in` 一词，改成 tension 枚举） |
| `llm.py` 的 HTTP/配额/JSON 解析 | Agent Runtime 的模型适配层（拆出通用 `complete_json`） |
| `migrate.py` | 编号 SQL 迁移 |
| `job_runs` | 研究 job 状态 |
| `static/stock.html` 个股壳 | Sprint 7 在现页 **加研究区**，不重做首页 |
| EmptyHonest / 无持仓口径 | Brain UI 同样禁止仓位动作词、禁止编数字 |

### 2.2 借鉴模式，不直接当 Brain 对象

| 现有 | Brain 对应 | 做法 |
| --- | --- | --- |
| `ThesisSnapshot` provenance | `InvestmentThesis.key_assumption_ids` → Evidence | 复制「无引用即 incomplete」，换引用对象 |
| `predictions` 状态机 + supersede | Thesis 版本化 | append-only 新版本，不改旧行 |
| `environment_snapshots` 只追加 | Assumption / Evidence 历史 | 状态变更写新事件，不覆盖 statement |
| `pack.assemble` I/O 适配 | `ResearchPack` builder | 新包，不把研究字段塞进 desk payload |
| `events.EarningsEvidence` | Fundamental Evidence | 财报数字可升格为 Evidence，但 Research Evidence 是独立表 |

### 2.3 明确不复用

- `impact.MACRO_RULES` / 新闻标题 → 个股方向
- `llm.py` 的 daily `SYSTEM_PROMPT`（why/outlook/bias）
- `prediction.synthesize_prediction` 当长期估值
- `pack.stock_page` 的「三个驱动来自今日事件卡」当 Core Thesis
- VoltAgent npm 包、`.claude/agents` 当生产运行时

---

## 3. 需要新增哪些表 / 模型

迁移文件：`src/stock_pm/sql/migrations/0004_research_brain.sql`。**不改** `schema.sql` 快照（0001 已冻结）。

### 3.1 表

所有业务键用 `ticker TEXT`（与现网 `symbol` 同义，API 路径仍用 `{symbol}`，入库统一大写）。禁止按 ticker 建特化表。

#### `research_tasks`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | TEXT PK | `rtask_` + uuid |
| `ticker` | TEXT NOT NULL |  |
| `task_type` | TEXT NOT NULL | `discover_fundamentals` / `verify_assumption` / `industry_check` / `quant_price_in` / `skeptic_attack` / `pm_review` / `monitor` |
| `title` | TEXT NOT NULL |  |
| `description` | TEXT NOT NULL |  |
| `source_reason` | TEXT NOT NULL | 为何生成：template seed / agent follow-up / assumption gap |
| `required_data` | JSONB | 例如 `["earnings","transcript","guidance"]` |
| `assigned_agents` | TEXT[] |  |
| `priority` | INTEGER | 默认 50 |
| `status` | TEXT | `pending` / `running` / `completed` / `blocked` / `cancelled` |
| `created_by` | TEXT | `template` / `agent:{name}` / `pm_judge` / `system` |
| `created_at` / `completed_at` | TIMESTAMPTZ |  |

索引：`(ticker, status, priority)`。

#### `research_evidence`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | TEXT PK | `rev_` + uuid |
| `ticker` | TEXT NOT NULL |  |
| `evidence_type` | TEXT NOT NULL | `fundamental` / `guidance` / `management_commitment` / `industry` / `competitive` / `quant` / `news` / `macro` / `filing` / `transcript` |
| `fact` | TEXT NOT NULL | 可核验陈述，不是观点 |
| `source` | TEXT NOT NULL |  |
| `source_url` | TEXT |  |
| `source_time` | TIMESTAMPTZ NOT NULL | 事件/文档时间 |
| `retrieved_at` | TIMESTAMPTZ NOT NULL | 抓取时间 |
| `confidence` | NUMERIC | 0–1 |
| `importance` | TEXT | `low` / `medium` / `high` / `critical` |
| `direction` | TEXT | `support` / `oppose` / `neutral`（相对其 linked assumption；未链接时 `neutral`） |
| `raw_reference` | JSONB | excerpt、body hash、`ref_table`/`ref_id`（可指向 `earnings_reports` 等现表） |
| `produced_by` | TEXT | agent 名；不得为 `pm_judge` 伪造证据 |
| `task_id` | TEXT | FK → research_tasks，可空 |

CHECK：`source` 与 `source_time` 非空。无来源不得 INSERT。

索引：`(ticker, evidence_type, source_time DESC)`。

#### `research_assumptions`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | TEXT PK | `rasm_` + uuid |
| `ticker` | TEXT NOT NULL |  |
| `category` | TEXT NOT NULL | `demand` / `guidance_delivery` / `margin` / `competition` / `supply` / `valuation` / `execution` / `other` |
| `statement` | TEXT NOT NULL |  |
| `status` | TEXT NOT NULL | `unverified` / `strengthened` / `unchanged` / `weakened` / `broken` |
| `confidence` | NUMERIC | 0–1 |
| `next_verification` | TEXT | 下次验证触发条件 |
| `proposed_by` | TEXT | agent 名或 `template` |
| `status_updated_by` | TEXT | **仅允许 `pm_judge`** 改 status |
| `created_at` / `updated_at` | TIMESTAMPTZ |  |

statement 创建后不改写。若语义变了，新增 Assumption，旧的 `broken` 或保留并链接替代 id（Sprint 4 再加 `superseded_by`）。

#### `research_assumption_links`

Assumption ↔ Evidence 多对多。

| 列 | 类型 |
| --- | --- |
| `assumption_id` | TEXT FK |
| `evidence_id` | TEXT FK |
| `direction` | `support` / `oppose` |
| `linked_at` | TIMESTAMPTZ |
| `linked_by` | TEXT |

PK `(assumption_id, evidence_id, direction)`。跨 ticker 链接由 service 拒绝。

#### `investment_theses`

Append-only 版本表。禁止 UPDATE `core_thesis` 等正文列。

| 列 | 类型 |
| --- | --- |
| `id` | TEXT PK | `ith_` + uuid |
| `ticker` | TEXT |
| `version` | INTEGER | UNIQUE `(ticker, version)` |
| `short_term_view` / `mid_term_view` / `long_term_view` | TEXT |
| `core_thesis` | TEXT |
| `key_assumption_ids` | TEXT[] |
| `key_risks` | JSONB | 字符串列表 |
| `invalidation_conditions` | JSONB |  |
| `monitoring_items` | JSONB | V1 先放 JSON；Sprint 7 再拆表 |
| `confidence` | NUMERIC |  |
| `valuation_id` | TEXT | 可空，写入后回填 |
| `change_summary` | TEXT | 相对上一版改了什么 |
| `actor` | TEXT NOT NULL | 必须 `pm_judge` |
| `created_at` | TIMESTAMPTZ |

#### `valuations`

| 列 | 类型 |
| --- | --- |
| `id` | TEXT PK |
| `ticker` | TEXT |
| `thesis_id` | TEXT FK |
| `thesis_version` | INTEGER |
| `horizon` | TEXT | 如 `2y` / `3y` |
| `bear_case` / `base_case` / `bull_case` | JSONB | 见下 |
| `spot_price` | NUMERIC | 可空；缺则 Honest |
| `created_at` | TIMESTAMPTZ |

每个 case JSON 最小字段：

```json
{
  "revenue": null,
  "earnings": null,
  "eps": null,
  "multiple": null,
  "valuation_method": "pe_exit",
  "target_value": null,
  "key_assumption_ids": [],
  "notes": ""
}
```

缺数保持 `null`，禁止用 0 填。

#### `research_packs`

ResearchPack 是 **可重建快照**，不是第二套行情库。

| 列 | 类型 |
| --- | --- |
| `ticker` | TEXT PK |
| `template_id` | TEXT NOT NULL |
| `company_profile` | JSONB |
| `earnings_history` | JSONB |
| `guidance_history` | JSONB |
| `price_reaction_history` | JSONB |
| `industry_context` | JSONB |
| `competitive_context` | JSONB |
| `major_events` | JSONB |
| `missing_fields` | JSONB | EmptyHonest |
| `source_refs` | JSONB | 指向现表 |
| `updated_at` | TIMESTAMPTZ |

Sprint 1 允许只存空壳 + `missing_fields`；Sprint 2 builder 填实。

#### `research_runs`（Sprint 1 建表，Sprint 2 才写）

一次 workflow 执行的审计日志：`id, ticker, trigger, status, template_id, task_ids, agent_outputs_ref, error, started_at, completed_at`。

### 3.2 不在 Sprint 1 建、但预留

- `issuer_profiles`（CIK、FYE、GICS）→ Sprint 6 去耦合
- `monitoring_items` 独立表 → Sprint 7
- `review_evaluations` → Review/Learning 后续
- `research_templates` 表：V1 用仓库内 JSON，不入库

### 3.3 Python dataclass（`research/types.py`）

与表 1:1，外加统一 Agent I/O（Sprint 2 使用，Sprint 1 先定义空壳以免接口漂移）：

```text
AgentInput:
  ticker, task, research_pack, current_thesis, assumptions, evidence, market_context

AgentOutput:
  findings, new_evidence[], new_assumptions[], supported_assumption_ids[],
  challenged_assumption_ids[], follow_up_tasks[], confidence
```

`new_assumptions` 只能 **提议**。`status` 写入时一律 `unverified`。只有 `pm_judge` 能改 status / 写 Thesis。

---

## 4. 需要新增哪些 service / module

全部放在 `src/stock_pm/research/`。Workflow 只编排，不写行业逻辑。

```
research/
  __init__.py
  types.py              # dataclass + Agent I/O
  errors.py
  store.py              # SQL；不进 queries.py
  service.py            # 不变量：出处、跨 ticker、PM 写权限、版本号
  api.py                # FastAPI 路由，api.py include
  templates/            # Sprint 2：generic_company.json, semiconductor.json, energy.json
  classify.py           # sector/themes → template_id；无 ticker if
  pack_builder.py       # Sprint 2；Sprint 1 可先 read-model 空壳
  tasks.py              # Research Task Engine
  runtime.py            # Agent Runtime：registry + JSON complete
  agents/               # 可插拔；统一 BaseAgent
    base.py
    search_data.py
    fundamental.py
    narrative.py
    quant.py
    industry.py
    risk.py
    pm_judge.py         # 唯一 thesis/assumption-status writer
    review.py           # V1 只记录
  evidence.py           # Evidence Engine：去重、excerpt、升格
  assumptions.py        # Assumption Engine：提议 vs 状态变更
  thesis.py             # Thesis Engine：版本、diff、PM gate
  valuation.py          # Valuation Engine
  workflow.py           # 配置化状态机
  monitor.py            # Sprint 7
  prompts/              # 角色 prompt；禁止公司专属答案
```

### 4.1 模块职责与权限

| 模块 | 可写 | 不可写 |
| --- | --- | --- |
| Search/Data Agent | 原始材料、ResearchPack 字段、Evidence（事实） | Assumption status、Thesis、Valuation |
| Fundamental / Industry / Quant / Narrative / Risk | Evidence、**提议** Assumption、follow-up Task | Thesis、Assumption status、Valuation |
| Assumption Engine | 新建 unverified、挂 link | status（转交 PM） |
| PM / Judge | Assumption status、Thesis 新版本、Valuation、Monitoring JSON | 不得伪造无出处 Evidence |
| Workflow Engine | Task status、research_runs | 业务结论 |
| 新闻/事件 ingest | 最多生成 Task「请抽取 Evidence」 | Thesis |

### 4.2 Workflow 配置（不是代码里的行业 if）

Sprint 2+ 用数据描述，例如：

```yaml
name: new_ticker_research
steps:
  - classify
  - build_pack
  - seed_tasks_from_template
  - run: [search_data, fundamental]
  - run: [industry, quant]
  - run: [risk]
  - run: [pm_judge]
  - seed_monitoring
```

持续监控另一条 workflow：`ingest_info → evidence → match_assumption → maybe_pm_review`。已有 Thesis 时禁止从头重跑整份研究。

### 4.3 Research Template 只提供起始问题

`semiconductor.json` 只含问题轴：revenue growth、end demand、customer capex、design wins、supply capacity、foundry、packaging、HBM、gross margin、inventory、competition。

禁止写入任何公司承诺、GW、客户名、数字。长期承诺必须由 Fundamental Agent 从 transcript/10-K 发现后 **动态** 生成 Assumption + verify task。

分类规则（`classify.py`）：

- `themes` 含 `semis` 或 `sector` 含「半导体」→ `semiconductor`
- `themes` 含 `energy` / `oil_producer` 或 sector 含「能源」→ `energy`
- 否则 `generic_company`

无 `if ticker == ...`。

### 4.4 VoltAgent 怎么用（模板库，不是框架）

参考 [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)，只借职责与协作，不复制其业务清单，不引入其运行时。

| VoltAgent 角色 | Stock-PM 角色 | 借用 | 必须自建 |
| --- | --- | --- | --- |
| search-specialist | Search / Data | 检索、出处、不合成结论 | 绑定 FMP/AV/SEC/Alpaca 工具 |
| research-analyst | Fundamental | 多源、交叉验证、引文 | 财报/Guidance/管理层承诺发现 |
| trend-analyst | Narrative | 聚类、叙事、不做投资结论 | 市场在定价什么 |
| data-analyst（无独立 quant-analyst） | Quant / Market | 量化纪律 | event window、相对指数、tension；禁止输出 `priced_in` |
| competitive-analyst | Industry | 竞争/份额/供应 | 客户 capex、上下游验证 |
| product-manager 的「决策权」隐喻 | PM / Judge | 唯一拍板 | 同时读正反证据 + 旧 Thesis + Valuation |
| workflow-orchestrator | Workflow Engine | 状态、转移、失败补偿 **写成配置** | Python 执行器 |
| multi-agent-coordinator / agent-organizer | Runtime registry | 按 task 委托、互不改对方记忆 | 统一 Agent I/O |
| performance-monitor | Review Agent | 事后指标 | V1 只记，不 fine-tune |
| （无对应） | Risk / Skeptic | — | 主动攻击 Assumption |
| （无对应） | Valuation Engine | — | Bear/Base/Bull 结构 |

Agent 实现约定：

- 一个 Agent = `name` + `system_prompt` + `tools` + `run(input) -> AgentOutput`
- 模型从 `Settings.llm_*` 注入，Agent 内不写死供应商
- 工具失败 → Evidence 缺失 + Task `blocked`，不编事实
- 重要结论无 `raw_reference` → service 丢弃该条

---

## 5. 哪些现有逻辑需要重构

按优先级。Sprint 1 **只做第 1 项的接口预留**，不改日循环行为。

### 5.1 必须做（否则 Brain 会和现网缠死）

1. **`queries.py` 停止膨胀**  
   Brain 读写全部走 `research/store.py`。`Database` 可持有 `ResearchStore`，不要把 20 个 research SQL 方法混进 QueryMixin。

2. **拆 `llm.py` 的「通道」与「复盘 prompt」**  
   Sprint 2：`complete_json(system, user, schema)` 给 Agent Runtime。`complete_review` 保持给 daily review。禁止 Agent 复用 daily SYSTEM_PROMPT。

3. **新 ticker 入口挂钩，但不阻塞现网 backfill**  
   `api._backfill_symbol` 仍拉日线/基本面。Sprint 2 起 `background.add_task(start_research_workflow, symbol)`。Workflow 失败不得让 watchlist 添加失败。

4. **命名隔离**  
   API 用 `/api/research/{symbol}/thesis`。页面文案用「投资命题 / 研究」。不要把 desk 的「当前判断」改名为 Thesis，避免两套对象互相覆盖。

5. **新闻不得改 Brain Thesis**  
   现有 `trusted_events` → desk 判断链保持。Brain 监控路径：新闻 → Evidence → 匹配 Assumption → 是否提请 PM。没有 PM 步骤就没有新 Thesis 版本。

### 5.2 应改但可晚于 POC（Sprint 6）

1. `WATCH_CIKS` / `FISCAL_YEAR_END_MONTH` → `issuer_profiles` 数据。未知 issuer：Honest 降级，不发明 CIK/FYE。
2. `ENTITY_ALIASES` / `SEMIS_MARKERS` / 新闻关键词里的公司名 → 配置或 issuer 别名，避免新票映射失败。
3. `fundamentals_thesis_view` 降级为 ResearchPack 的一个只读摘要字段，不再叫 thesis。

### 5.3 不要改

- 首页 `/` IA（用户明确：暂时不要重做首页）
- `decision/` Golden Tests A–AM
- Prediction 状态机
- 无持仓 / EmptyHonest / 主路径去系统词

### 5.4 个股页演进（Sprint 7，现在只定接口）

在 `/stock/{symbol}` **现有五段之下或旁**增加「研究 / 投资命题」区块，数据来自 `/api/research/{symbol}/*`：

- 顶栏：short / mid / long、confidence、base target、upside/downside、latest thesis change
- 区块：Core Thesis、Key Assumptions、Valuation、Risks、Monitoring、Evidence、Thesis History
- Assumption 展开：结论、supporting / counter evidence、confidence、next verification

材料折叠 C 保留。日判断五段保留。

---

## 6. 目标架构（与现网共存）

```
New ticker (watchlist)
  → classify (template_id)
  → build ResearchPack (from existing tables + transcripts)
  → seed ResearchTasks from template questions
  → Agent Runtime (unified I/O)
       Search/Data → Evidence only
       Fundamental → Evidence + proposed Assumptions + follow-up Tasks
       Industry / Quant / Risk → Evidence + support/challenge
  → Assumption Engine (link; status stays unverified)
  → PM/Judge (only writer of status + Thesis vN + Valuation)
  → Monitoring items
  → later: incremental evidence → maybe Thesis vN+1
```

日循环（environment / tape / prediction / desk pack）继续跑。Brain 不订阅「今日重点关注」去重写长期命题。

### 6.1 AVGO POC 怎么测（数据，不是代码）

- 测试夹具：`tests/fixtures/research/` 放脱敏/冻结的财报与 transcript 片段。
- 断言：系统从材料中抽出 **某条** 管理层长期承诺类 Assumption，并生成 verify task 与正反证据槽。
- 测试代码 **可以** 出现 `AVGO` 字符串（它是样本 ticker）。
- `src/stock_pm/research/` **生产代码与 prompt** 不得出现 `30GW`、`Broadcom` 专属规则、`if ticker == "AVGO"`。
- 复用测试：同一 workflow 换 NVDA / XOM / COHR 夹具，不改 `workflow.py`。

---

## 7. Sprint 1 文件级开发计划

范围：表 + dataclass + store/service 不变量 + 只读写 API + 防耦合测试。  
不做：Agent、Workflow 执行、Template 运行、前端、真实 LLM。

### 7.1 新增文件

| 文件 | 职责 |
| --- | --- |
| `docs/BRAIN_V1_DESIGN.md` | 本设计（已落地） |
| `src/stock_pm/sql/migrations/0004_research_brain.sql` | 第 3 节全部表 + index + check |
| `src/stock_pm/research/__init__.py` | 导出类型与 service 入口 |
| `src/stock_pm/research/types.py` | Task/Evidence/Assumption/Thesis/Valuation/Pack/Agent I/O |
| `src/stock_pm/research/errors.py` | `ProvenanceError` `PermissionError` `VersionConflict` `CrossTickerError` |
| `src/stock_pm/research/store.py` | 纯 SQL CRUD；幂等 insert |
| `src/stock_pm/research/service.py` | 不变量与事务 |
| `src/stock_pm/research/api.py` | `APIRouter(prefix="/api/research")` |
| `tests/test_research_types.py` | 构造校验：缺 source 失败等 |
| `tests/test_research_store.py` | Postgres 可 skip；版本只增不改 |
| `tests/test_research_api.py` | FastAPI TestClient |
| `tests/test_research_invariants.py` | PM gate、跨 ticker、新闻不能写 thesis |
| `tests/test_research_no_ticker_coupling.py` | 扫描 `research/` 禁止 `if ticker ==` / 禁止 prompt 含样本承诺 |

### 7.2 修改文件（小、可审）

| 文件 | 改什么 |
| --- | --- |
| `src/stock_pm/api.py` | `app.include_router(research_router)`；不改 desk 路由 |
| `src/stock_pm/database.py` | 可选：`self.research = ResearchStore(self)` |
| `docs/README.md` | 索引本设计 |
| `pyproject.toml` | 仅当需要 `package-data` 纳入 `research/templates`（Sprint 1 可不动） |

**禁止改：** `decision/`、`pack/stock_page.py`、`static/stock.html`、`llm.py` SYSTEM_PROMPT、`impact.py`、watchlist 种子。

### 7.3 Sprint 1 API

一律 EmptyHonest：缺对象返回结构化空态，不 500 编造。

```
GET    /api/research/{symbol}/tasks
POST   /api/research/{symbol}/tasks
GET    /api/research/{symbol}/tasks/{id}

GET    /api/research/{symbol}/evidence
POST   /api/research/{symbol}/evidence

GET    /api/research/{symbol}/assumptions
POST   /api/research/{symbol}/assumptions          # 只创建 unverified
POST   /api/research/{symbol}/assumptions/{id}/links
POST   /api/research/{symbol}/assumptions/{id}/status   # actor 必须 pm_judge

GET    /api/research/{symbol}/thesis                 # 最新版或 empty
GET    /api/research/{symbol}/thesis/history
POST   /api/research/{symbol}/thesis                 # actor=pm_judge；version=max+1

GET    /api/research/{symbol}/valuation
POST   /api/research/{symbol}/valuation              # 绑定 thesis_id

GET    /api/research/{symbol}/pack                   # Sprint 1：表内快照或 missing
```

`POST thesis` / `POST assumption status` 若 `actor != pm_judge` → 403。这是为后续 Agent 预埋墙，不是给用户做确认门槛。

### 7.4 Service 不变量（Sprint 1 测试必须锁死）

1. Evidence：`source`、`source_time`、`retrieved_at`、`fact` 缺一不可。
2. 链接 Evidence 与 Assumption 必须同 ticker。
3. Assumption `POST` 强制 `status=unverified`；客户端传入的 status 忽略。
4. 只有 `actor=pm_judge` 能改 Assumption status 或插入 Thesis。
5. Thesis `UPDATE` 不存在；同 ticker 新插入 `version = coalesce(max,0)+1`。
6. Thesis 的 `key_assumption_ids` 必须存在且同 ticker。
7. Valuation 的每个 case 允许字段全 null，但不允许缺 `bear/base/bull` 三个键。
8. 不存在从 `news_articles` 或 `trusted_events` 直接写 `investment_theses` 的 store 方法。
9. `research/` 源码与未来 prompt 目录不得出现 `30GW`、`if symbol == "AVGO"` 一类分支。

### 7.5 Sprint 1 验收

- `python -m stock_pm.migrate` 后 `0004_research_brain` 在 `schema_migrations`。
- `pytest tests/test_research_*.py -q` 过。
- 现有 `tests/test_decision_kernel.py`、`tests/test_pack_desk.py`、desk API 测试无回归。
- 用任意 ticker（测试里可用 `FAKE` 或自选里已有符号）走完：建 task → 建 evidence → 建 assumption → link →（非 pm 写 thesis 失败）→ pm 写 thesis v1 → 再写 v2 → history 两条且 v1 正文未变。

### 7.6 建议实现顺序（仍在 Sprint 1 内）

1. 迁移 SQL + 本地 migrate
2. `types.py` / `errors.py`
3. `store.py` + postgres 测试
4. `service.py` 不变量
5. `api.py` + TestClient
6. coupling 扫描测试
7. 文档索引

---

## 8. 后续 Sprint 只定边界（不在本次开发）

| Sprint | 交付 | 明确不做 |
| --- | --- | --- |
| 2 | Pack builder、Runtime、Search、Fundamental；template JSON×3；watchlist 挂钩 workflow | 不写行业数字进 template；不改 desk |
| 3 | Assumption Engine 实装、Industry、Quant、Risk | Quant 不输出 `priced_in` |
| 4 | PM/Judge、Thesis 版本 diff、Valuation | 其他 Agent 不得调 thesis store |
| 5 | AVGO Golden Case 夹具驱动，调 prompt/工具 | 不把 30GW 写进代码 |
| 6 | NVDA/XOM/COHR 复用；issuer_profiles 替换 CIK/FYE 硬编码 | 不改 `workflow.py` 主逻辑 |
| 7 | 个股研究区 UI + 增量 Monitoring | 不重做首页；Narrative/Review 可继续 stub |

---

## 9. 开发约束（实施时对照）

- 禁止 ticker-specific if/else（测试夹具除外）
- 禁止 Prompt 写 AVGO/NVDA 专属答案
- 禁止无出处的重要结论入库
- 禁止新闻直接修改 Thesis
- 禁止单个非 PM Agent 修改 Thesis 或 Assumption status
- Thesis 必须版本化（只追加）
- Assumption 必须能新增 / 强化 / 削弱 / 失效
- Evidence 必须保留来源和时间
- Agent 必须走统一 I/O
- Workflow 必须配置化；新 ticker 只加数据/模板/issuer 行
- 不引入 VoltAgent 框架依赖
- 不破坏现网日循环与 `/` IA

最终目标不变：Stock-PM 的研究核心是 Evidence → Assumption → Thesis → Valuation → Monitoring → Review。AVGO 只是第一个 Golden Case。
