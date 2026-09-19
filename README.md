# stock-pm

面向价值投资的股票分析与仓位管理数据服务。

```text
Alpaca 延迟行情 -> 云端定时采集 -> PostgreSQL -> FastAPI / 分析程序
```

这套方案不依赖 TWS，也不要求 Codex 一直打开。自选名单存于数据库
`watchlist` 表，可在 `/settings` 页面动态增删（初始种子为
`MU, INTC, AAPL, GOOGL, NVDA, SKHY, NOK, AVGO, QQQ`）。

## 页面结构

| 页面 | 范围 | 内容 |
| --- | --- | --- |
| `/market` 市场总览 | V1 第一阶段 | 已落盘定价主轴（主导/次主导/辅助分条）· 主导变量卡片 · 触发事件另层；只读 `GET /api/market/overview` |
| `/` 总览 | 全部自选 | 市场主事件（依据默认折叠）、「今日重点关注」三档白话、其余事件轮播、未映射头条折叠 |
| `/stock/{symbol}` 个股 | 单标的 | 五段：当前判断 · 昨→今/中期 · 三个驱动 · 风险反证 · 观察/失效；材料与诊断默认折叠 |
| `/review` 复盘 | 全部自选 | 正式预测（计入命中）与观察分家；错误归因/学习；不倾倒全市场 |
| `/events` 事件中心 | 诊断 | 可信事件原文与覆盖（主路径不抢） |
| `/replay` 盘面回放 | 单标的（最多两个对比） | 美股常规时段 1 分钟 K 线 + 量价分析 |
| `/settings` 设置 | 配置 | 自选新增（Alpaca 校验+自动回填）与停用 |

现网部署见 [`docs/DEPLOY_43.md`](docs/DEPLOY_43.md)（`http://43.166.2.31/`）。

## 功能

- 自选名单入库，新增标的自动经 Alpaca 校验并后台回填一年日线与基本面
- 大额成交两步采集：由分钟K线定位放量分钟，再拉取 Alpaca SIP 逐笔，
  保留单笔金额 ≥ `LARGE_TRADE_NOTIONAL`（默认 $200,000）的成交，
  tick rule 推断买卖方向（明确标注为推断）
- 日内摆动分段（ZigZag）：每段输出涨跌幅、量相对日均倍数、VWAP 位置、
  大单净额与笔数
- 宏观事件日历（`data/macro_calendar.json` 手工维护 + FRED 自动补实际值）
  与规则化板块影响映射（如：非农弱于预期 → 降息预期升温 → 利多高估值成长/黄金）
- 新闻按主题打标（利率、半导体/AI、消费电子等），旧情绪分降级为个股页参考项
- 计算 MA5 / MA20 / MA50 / MA200、RSI14、年化波动率、量比和阶段涨跌幅
- 展示最近到期日期权墙、近一年财报 EPS 与前后股价反应、估值指标
- PostgreSQL 时间序列索引与幂等写入；保留原始数据源 JSON

## PostgreSQL

PostgreSQL is the real persistence store. Live overlays must not hide a down
database: `/health` reports `status=error` and `database=unavailable` when
Postgres is unreachable.

Local/cloud start (never commit real passwords):

```bash
# 1) Copy examples only. Put real credentials in gitignored .env or .env.server.
cp .env.example .env
# 2) Start Postgres (Docker if present, otherwise a local cluster).
bash scripts/start-postgres.sh
# 3) Apply and verify every migration.
python -m stock_pm.migrate
# 4) Optional: persist live NVDA bars, FMP earnings, and FRED NFP.
python -m stock_pm.persist_live --symbol NVDA
# 5) Optional one-shot: map existing research_* into empty brain_* (no GLM, no schedule).
python -m stock_pm.brain.materialize_from_research --tickers AVGO,LITE
```

`DATABASE_URL` is read from the process environment (and gitignored `.env` via
python-dotenv). Logs only print a redacted DSN (`user:***@host/db`). The
documented local-dev default is:

```text
DATABASE_URL=postgresql://stock_pm:stock_pm_dev@localhost:5432/stock_pm
```

Docker Compose still requires `POSTGRES_PASSWORD` from `.env.server` (also
gitignored). Windows install path remains `D:\Program Files\PostgreSQL\17`.

```powershell
docker compose up -d postgres
```

## 安装与启动

```powershell
cd D:\workspace\stock-pm
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
stock-pm
```

打开 `http://127.0.0.1:8000/` 查看仪表盘，或打开 `http://127.0.0.1:8000/docs` 查看接口文档。

接口按范围分组：

- 决策系统主路径：`GET /api/desk/overview`、`GET /api/desk/stock/{symbol}`、`GET /api/desk/review`（冻结 IA，真数据，缺则诚实降级）
- 管理：`GET/POST /api/watchlist`、`DELETE /api/watchlist/{symbol}`、`GET /api/sync/status`、`GET /health`
- 全列表：`/api/market/snapshot | signals | technicals | events | news | earnings/recent | impact`
- 单标的：`/api/stock/{symbol}/chart?interval=`、`earnings/summary`、`valuation/history`、`volume-profile`、`capital-flow`，以及既有的 `intraday | segments | large-trades | overview | fundamentals | earnings | sentiment | options | news | reviews | history`
- 环境：`GET /api/environment`、`GET /api/environment?symbol=`、`GET /api/environment/history?symbol=`（只追加，不覆盖旧半句）
- 昨盘：`GET /api/stock/{symbol}/tape`、`GET /api/stock/{symbol}/tape/history`（TapeAnalysis，只追加）
- 复盘笔记：`GET /api/stock/{symbol}/review-notes`（ReviewNote 白话总结/解释，只追加）
- 预测：`GET /api/stock/{symbol}/prediction`、`/predictions`、`/prediction/checks`；`POST /api/stock/{symbol}/predictions/{id}/supersede`（改口留痕）
- 回放：`/api/replay/day?date=`、`/api/replay/range?symbol=&from=&to=`
- 宏观：`GET/POST /api/macro/events`（POST 用于补录实际值或 FOMC 结果）

持仓/成交/账户接口已随 IBKR 移除下线，表结构保留待接入新券商。

## Alpaca 数据同步

股票与期权数据直接由云服务器调用 Alpaca API，无需打开 TWS 或保持
Codex 在线。免费版股票完整市场分钟线按约 15 分钟延迟保存，期权使用
indicative 数据。手动运行示例：

```powershell
stock-pm-alpaca --mode intraday
stock-pm-alpaca --mode daily
```

同步载荷已加入 `.gitignore`。`sync_runs` 会记录每次同步时间、状态和写入数量。

## 基本面与财报同步

在 `.env` 中配置 `FMP_API_KEY` 后，`stock-pm-fundamentals` 使用 Financial Modeling Prep 拉取估值 TTM 与财报实际值；未配置时回退到 Nasdaq 免费接口（仅 EPS 一致预期）。

```powershell
stock-pm-fundamentals
```

FMP 可提供：公司资料、PE/PB/PS、毛利率等 TTM 比率、季度利润表净利润、以及已公布的 EPS/营收实际值与预期。当前套餐不要传 `limit`（该查询参数会 402）。`analyst-estimates` 以及部分标的的部分接口也可能 402，因此**净利润预期、分析师目标价、Forward PE 一律留空**，页面显示「数据源暂未提供」，不会用估算值填补。未来财报行若尚无 actual 也会跳过。新闻仍来自 Nasdaq。

ETF（例如 QQQ）或供应商未覆盖的字段同样显示为空。

云服务器使用 `deploy/stock-pm-daily.timer` 每天 23:30 UTC（北京时间次日 07:30）依次运行：Alpaca 日线与期权 → 基本面/财报/新闻 → `stock-pm-flow --days 1`（当日大额成交与分段） → `stock-pm-macro`（宏观日历） → `stock-pm-cboe`（Cboe 期权市场概览） → `stock-pm-events`（可信事件增量入库） → 复盘 → 环境快照 → 昨盘/复盘笔记 → 预测与打脸检查。`deploy/stock-pm-intraday.timer` 每 5 分钟触发一次，只在美股交易日 09:45–16:30（纽约时间）写入约 15 分钟延迟的分钟线。

## 个股页指标定义

- **K 线周期**：`1m / 5m / 15m / 60m` 由分钟线重采样；`1d / 1w / 1M` 由日线重采样。分钟线为 Alpaca 免费层约 15 分钟延迟。
- **均线**：所选周期收盘价的 MA5 / MA10 / MA20 / MA30；不足窗口长度时该均线为空。
- **KDJ**：RSV(9)，K/D 平滑 3（初始值 50），`J = 3K - 2D`。
- **成交量价位分布（估算）**：把每根日 K 的成交量在高低价区间内均摊到 32 个价位桶，POC 为最大桶，价值区覆盖约 70% 成交量。这不是交易所披露的持仓成本或主力筹码。
- **资金流**：大额成交分层（20–50 万 / 50–100 万 / 100 万+）只统计单笔金额 ≥ `LARGE_TRADE_NOTIONAL` 的成交；买卖方向由 tick rule **推断**，不能识别机构或散户。CMF(20) 与 OBV 为日 K 代理指标。
- **支撑/压力线**：来自上述成交量分布中低于/高于现价的高成交价位，叠加在图表上作为参考，不是订单簿。

## 大额成交与宏观事件

```powershell
stock-pm-flow --days 7        # 回填过去一周的分段量价与大额成交
stock-pm-flow --date 2026-09-04
stock-pm-macro                # 同步宏观日历；配置 FRED_API_KEY 后自动补非农/CPI/PCE 实际值
stock-pm-cboe                 # 拉取 Cboe 日终期权成交量与 Put/Call
stock-pm-environment          # 盘后追加 EnvironmentSnapshot（失败写 missing，不覆盖旧行）
stock-pm-tape                 # 盘后追加 TapeAnalysis + ReviewNote（失败写 missing，不覆盖旧行）
stock-pm-prediction           # 盘后追加 Prediction 并跑 PredictionCheck（失败写 missing，不编假边界）
```

- 大额成交阈值默认 $200,000（`LARGE_TRADE_NOTIONAL`）；方向由 tick rule 推断，页面上均标注"推断"。
- Alpaca 免费层限速约 200 请求/分钟，flow 已限制每标的每日最多 40 个逐笔窗口并加间隔。
- 宏观日历中未确认日期的事件（CPI/FOMC 惯例日）以「日期待确认」显示；
  FOMC 结果需公布后通过 `POST /api/macro/events` 更新 `surprise`（cut/hold/hike）。
- 期权异动依据成交量、未平仓量与两者比例识别；公开期权链不能判断主动买卖方向。

## 过程文档

讨论中的评估和方案（Product Fit Evaluation、重构方案、代码评估、数据源对照）在 [`docs/`](docs/README.md)。产品切片与哲学见 [`CURSOR_BRIEF.md`](CURSOR_BRIEF.md)：同一仓库连续四刀（A/P0 → 环境 → 盘面 → 预测打脸），不是「只做 M1」。

## 测试

```powershell
pytest -q
```
