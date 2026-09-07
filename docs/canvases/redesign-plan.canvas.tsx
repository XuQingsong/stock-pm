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
  Stack,
  Table,
  Text,
} from "cursor/canvas";

export default function RedesignPlan() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H1>stock-pm 重构方案</H1>
        <Text tone="secondary">
          针对四个问题：新闻情绪无决策价值、实时页只有一根K线、单标的与全列表模块混杂、自选名单写死在代码里。方案分三期，每期独立可用。
        </Text>
      </Stack>

      <H2>一、信息架构：按「看什么」分页，不按数据源分页</H2>
      <Text>
        现在 dashboard 一页里混着单标的 KPI、全列表技术面表、单标的估值、全列表财报，切换股票时只有一半内容跟着变。重构后每个页面回答一个问题：
      </Text>
      <Table
        headers={["页面", "回答的问题", "范围", "包含模块"]}
        rows={[
          [
            "/ 市场总览",
            "今天整个自选盘面怎么样",
            "全部自选",
            "宏观事件与板块影响、快照+技术信号统一表（合并现有两张表）、今日异动汇总（大额成交/期权异动）、近期财报日历",
          ],
          [
            "/stock/{symbol} 个股分析",
            "这只标的现在什么状态",
            "单标的",
            "日线K线+均线、日内分段量价与大额成交、技术指标、估值与财报反应、期权墙、个股新闻、历史复盘时间线",
          ],
          [
            "/replay 盘面回放",
            "某天/某段时间发生了什么",
            "全列表 + 可下钻",
            "日期与区间选择器、当日各标的分段量价摘要、区间涨跌与事件叠加、当日事件列表",
          ],
          [
            "/settings 设置",
            "管理自选",
            "配置",
            "新增/停用标的、板块与主题标签维护、大额成交阈值",
          ],
        ]}
      />
      <Text tone="secondary">
        API 同步分组：`/api/market/*`（全列表）、`/api/stock/{"{symbol}"}/*`（单标的）、`/api/replay/*`（按日期）、`/api/watchlist`（管理）。现有端点保留别名一个版本后下线。持仓/成交模块目前没有数据写入方（IBKR 已移除），默认从页面撤下，表结构保留。
      </Text>

      <H2>二、实时页替换为「分段量价 + 大额成交」</H2>
      <Callout tone="info" title="数据可行性">
        Alpaca 提供历史逐笔接口 `/v2/stocks/trades`，免费层可取 15 分钟延迟之前的 SIP
        逐笔。但一只活跃股一天有百万笔，不能全量拉。采用两步法：先用已入库的 1
        分钟K线找出放量分钟，再只对这些窗口拉逐笔筛大单。
      </Callout>
      <Grid columns={2} gap={16}>
        <Stack gap={8}>
          <H3>采集管道（每日收盘后 + 回填过去一周）</H3>
          <Text>
            第一步：对每只标的的当日 1 分钟K线，找出成交量大于「近 20
            个交易日同时间段均量 3 倍」或绝对成交额超阈值的分钟。第二步：只对这些分钟窗口调逐笔接口，保留单笔金额 ≥
            20 万美元（可配 `LARGE_TRADE_NOTIONAL`）的成交，用 tick rule
            结合报价中价推断主动买卖方向——推断结果会明确标注，不冒充真实方向。
          </Text>
        </Stack>
        <Stack gap={8}>
          <H3>分段分析</H3>
          <Text>
            用 ATR 比例的摆动分段（ZigZag）把一天切成趋势段，每段输出：起止时间、方向、涨跌幅、段内总量相对基准倍数、收盘相对
            VWAP 位置、大单净额（推断买-卖）与笔数。这就是「每一段大额成交的量价关系」：一眼看出哪一段是放量主动买上去的、哪一段是缩量阴跌。
          </Text>
        </Stack>
      </Grid>
      <Table
        headers={["新增", "内容"]}
        rows={[
          [
            "表 large_trades",
            "symbol, trade_time, price, size, notional, side_inferred, exchange；唯一键防重",
          ],
          [
            "表 intraday_segments",
            "symbol, trade_date, seg_no, 起止时间, direction, change_pct, volume, rel_volume, vwap_side, large_buy/sell_notional",
          ],
          [
            "API",
            "GET /api/stock/{symbol}/segments?date=  ·  GET /api/stock/{symbol}/large-trades?date=&min_notional=",
          ],
          [
            "UI",
            "个股页：K线上标注大单气泡（大小=金额、颜色=推断方向），下方分段量价表；默认展示最近一周，带日期选择",
          ],
        ]}
      />

      <H2>三、日期与区间回放</H2>
      <Text>
        所有分析查询加 `date` 或 `from/to` 参数（分段量价、事件、复盘、新闻均支持）。`/replay`
        页提供：单日模式——选定日期看当天全列表分段摘要与事件；区间模式——K线叠加事件标记，输出区间涨跌、量变化、期间发生的宏观事件与个股事件。数据都已在库里（price_bars
        保留全部历史，daily_reviews 按日存），主要是查询参数化和页面工作。
      </Text>

      <H2>四、新闻改造：从「情绪分」到「事件 → 板块影响」</H2>
      <Text>
        现在的情绪分是英文关键词计数加权，无法回答「非农超预期对我的持仓意味着什么」。改造分三层：
      </Text>
      <Table
        headers={["层", "做法", "产出"]}
        rows={[
          [
            "1. 宏观事件日历",
            "新表 macro_events：事件时间、类型（非农/CPI/FOMC/PCE）、实际值、预期值、前值。数据源见待确认项",
            "「9/5 20:30 非农 +14.2万，低于预期 → 降息预期升温」",
          ],
          [
            "2. 标的主题标签",
            "watchlist 表每只标的挂 sector 与主题标签：利率敏感度（高估值成长=高）、AI/半导体、消费电子、指数ETF 等",
            "NVDA = 半导体 + 高估值成长 + AI",
          ],
          [
            "3. 影响映射",
            "规则表：事件类型 × 意外方向 → 受影响主题与方向。新闻按主题关键词归类后走同一映射",
            "降息预期升温 → 利多高估值成长（NVDA/AVGO/QQQ）与黄金；利空银行（不在自选则不显示）",
          ],
        ]}
      />
      <Callout tone="warning" title="诚实边界">
        规则法只覆盖预设的事件类型和主题，识别不了复杂逻辑链。方案预留每日一次的 LLM
        批处理位置（把当日新闻+事件交给模型输出结构化影响标注），是否启用见待确认项。旧的情绪分降级为个股页的参考小项，不再作为独立模块。
      </Callout>

      <H2>五、自选名单入库</H2>
      <Text>
        `config.WATCHLIST` 移入数据库 `watchlist` 表（symbol、名称、交易所、asset_class、sector、主题标签、active、added_at），现有
        9 只作为种子数据。新增流程：提交 symbol → 调 Alpaca assets 接口校验并取名称/交易所 →
        后台回填 430 天日线、基本面、期权 → 标记 active 生效。查询层从表读取（进程内缓存
        60 秒），ETF 判断改用 asset_class 字段，不再硬编码 QQQ。停用为软删除，历史数据保留。
      </Text>

      <Divider />

      <H2>实施分期</H2>
      <Table
        headers={["阶段", "内容", "依赖", "工作量"]}
        rows={[
          [
            "Phase 1 基础",
            "watchlist 入库与管理 API/页面；四页信息架构重构，现有模块归位；API 分组",
            "无",
            "中",
          ],
          [
            "Phase 2 量价核心",
            "大额成交两步采集 + 分段分析 + 回填一周；/replay 日期区间回放；实时页替换",
            "Phase 1 的页面框架",
            "大",
          ],
          [
            "Phase 3 事件与板块",
            "macro_events 日历、标的主题标签、影响映射规则、总览页事件面板；可选 LLM 标注任务",
            "Phase 1 的 watchlist 标签字段",
            "中",
          ],
        ]}
      />
      <Text tone="secondary">
        风险：Alpaca 免费层限速约 200 请求/分钟，一周逐笔回填需分批执行；Nasdaq
        新闻只有日期没有时间戳，事件时间对齐依赖 macro_events 而非新闻本身。
      </Text>
    </Stack>
  );
}
