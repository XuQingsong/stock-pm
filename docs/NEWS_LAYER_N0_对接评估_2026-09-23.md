# 新闻与信息层 N0：stock-pm 对接评估（2026-09-23）

对应交接：`qingsong-xu/investment-cognition` 分支 `cursor/stock-pm-design-b9f0` 的 `docs/08-news-information-layer.md`、`config/news_taxonomy.yaml`、`schema/news.sql`。

## 0. 前提与限制

- 本次在 stock-pm 云端环境里**读不到** investment-cognition（Origin 私有仓库，CLI 未授权；GitHub 上无同名仓库）。
- 因此 `RawArticle` 契约（docs/08 §3.1）与冗余要求（§3.2）按交接摘要重建：带时区的发布时间、`external_id`、`vendor_tickers`、SEC 表单与 Item、其他一手源原生元数据。字段名如与 docs/08 不同，以 docs/08 为准，改 `src/stock_pm/news/contract.py` 即可。
- `schema/news.sql` 未见原文，第 5 节只能给出**并入规则和需要逐项核对的清单**，不直接改表。
- 标注「待核实」的地方需要用实盘样本确认，不编造。

## 1. 现有美股数据源清单

调度（`deploy/`）：`stock-pm-intraday.timer` 每 5 分钟跑 Alpaca 日内行情；`stock-pm-daily.timer` 每天 **23:30 UTC**（美东 19:30 EDT / 18:30 EST）串行跑其余全部任务，其中包括新闻、SEC、美联储和 EIA。

| 类别 | 数据源 / 模块 | 端点 | 保留字段 | 频率 | 时区处理 | 写入 |
| --- | --- | --- | --- | --- | --- | --- |
| 日线 | Alpaca SIP，`alpaca.py`、`bars.py` | `data.alpaca.markets/v2/stocks/bars`，1Day，split-adjusted | OHLCV、`source/feed/as_of/fetched_at` | 每日 | bar_time 为 UTC；`bars.py` 按 America/New_York 16:00 判断已完成交易日 | `price_bars` |
| 快照 / 日内 | Alpaca（`ALPACA_DATA_FEED`，默认 iex） | snapshots、1Min bars、trades | last/bid/ask/OHLC/prior_close、大单 | 每 5 分钟；`market_is_collectible` 限定 ET 9:45–16:30；1Min 数据延迟 16 分钟 | 窗口写死，只判断周一到周五，**不看节假日和提前收盘**，盘前盘后不采集 | `market_snapshots`、`intraday_segments`、`large_trades` |
| 期权 | Alpaca options（indicative） | option chain snapshot | 按行权价的 call/put 量、OI、IV | 每日 / 日内 | UTC captured_at | `option_wall_snapshots` |
| 期权统计 | Cboe，`cboe.py` | `cboe.com/us/options/market_statistics/daily` | 总量、P/C | 每日 | trade_date | `cboe_option_stats` |
| 估值 / 财报 | FMP（有 key）或 Nasdaq 非官方 API，`providers.py`、`fundamentals.py` | FMP `stable/profile, ratios-ttm, key-metrics-ttm, income-statement, earnings`；Nasdaq `quote/*/summary, eps, earnings-surprise` | 见 `fundamentals_snapshots`、`earnings_reports` | 每日 | report_date 仅日期；`report_timing` 恒为 `unknown`（盘前/盘后缺失） | 同左 |
| 财报（事件） | Alpha Vantage EARNINGS 等，`events/av_earnings.py` | `alphavantage.co/query` + SEC 回链 | EPS 实际/预期、期间 | 每日，按预算轮换（`STOCK_PM_EARNINGS_BUDGET`） | 日期 | `trusted_events` |
| **个股新闻** | **Nasdaq 非官方 API**，`fundamentals._news` | `api.nasdaq.com/api/news/topic/articlebysymbol` | headline、summary、publisher、url、`created`（**只有日期**） | 每日（随 fundamentals 任务） | 见第 2 节缺陷 1 | `news_articles`（`UNIQUE(symbol,url)`） |
| 新闻（研究检索） | Alpha Vantage NEWS_SENTIMENT，`external/clients.alphavantage_news` | `function=NEWS_SENTIMENT&tickers=` | title、url、summary、source、`time_published` | 研究任务按需 | 截成日期（缺陷 2） | 研究库 `research_*`，不进 `news_articles` |
| 发现检索 | Tavily / Exa / DuckDuckGo HTML / Google CSE（未启用） | 各自 API | title、url、正文片段、日期 | 按需、`SearchBudget` 限额 | 日期；页面 meta 回补也只给日期 | 研究库；只作线索 |
| SEC 8-K | `events/live.SecEdgarProvider` | `browse-edgar?action=getcurrent&type=8-K&output=atom`，外加 4 家公司的 `getcompany` Atom | title、url、`updated`、summary、AccNo；Item 从 index 页解析 | 每日（events.job） | Atom `updated` 自带偏移，转成 UTC | `trusted_events`、`trusted_event_sources` |
| SEC 基本资料 | `research/live_fetch.py` | `sec.gov/files/company_tickers.json`、`data.sec.gov/submissions`、`companyfacts` | CIK 映射、filings 列表、XBRL | 研究任务按需 | 日期 | `research_*`、`issuer_profiles` |
| 美联储 | `events/live.FederalReserveProvider` | `federalreserve.gov/feeds/press_all.xml`、`press_monetary.xml` | title、link、pubDate | 每日 | RFC 2822 自带时区，转成 UTC | `trusted_events` |
| 能源 | `events/live.EiaPressProvider` | `eia.gov/rss/press_rss.xml` | 同上 | 每日 | 同上（`EST` 等缩写可解析） | `trusted_events` |
| 宏观数据 | FRED（有 key 走 JSON，没有走 `fredgraph.csv`），`series.py`、`macro.py`、`nfp.py` | CPIAUCSL、PAYEMS、DGS2、VIXCLS、DCOILWTICO、DTWEXBGS | observed_at / as_of / fetched_at 分开存 | 每日 | as_of 是统计期，不作观测时钟（见 `data-coverage-matrix.md`） | `macro_events` 等 |
| 黄金 | Alpha Vantage GOLD_SILVER_HISTORY，`gold.py` | — | XAU 日线 | 每日 | 日期 | 缓存 + 健康检查 |
| 经济日历 | **手工 JSON** `data/macro_calendar.json` | — | event_type、event_time（UTC）、consensus、prior、`confirmed` | 手工维护 | UTC；CPI、FOMC 等标 `confirmed:false`（按惯例估计） | `macro_events` |
| 分析师评级 | **无** | — | 只有 Nasdaq summary 的 `OneYrTarget` 一个数 | — | — | `fundamentals_snapshots.analyst_target_price` |

补充：
- Alpaca 的 key 已在用，但**没有接 Alpaca News API**。`brain/audit.py` 里写的「Alpaca/news ingest」与实际不符，`news_articles` 目前唯一的写入方是 Nasdaq。
- `news_articles.sentiment` 和 `themes` 来自 `impact.py` 的关键词规则，不是供应商字段。

## 2. 按 RawArticle 契约逐个对接

N0 的适配器（`src/stock_pm/news/adapters.py`）都是纯函数：输入是现有客户端已经拿到的原始条目，不新增任何 HTTP 调用。`RawArticle.missing_fields()` 会逐条列出缺口。

| 契约字段 | Nasdaq 新闻 | AV NEWS_SENTIMENT | SEC 8-K Atom | Fed / EIA RSS | Tavily / Exa |
| --- | --- | --- | --- | --- | --- |
| 发布时间（带时区） | ❌ 只有日期 → `precision=day`，`session=unknown` | ⚠️ 精确到分/秒，但**不带时区**，按 UTC 假定（`tz_basis=assumed:UTC`，待核实） | ✅ `updated` 自带偏移（待核实：它是否等于 acceptance time） | ✅ RFC 2822 带时区 | ❌ 只有日期 |
| `external_id` | ⚠️ 行里有 `id` 时用（待核实：该接口是否总返回 id） | ❌ 无 → 退回 canonical URL | ✅ accession number | ⚠️ 只有 URL（RSS guid 没保留到 `EventDocument`） | Exa 有 `id`（`metadata.exa_id`）；Tavily 没有 |
| `vendor_tickers` | ⚠️ `primarysymbol`、`related_symbols`（此前入库时丢掉了） | ✅ `ticker_sentiment[].ticker` 及 relevance（此前丢掉了） | ⚠️ 只覆盖写死的 9 个 CIK（`WATCHLIST_CIKS`），其余标 `UNMAPPED_FILER` | 不适用（市场级） | 只有查询时用的 ticker |
| SEC 表单 / Item | — | — | ✅ 表单来自标题（`8-K`、`8-K/A`）；Item 来自 index 页，拿不到时为空并标缺 | — | — |
| publisher | ✅ | ✅ `source` | ✅ | ✅ | 域名 |
| 正文 | 摘要 | 摘要 | index 页摘要；主文档另行抓取（`bodies.py`） | 摘要 / 官方页 | 片段；部分有全文 |

现有代码的缺陷（按影响大小排序）：

1. **Nasdaq 日期被当作 UTC 零点**（本 PR 已修）。`news_on_date` 按美东日期取数，`"Sep 22, 2026"` 会落到 9/21，复盘「昨盘」的消息整体错一天。现在改为按美东 00:00 锚定。已经入库的旧行要等下一次 upsert 才会更正。
2. `external/clients.parse_published` 把所有时间截成 `YYYY-MM-DD`，AV 的分钟精度因此丢失，也就无法判断盘前还是盘后。N0 的 `normalize_published` 会保留时刻、精度和时区依据。研究链路要不要切过来，放到 N1 统一处理，以免改变现有研究判定。
3. `news_articles.raw_data` 存的是加工后的行，供应商原始行丢了。本 PR 起在 `vendor_row` 里保留原始行，但历史数据无法补回。
4. AV 的 `ticker_sentiment` 和 `topics` 被丢弃。适配器现在保留为 `vendor_ticker_meta` 和 `vendor_topics`。
5. SEC 的 accession 和 CIK 混在 `EventDocument.entities` 列表里，没有独立字段；适配器负责拆出来。CIK→ticker 映射是写死的，应改用已经在用的 `company_tickers.json`（`research/live_fetch.py`）。
6. `events/dedupe._published_day` 取的是 UTC 日期，美东盘后的公告会被算到下一天。聚类窗口只有 45 天，影响有限，但事件 ID 里用了这个日期。
7. `earnings_reports.report_timing` 恒为 `unknown`。不知道财报是盘前还是盘后发布，价格反应就对不上交易日。
8. `events/earnings.documents_from_evidence` 遇到只有日期的 AV 财报，会补成 `T16:00:00+00:00`，即美东中午 12 点。这个时刻是编出来的，应改成标注 `precision=day`。
9. `events/policy.classify_source` 给二级媒体来源（路透、彭博、美联社）的 `fact_or_opinion` 是 `"reported"`，但 `trusted_event_sources` 的 CHECK 只允许 `'fact','opinion'`。目前的实时源都是官方源，所以还没触发；一旦媒体来源写库，整批写入会失败，事件任务被标为 `degraded`。修法是在迁移里放宽这个 CHECK，建议和 news.sql 一起并入。
10. 交易日判断有两套：`calendar.is_trading_day` 会看 NYSE 节假日，而 `bars.is_us_trading_day`、`alpaca.market_is_collectible` 和 `flow` 的取日逻辑只判断周一到周五。节假日当天，日内采集会空跑；「最近完成的交易日」也会指向休市日。
11. 外部检索结果（Tavily、Exa、AV、DuckDuckGo）只在内存里用，**不入库**。只有抽取出的事实会写进 `research_evidence`，这与 docs/08「外部检索结果先入库、处理后再返回」的要求不符。
12. Cboe 抓取失败时直接抛 `RuntimeError`，没有状态记录；`job_runs` 只由 tape、environment、prediction、review 这几个任务写入，数据采集任务都不写。

## 3. 冗余缺口（对照 §3.2 的要求）

| 类别 | 现有来源 | 备用源 | 缺口与建议 |
| --- | --- | --- | --- |
| 个股新闻（带时刻） | 无。Nasdaq 只有日期，AV 只用在研究链路 | 无 | **最大缺口**。建议：主源用 Alpaca News API（key 已有；有 `id`、UTC 的 `created_at/updated_at`、`symbols`），AV NEWS_SENTIMENT 作备用源，Nasdaq 降级为只补日期 |
| 公司新闻稿 | FMP `press-releases`（`research/live_fetch.py`，只在研究回填时用，落 `research_source_documents`） | 8-K Item 7.01 / 8.01 的附件 EX-99.1 | 可以接入新闻层作为一手源；时间精度待核实 |
| SEC 8-K | current Atom 加 4 家公司 Atom | 无 | 备用源用 `data.sec.gov/submissions/CIK*.json`（已在研究链路里用）按自选股逐个对账；两者按 accession 对齐 |
| 财报发布时刻 | FMP / Nasdaq / AV 只有日期 | — | 缺盘前/盘后标记。建议用 AV `EARNINGS_CALENDAR` 或 FMP earnings-calendar 的时段字段，并用 8-K Item 2.02 的时间戳交叉验证 |
| 美联储 | Fed RSS | 无 | FOMC 日程仍是手工估计（`confirmed:false`）。建议抓 federalreserve.gov 的 FOMC calendar 页，按固定日程生成事件键 |
| 宏观数据发布 | FRED 数值 | 无（BLS RSS 返回 403） | FRED 的数据只能在发布之后拿到；缺官方发布日程：需要 BLS、BEA 日程表，或者一个付费经济日历 |
| 经济日历 / 一致预期 | 手工 JSON | 无 | consensus 大多为空。没有合法的免费源；数据不足就标缺失，不要去填 |
| 分析师评级 | 无 | 无 | 整个类别空缺。FMP `grades` 等接口要看套餐（待核实）；在接入之前，taxonomy 里的评级类只能依靠新闻标题规则 |
| 能源 | EIA RSS | FRED WTI | 基本够用 |

## 4. N0 落地方式（按 stock-pm 的现有结构调整）

本 PR 已完成（`src/stock_pm/news/`，未接入任何任务或页面，不改变现网行为）：

- `timeutil.py`：把发布时间统一成 UTC 时刻，并附带 `precision`（秒/分/日）和 `tz_basis`（显式、假定时区、仅日期）；拒绝「3 hours ago」这类相对时间。交易时段分为 premarket 04:00、regular 09:30–16:00（提前收盘日到 13:00）、after_hours 到 20:00（提前收盘日到 17:00）、overnight、closed。`reaction_date` 给出第一个能对这条信息定价的常规交易日。
- `calendar.is_early_close`：NYSE 提前收盘日，包括 7/3、感恩节次日、平安夜（后两个仅周一到周四适用）。
- `contract.py`：`RawArticle` 及 `missing_fields()`。
- `adapters.py`：Nasdaq、AV、SEC、Fed/EIA、Tavily/Exa 五类适配器。
- `dedupe.py`：文章级去重，依次按 accession、厂商 id、canonical URL、同标题 36 小时内转载判断。官方源和过短的标题不按标题合并。保留顺序是官方 > 厂商 feed > 聚合 > 检索，同级再比较时区是否显式、精度、发布时间先后。被合并的来源记在 `also_seen_in`。
- `health.py`：每个源定义新鲜度目标和活跃窗口；状态分为 `ok / idle / degraded / silent / stale / down / not_configured`。「silent」的判定：抓取成功，但在活跃窗口里最新一条的发布时间停止前进。状态存进现有的 `event_job_cursors`，provider 名用 `news:<source>`，不新建表。

N0 的下一步（按顺序）：

1. **把调度改成日内运行**。现在新闻和 SEC 每天只跑一次（23:30 UTC），`health.py` 里 SEC 30 分钟、AV 3 小时的目标都会被判为 stale，这是事实，不是误报。建议新增一个 `stock-pm-news.timer`，在交易日 04:00–20:00 ET 每 5 分钟运行一个独立的 `stock_pm.news.job`。
2. daily service 前半段是 `&&` 串联，`fundamentals` 失败时 macro、cboe、events 会一起被跳过，而且没有任何报错。应改为和后半段一样用 `;`，并让每一步都写 `job_runs`。
3. 新增 Alpaca News 适配器和抓取（契约最完整）；AV 作备用源。两者都走 `fetch.json_get`，复用它的缓存和退避。
4. 抓取时把 `normalize_published` 的结果和 `vendor_row` 一起落库（落哪张表见第 5 节）。`news_articles` 在过渡期内双写。
5. 每日对账：按自选股比对 SEC submissions 和 Atom 的 accession，比对 Alpaca 和 AV 同一 ticker 的条数。偏差写入 `severity_alerts`（只追加）。

## 5. `schema/news.sql` 并入评估

stock-pm 的约束：

- 迁移文件放在 `src/stock_pm/sql/migrations/NNNN_*.sql`，目前编号到 `0026`，新文件从 **`0027_news_layer.sql`** 开始。`Database.initialize()` 每次启动都会执行 `apply_migrations`；文件 checksum 一变就**重新执行整个文件**，所以 news.sql 必须全部可重跑（`IF NOT EXISTS`、`ADD COLUMN IF NOT EXISTS`、`ON CONFLICT`），不能有裸的 `CREATE TYPE`、裸的 `INSERT`，也不能在同一个文件里删表后再重建。
- 生产数据库是 `postgres:17-alpine`（docker-compose）。news.sql 在 PG16 上验证过，语法上向前兼容。**该镜像没有 pgvector**：如果 news.sql 用了 `vector` 类型或 `CREATE EXTENSION vector`，要么把镜像换成 `pgvector/pgvector:pg17`（需要评估现网数据卷迁移），要么先把向量存成 `real[]`，在应用层计算相似度，N1 再上索引。`pg_trgm`、`tsvector` 在官方镜像里就有。
- 主键风格：业务表多用 `TEXT` 主键加前缀哈希（`evt_…`、`xdoc_…`），时间一律 `TIMESTAMPTZ`，扩展字段用 `JSONB NOT NULL DEFAULT '{}'`。历史表只追加（environment、tape、prediction 都是这样）。

与现有表的对应关系：

| news.sql 里的概念（按交接摘要） | stock-pm 现有表 | 建议 |
| --- | --- | --- |
| 原始文章（RawArticle） | `news_articles`：按 `(symbol,url)` 唯一，同一篇文章按 ticker 复制多行，没有 external_id 和精度字段 | 新建文章表，每篇文章存一行，ticker 放关联表。`news_articles` 保留为兼容视图或者过渡期双写；读方有 `queries.py` 4 处、`research/sources.py`、`research/backfill.py`、`research/pack_builder.py`、`brain/news.py` |
| 事件 / Story | `trusted_events`、`trusted_event_sources`、`trusted_event_claims`：只收官方事实、带分级 | 不合并。`trusted_events` 继续作为官方事实层；story 用外键或 JSONB 引用 `event_id`。确定性事件键（如 `earnings:NVDA:2026Q3`）可以作为 `dedupe_group` 的新取值 |
| 数据源健康 / 游标 | `event_job_cursors`（provider 主键，含 etag、last_modified、cursor_json）、`job_runs` | 优先复用；如果 news.sql 自带 source_health 表，就只保留一套，另一套改成视图 |
| 经济日历 | `macro_events`（主键 `(event_type,event_time)`） | 核对 news.sql 的日历表能否直接替代；手工 JSON 迁入后要保留 `confirmed` 标记 |
| 价格反应 / 覆盖缺口 | `price_bars`、`intraday_segments`、`market_events` | 反应表只读价格，不回写重要度（与 docs/08 一致）；「异动但无事件」可以复用 `market_events.event_type='coverage_gap'`，或者使用 news.sql 的专表 |
| 分类 / taxonomy | 无（`impact.tag_news` 是关键词规则） | `config/news_taxonomy.yaml` 放 `src/stock_pm/news/`，并加入 `pyproject` 的 package-data |

拿到 news.sql 之后逐项核对：扩展（vector / trgm）、枚举和 CHECK 与上表是否冲突、是否全部可重跑、外键是否指向已有表、索引是否覆盖 `(ticker, published_at DESC)` 和 `(reaction_date)`。核对完再落 `0027`。
