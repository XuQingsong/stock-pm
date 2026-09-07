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
| `/` 市场总览 | 全部自选 | 宏观事件与板块影响、快照+技术信号统一表、今日异动、近期财报、新闻（带主题标签） |
| `/stock/{symbol}` 个股分析 | 单标的 | 日线K线+均线、日内分段量价与大额成交、估值、期权墙、财报反应、复盘、个股新闻 |
| `/replay` 盘面回放 | 按日期/区间 | 单日全列表分段量价摘要+当日事件；区间走势与宏观/个股事件叠加 |
| `/settings` 设置 | 配置 | 自选新增（Alpaca 校验+自动回填）与停用 |

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

正式安装路径：`D:\Program Files\PostgreSQL\17`

如果另一台机器使用 Docker，也可运行：

```powershell
docker compose up -d postgres
```

连接配置位于 `.env`：

```text
DATABASE_URL=postgresql://stock_pm:stock_pm_dev@localhost:5432/stock_pm
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

- 管理：`GET/POST /api/watchlist`、`DELETE /api/watchlist/{symbol}`、`GET /api/sync/status`、`GET /health`
- 全列表：`/api/market/snapshot | signals | technicals | events | news | earnings/recent | impact`
- 单标的：`/api/stock/{symbol}/chart | intraday | segments | large-trades | overview | fundamentals | earnings | sentiment | options | news | reviews | history`
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

```powershell
stock-pm-fundamentals
```

该命令从 Nasdaq 公共接口同步估值快照、分析师目标价和最近四次财报 EPS，并结合数据库中的日线计算 TTM / Forward PE 与财报前后 1、5、20 个交易日的涨跌。ETF（例如 QQQ）或数据源未覆盖的字段会显示为空，不用估算值填充。

云服务器使用 `deploy/stock-pm-daily.timer` 每天 23:30 UTC（北京时间次日 07:30）依次运行：Alpaca 日线与期权 → Nasdaq 估值/财报/新闻 → `stock-pm-flow --days 1`（当日大额成交与分段） → `stock-pm-macro`（宏观日历） → 复盘。`deploy/stock-pm-intraday.timer` 每 5 分钟触发一次，只在美股交易日 09:45–16:30（纽约时间）写入约 15 分钟延迟的分钟线。

## 大额成交与宏观事件

```powershell
stock-pm-flow --days 7        # 回填过去一周的分段量价与大额成交
stock-pm-flow --date 2026-09-04
stock-pm-macro                # 同步宏观日历；配置 FRED_API_KEY 后自动补非农/CPI/PCE 实际值
```

- 大额成交阈值默认 $200,000（`LARGE_TRADE_NOTIONAL`）；方向由 tick rule 推断，页面上均标注"推断"。
- Alpaca 免费层限速约 200 请求/分钟，flow 已限制每标的每日最多 40 个逐笔窗口并加间隔。
- 宏观日历中未确认日期的事件（CPI/FOMC 惯例日）以「日期待确认」显示；
  FOMC 结果需公布后通过 `POST /api/macro/events` 更新 `surprise`（cut/hold/hike）。
- 期权异动依据成交量、未平仓量与两者比例识别；公开期权链不能判断主动买卖方向。

## 测试

```powershell
pytest -q
```
