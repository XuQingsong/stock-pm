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
  UsageBar,
  useHostTheme,
} from "cursor/canvas";

const GOAL_ROWS = [
  [
    "基本信息",
    "已覆盖",
    "自选名称、交易所、板块、主题标签；个股页顶部报价。",
    "neutral",
  ],
  [
    "过去一年股价",
    "半覆盖",
    "日K约 260 根可看图；有 52 周高低距。没有「一年涨跌幅」摘要，总览也不展示 5/20/50 日回报。",
    "warning",
  ],
  [
    "财报信息",
    "半覆盖",
    "近一年季度 EPS/营收实际与预期、财报后 1/5/20 日股价。净利润预期、Forward PE、分析师目标价因套餐留空。",
    "warning",
  ],
  [
    "一年是否达标预期",
    "半覆盖",
    "能逐季看超预期/低于预期，没有「过去四季 3/4 超预期、营收是否减速」的年报式结论。",
    "warning",
  ],
  [
    "行业是否高速发展",
    "未覆盖",
    "表里有营收/EPS 同比字段，FMP 适配器写死为 null。没有行业增速、同业对比或「成长期」判断。",
    "danger",
  ],
  [
    "股价是否符合估值",
    "半覆盖",
    "有 PE TTM、相对本库快照分位。分位不是一年市场历史；也没有相对行业、PEG 可用值或公允价值对照现价。",
    "warning",
  ],
] as const;

const TAPE_ROWS = [
  [
    "量是否放大",
    "已覆盖",
    "量比 20 日、复盘 relative_volume、放量突破/缩量跌破规则。",
    "success",
  ],
  [
    "支撑 / 压力",
    "半覆盖",
    "复盘有最近支撑、压力、是否测试/跌破、20 日高低点突破。支撑来自筹码估算+均线，不是订单簿。总览不突出「守住/跌破」。",
    "warning",
  ],
  [
    "情绪面",
    "弱",
    "仍是标题关键词正负 + 期权 Put/Call + 20 日动量加权。不是盘面情绪，也不是当天消息驱动。",
    "danger",
  ],
  [
    "近一周趋势",
    "半覆盖",
    "SQL 已算 return_5d_pct。总览表没展示；复盘摘要也不说「近 5 日向上/向下」。",
    "warning",
  ],
  [
    "MA5 / 20 / 50 / 200",
    "半覆盖",
    "后端日线有这四条和多头排列。个股图却画 MA5/10/20/30，对不上你要看的位置。",
    "warning",
  ],
  [
    "股价健康与中长期",
    "半覆盖",
    "有 RSI、52 周位置、筹码浮盈/套牢、评分偏多偏空。没有把均线结构+量+位置合成一句「趋势健康/过热/走坏」。",
    "warning",
  ],
] as const;

const REVIEW_ROWS = [
  [
    "收盘后看盘面",
    "已覆盖",
    "/review 按交易日列出全部自选：评分、量价话术、支撑压力、分段量价；可跳分钟回放。",
    "success",
  ],
  [
    "情绪 + 消息 + 板块解释为何走成这样",
    "未覆盖",
    "复盘只吃日 K、CMF/OBV、期权墙。当天新闻和宏观在总览另一处，没有接到「这只股票今天为什么涨跌」。",
    "danger",
  ],
  [
    "预测明天大致走势",
    "未覆盖",
    "没有预测字段、区间或概率。评分是对已发生盘面的规则打分，不是对次日的判断。",
    "danger",
  ],
  [
    "对照次日、迭代总结",
    "未覆盖",
    "daily_reviews 只能按日覆盖写入规则摘要，不能记你的判断、也不能把「昨日看法 vs 今日实际」并排复盘。",
    "danger",
  ],
] as const;

const QUALITY_ROWS = [
  [
    "诚实缺数",
    "好",
    "缺失显示「数据源暂未提供」，402/未覆盖新闻不强行编造影响。适合个人研究工具。",
  ],
  [
    "模块边界",
    "中上",
    "查询/写入已拆 mixin；分析、影响映射、供应商有测试。review.py 仍复制了一套筹码/资金流，和 analytics.py 会漂移。",
  ],
  [
    "指标口径",
    "中",
    "图上均线与日线技术面不是同一套；估值分位依赖入库快照数量，不是一年行情。增长字段有表无值。",
  ],
  [
    "前端形态",
    "中",
    "总览/复盘/回放各写一份 HTML+内联样式，交互能用，但同一指标在不同页展示不一致。",
  ],
  [
    "测试",
    "够用",
    "API、复盘突破、影响规则、财报合并都有单测。没有「复盘是否挂上当日新闻」或「均线是否与图一致」这类产品断言。",
  ],
];

function toneFor(status: string): "success" | "danger" | "warning" | "info" | "neutral" {
  if (status === "已覆盖" || status === "success") return "success";
  if (status === "未覆盖" || status === "弱" || status === "danger") return "danger";
  if (status === "半覆盖" || status === "warning") return "warning";
  return "neutral";
}

export default function ProductFitEvaluation() {
  const theme = useHostTheme();

  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H1>stock-pm 对照你的目标</H1>
        <Text tone="secondary">
          版本 0.6.0。口径是「第二天早上看自选、收盘后复盘并迭代判断」，不是交易执行系统。
        </Text>
      </Stack>

      <Callout tone="warning" title="结论：能当数据台，还撑不起你要的研究闭环">
        采集、日 K、财报超预期表、量比、支撑压力规则、每日复盘页都已经有了。缺的是把这些拼成三个你真正会问的问题：这家公司基本面是否还值这个价、昨天盘面是否健康、以及「我昨天怎么看、今天对不对」。第三段几乎是空的，所以现在还满足不了完整需求。
      </Callout>

      <Grid columns={3} gap={16}>
        <Stat value="约 55%" label="基本面与估值" tone="warning" />
        <Stat value="约 65%" label="隔日盘面（数据层更高）" tone="warning" />
        <Stat value="约 25%" label="复盘解释与迭代" tone="danger" />
      </Grid>

      <Stack gap={8}>
        <H2>需求覆盖（按你的三块加权）</H2>
        <UsageBar
          total={100}
          topLeftLabel="已覆盖 35 · 半覆盖 40 · 缺口 25"
          topRightLabel="示意比例，不是精确计分"
          segments={[
            { id: "met", value: 35, color: "green" },
            { id: "partial", value: 40, color: "yellow" },
            { id: "gap", value: 25, color: "orange" },
          ]}
        />
        <Text tone="tertiary" size="small">
          来源：对照 README、review.py / queries.py / providers.py / 个股与复盘页 · 2026-09-07
        </Text>
      </Stack>

      <Stack gap={10}>
        <H2>一、自选基本面</H2>
        <Text>
          你要看的是：这只票过去一年涨了多少、财报有没有持续超预期、行业是否还在高增长、现价贵不贵。
        </Text>
        <Table
          headers={["你要的", "现状", "代码里实际有什么"]}
          rows={GOAL_ROWS.map((row) => [row[0], row[1], row[2]])}
          rowTone={GOAL_ROWS.map((row) => toneFor(row[3]))}
        />
      </Stack>

      <Grid columns="1.1fr 0.9fr" gap={16}>
        <Stack gap={8}>
          <H3>已经能用的部分</H3>
          <Text>
            个股「财报」页可以把近一年季度实际/预期摊开，并带上财报后股价反应。这比新闻标题有用，也更接近「有没有达标」。
          </Text>
          <Text>
            估值页有 PE TTM。在快照攒够之前，分位会偏短、偏本地，不能当成「相对过去一年贵了还是便宜了」。
          </Text>
        </Stack>
        <Card>
          <CardHeader>最大缺口</CardHeader>
          <CardBody>
            <Stack gap={8}>
              <Text weight="semibold">行业是否还在高速发展期</Text>
              <Text tone="secondary">
                没有营收同比序列，也没有同业增速。半导体/AI 只是自选手动打的主题标签，不能回答「这个行业还在不在成长期」。
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Divider />

      <Stack gap={10}>
        <H2>二、隔日盘面（你没时间盯盘）</H2>
        <Text>
          目标是第二天用几分钟看完：量大不大、有没有破位、一周方向、均线位置、盘面是否健康。
        </Text>
        <Table
          headers={["你要的", "现状", "代码里实际有什么"]}
          rows={TAPE_ROWS.map((row) => [row[0], row[1], row[2]])}
          rowTone={TAPE_ROWS.map((row) => toneFor(row[3]))}
        />
      </Stack>

      <Callout tone="info" title="盘面数据比页面组装得更好">
        日线 SQL 已经有 MA5/20/50/200、5/20/50 日涨跌、量比、52 周位置、多头排列。总览却只放 RSI、量比、52 周高、一句「日线信号」。个股图还画了另一套均线。隔日简报缺的是编排，不完全是缺数。
      </Callout>

      <Divider />

      <Stack gap={10}>
        <H2>三、每日复盘与迭代判断</H2>
        <Text>
          这是你真正想形成的习惯：用情绪、消息、板块解释当天为什么这样走，写下明天大致判断，再用第二天走势打分、改方法。
        </Text>
        <Table
          headers={["你要的", "现状", "代码里实际有什么"]}
          rows={REVIEW_ROWS.map((row) => [row[0], row[1], row[2]])}
          rowTone={REVIEW_ROWS.map((row) => toneFor(row[3]))}
        />
      </Stack>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>现在的复盘在算什么</CardHeader>
          <CardBody>
            <Stack gap={6}>
              <Text>量价形态（收盘位置、影线、相对成交量）</Text>
              <Text>相对 20 日高低点的突破/跌破</Text>
              <Text>CMF / OBV 资金流代理</Text>
              <Text>60 日成交量分布位置</Text>
              <Text>近月期权墙（indicative）</Text>
              <Text tone="secondary" size="small">
                输出是一段规则摘要和 −100～100 分。不读当天新闻，不读关联板块，不产生次日预测。
              </Text>
            </Stack>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>要闭环还缺什么</CardHeader>
          <CardBody>
            <Stack gap={6}>
              <Text>把当日宏观、主题新闻接到该标的复盘卡上</Text>
              <Text>你自己的「原因假设」和「明日看法」可写可存</Text>
              <Text>次日自动对照：涨跌、量、是否破位 vs 昨日判断</Text>
              <Text>按周回看命中率，而不是每天覆盖掉旧摘要</Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Divider />

      <Stack gap={10}>
        <H2>代码质量（相对这个目标）</H2>
        <Text tone="secondary">
          作为个人自选数据服务，结构清楚、缺数不装懂，质量中上。它还没有把领域模型做成「基本面结论 / 盘面简报 / 判断日志」三层。
        </Text>
        <Table
          headers={["方面", "判断", "说明"]}
          rows={QUALITY_ROWS.map((row) => [row[0], row[1], row[2]])}
          rowTone={["success", "info", "warning", "warning", "info"]}
        />
      </Stack>

      <Stack gap={8}>
        <H2>若要对齐你的目标，优先顺序</H2>
        <Row gap={8} wrap>
          <Pill active>1. 隔日盘面简报</Pill>
          <Pill>2. 复盘挂上消息与板块</Pill>
          <Pill>3. 判断日志与对照</Pill>
          <Pill>4. 一年基本面结论</Pill>
        </Row>
        <Table
          headers={["优先级", "改什么", "为什么先做这个"]}
          rows={[
            [
              "P0",
              "总览/复盘做成隔日简报：量比、5 日涨跌、是否守住支撑/压力、MA5/20/50/200 位置与排列。个股图改成同一套均线。",
              "数据已在 SQL 里，改展示就能补上你每天最需要看的那几行。",
            ],
            [
              "P0",
              "日终复盘卡附上当日该标的新闻、命中主题、宏观对自选主题的方向，明确写「可能解释盘中走势的因素」，并标明规则不是因果。",
              "没有这一层，复盘只是量价复述，解释不了「为什么」。",
            ],
            [
              "P1",
              "给 daily_reviews 增加用户字段：原因假设、明日偏向、关注位。次日自动写入实际涨跌/量比/破位，形成对照。",
              "这是你说的迭代学习；现在完全没有落点。",
            ],
            [
              "P1",
              "补营收/EPS 同比（可用已有利润表季度序列自己算），并给出「近四季超预期次数 + 增速是否放缓」。行业成长期用同主题自选对比，不编行业数据。",
              "先回答「这家公司自己还在不在增长」，再谈行业。",
            ],
            [
              "P2",
              "估值改成「现价 vs 自身一年分位 + 明确缺失项」。不要在 Forward PE / 目标价空着时给「便宜/贵」结论。",
              "避免用过短的本地快照冒充长期估值。",
            ],
          ]}
        />
      </Stack>

      <Text tone="tertiary" size="small" style={{ color: theme.text.tertiary }}>
        评估范围：src/stock_pm（api、queries、review、analytics、impact、providers、静态页）与 tests。未把持仓/下单列入目标。
      </Text>
    </Stack>
  );
}
