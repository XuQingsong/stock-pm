import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

const FINDINGS = [
  [
    "必须修",
    "api.py 重复注册 GET /api/reviews",
    "同一路径定义了两次完全相同的函数。FastAPI 会覆盖前者，容易让后续改动只改到一半。",
    "src/stock_pm/api.py:191-205",
  ],
  [
    "必须修",
    "K 线 feed 与配置不一致",
    "快照用 ALPACA_DATA_FEED（默认 iex），_bars() 却写死 feed=sip。免费/未开通 SIP 的账号会快照成功、日线/分钟线失败。history.source 还标成 alpaca_sip_delayed。",
    "src/stock_pm/alpaca.py:79 vs config.py:44",
  ],
  [
    "高",
    "history() 未过滤 bar_size",
    "price_bars 同时存 1m 和 1d。GET /api/market/history/{symbol} 按时间倒序 LIMIT，会把分钟线和日线混在一起。",
    "src/stock_pm/database.py:121-135",
  ],
  [
    "高",
    "仍存在第二套分钟线写入路径",
    "云端 timer 走 Alpaca；stock-pm-realtime 仍从 Nasdaq 非官方接口写同一张 price_bars（1m, ON CONFLICT 覆盖）。本地误跑会污染 live 信号。",
    "src/stock_pm/realtime.py",
  ],
  [
    "中",
    "单标的总览会算全市场技术面",
    "investment_overview(symbol) 调用 technical_summary()（全自选窗口函数），再在 Python 里过滤。9 只股票还能跑，接口语义不对。",
    "src/stock_pm/database.py:503-515",
  ],
  [
    "中",
    "recent_earnings 是 N 次 LATERAL 查询",
    "对每只股票跑一遍 earnings_history（每条财报 5 次 LATERAL 日线查找），再在内存排序截断。",
    "src/stock_pm/database.py:406-411",
  ],
  [
    "债",
    "IBKR 残留与文档漂移",
    "WATCHLIST 仍带 conid；schema 默认 source=ibkr_plugin；/api/ingest/ibkr 仍在。README 写 /live 用 Alpaca，但 realtime 入口还在 pyproject。",
    "config.py / schema.sql / api.py",
  ],
  [
    "债",
    "Database 上帝类",
    "约 1000 行：连接池、校验、分析 SQL、情绪打分、ingest upsert。查询与写入、领域规则挤在一起，测试只能 mock 整类。",
    "src/stock_pm/database.py",
  ],
];

export default function CodeReview() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H1>stock-pm 代码评估</H1>
        <Text tone="secondary">
          范围：src/stock_pm（9 个模块）、schema、deploy timer、测试。评估口径是「个人
          9 只自选股的数据服务」而不是交易执行系统。
        </Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat value="可用" label="总体判断" tone="success" />
        <Stat value="2" label="必须先修的缺陷" tone="danger" />
        <Stat value="4" label="正确性 / 数据风险" tone="warning" />
        <Stat value="9" label="自选股规模下可接受" />
      </Grid>

      <Callout tone="success" title="结论">
        作为个人价值投资看板，方向和分层是合理的：Alpaca 延迟行情入库、PostgreSQL
        幂等写入、FastAPI 查询、日终复盘与基本面补充分开跑。云端
        deploy/stock-pm-intraday 只调 alpaca --mode
        intraday，主路径比 README 里残留的 Nasdaq 实时采集更干净。它还不是「仓位管理产品」——账户/成交仍是 IBKR
        ingest 遗留，没有仓位规则或风控。
      </Callout>

      <H2>做得好的地方</H2>
      <Grid columns={2} gap={16}>
        <Stack gap={8}>
          <H3>数据管道</H3>
          <Text>
            采集与查询分离；upsert 按自然键去重；日线复盘用 DISTINCT ON
            优先 Alpaca 源，说明已经意识到多源污染。Alpaca 分钟/日线截到 now-16
            分钟，和免费延迟行情匹配。自选名单校验防止任意 ticker 打爆库。
          </Text>
        </Stack>
        <Stack gap={8}>
          <H3>分析有边界</H3>
          <Text>
            ETF 空字段不填估算值；期权异动写明无法判断主动方向；情绪分带 method
            字符串。突破判定要求收盘越过前高且量比确认，比「盘中摸了一下」更稳。ingest
            token 用 compare_digest，SQL 基本参数化。
          </Text>
        </Stack>
      </Grid>

      <H2>问题清单</H2>
      <Card>
        <CardHeader trailing={<Text size="small">按严重程度</Text>}>
          发现项
        </CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["级别", "问题", "为什么要紧", "位置"]}
            columnAlign={["left", "left", "left", "left"]}
            rowTone={[
              "danger",
              "danger",
              "warning",
              "warning",
              "warning",
              "warning",
              "neutral",
              "neutral",
            ]}
            rows={FINDINGS}
          />
        </CardBody>
      </Card>

      <H2>分析逻辑是否站得住</H2>
      <Callout tone="warning" title="指标是启发式，命名比实现更像「标准技术指标」">
        日线 RSI14 用的是 14 日简单平均涨跌，不是 Welles Wilder
        平滑。复盘均线是最近 N 根收盘价算术平均，和仪表盘 SQL
        窗口均线接近但实现两套。Volume profile / CMF / 归一化 OBV
        作为「代理信号」可以，不宜当成机构级筹码分布。评分把 AVWAP、CMF、突破、POC、MA50
        线性加权到 ±100，阈值 25 分切多空——适合自己看，不要当交易信号。
      </Callout>
      <Grid columns="1.2fr 1fr" gap={16}>
        <Stack gap={8}>
          <H3>复盘模块（review.py）</H3>
          <Text>
            量价、突破、资金流、价值区拆开再合成摘要，结构清楚。问题是
            generate_review 边算边写 market_events，分析与持久化耦在一起；large_trade_count
            恒为 0，字段是空壳。期权墙取「最新快照里全部到期」的最大 OI，而
            option_wall() API 只取最近到期，两边口径不一致。
          </Text>
        </Stack>
        <Stack gap={8}>
          <H3>情绪与新闻</H3>
          <Text>
            Nasdaq 新闻用 beat/miss 等英文词计数，标题党会翻转分数。期权
            Put/Call 用
            100×(1−pc)/(1+pc)，再和新闻、20 日动量加权。对 9
            只股票做展示可以，不能解释为「市场情绪」。
          </Text>
        </Stack>
      </Grid>

      <H2>结构与测试</H2>
      <Row gap={8} wrap>
        <Pill tone="info" active>
          FastAPI 薄封装合理
        </Pill>
        <Pill tone="warning" active>
          连接池在 import 时创建
        </Pill>
        <Pill tone="warning" active>
          schema 每次启动全量执行
        </Pill>
        <Pill tone="neutral" active>
          版本号三处不一致
        </Pill>
      </Row>
      <Text>
        API 层主要做校验和 HTTP 映射，这点干净。database 在模块 import
        时就建池，lifespan 只 initialize、不 close。每次 CLI/API 都跑完整
        schema.sql（IF NOT EXISTS，功能上能用，迁移策略原始）。__init__.py
        是 0.1.0，pyproject/api 是 0.5.0。测试覆盖健康检查、token、复盘突破，但
        FakeDatabase 里 intraday_history / market_events / latest_reviews
        各定义了两次，后写覆盖前写——和重复路由是同一类疏忽。没有针对 SIP/IEX、bar_size
        混用、或 ingest 冲突的回归测试。
      </Text>

      <Divider />

      <H2>建议顺序</H2>
      <Table
        headers={["顺序", "动作", "收益"]}
        rows={[
          [
            "1",
            "删掉重复 /api/reviews；history() 加上 bar_size",
            "立刻消除接口歧义",
          ],
          [
            "2",
            "_bars() 使用 settings.alpaca_data_feed，source 与配置一致",
            "避免免费账号静默缺日线",
          ],
          [
            "3",
            "明确唯一分钟线写入方：云端只留 Alpaca，归档或删除 realtime",
            "live 信号不再被 Nasdaq 残缺 OHLC 覆盖",
          ],
          [
            "4",
            "overview / earnings 按 symbol 查；复盘期权口径与 option_wall 对齐",
            "数字可解释、可复现",
          ],
          [
            "5",
            "拆 Database：queries / ingest / scoring；清掉 IBKR conid 与死路由",
            "后面加股票或换数据源时不会继续堆上帝类",
          ],
        ]}
      />
      <Text tone="secondary" size="small">
        评估基于仓库当前源码，未跑生产库与实盘 Alpaca 权限。SIP
        是否可用取决于你的 Alpaca 套餐。
      </Text>
    </Stack>
  );
}
