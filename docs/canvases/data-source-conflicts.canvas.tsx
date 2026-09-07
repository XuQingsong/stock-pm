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

export default function DataSourceConflicts() {
  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H1>数据源会不会打架</H1>
        <Text tone="secondary">
          对照 stock-pm 当前代码：同一指标是否有两套口径同时进页面。结论是「不会并写同一数字」，但期权有两层、财报有历史残留。
        </Text>
      </Stack>

      <Grid columns={3} gap={12}>
        <Stat
          value="不会并写"
          label="FMP 与 Nasdaq"
          tone="success"
        />
        <Stat
          value="两层，不互替"
          label="期权：Cboe vs Alpaca"
          tone="warning"
        />
        <Stat
          value="有残留"
          label="切换源之后的旧行"
          tone="warning"
        />
      </Grid>

      <Callout tone="info" title="现在实际怎么选源">
        配了 FMP_API_KEY 时，估值和财报只走 FMP。Nasdaq 只在没 key 时当免费回退。新闻始终来自 Nasdaq。价格、个股期权墙来自 Alpaca。全市场期权成交量来自 Cboe 一家交易所，不是 OCC。
      </Callout>

      <Stack gap={8}>
        <H2>谁负责哪一块</H2>
        <Text tone="tertiary">同一单元格里的数字只有一个写入源。页面上相邻的数字可能来自不同层。</Text>
        <Table
          headers={["页面上看到的", "唯一写入源", "不要拿来比的东西"]}
          rows={[
            ["K 线 / 报价 / 量比", "Alpaca（日线视图优先 SIP）", "FMP 或 Nasdaq 的估值价格"],
            ["PE TTM、利润表、EPS 实际", "FMP（有 key）或 Nasdaq（无 key）", "两套 PE 算法混在同一条历史曲线"],
            ["新闻标题与情绪", "Nasdaq 新闻接口", "FMP 新闻（未接入）"],
            ["个股 Put/Call 墙、持仓代理比", "Alpaca indicative，近月约 18 档", "Cboe 全市场 P/C"],
            ["总览「Cboe 期权市场概览」", "Cboe 日终统计（一家交易所）", "OptionsDaily / OCC 全市场、个股墙"],
            ["筹码 / 大额成交方向", "Alpaca OHLCV + SIP 逐笔估算", "交易所官方机构成交"],
          ]}
        />
      </Stack>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader trailing={<Pill size="sm">运行时二选一</Pill>}>
            FMP × Nasdaq
          </CardHeader>
          <CardBody>
            <Stack gap={12}>
              <Text>
                每次 fundamentals 任务只选一个 provider。FMP 跑完会按
                (标的, 报告日, 财季标签) 覆盖同键旧行，不会同一格里叠两个 EPS。
              </Text>
              <H3>仍可能看起来打架</H3>
              <Text tone="secondary">
                Nasdaq 财季标签是「Jun/2026」，FMP 是「Q2」。主键含财季标签，报告日再差一天，库里就会留下两行同一季度。财报摘要页会按报告日偏好 FMP；原始 /earnings 接口和估值 PE 历史曲线不会做这层去重。
              </Text>
              <Text tone="secondary">
                PE 算法也不同：Nasdaq 用 Alpaca 现价 ÷ 四季 EPS 之和；FMP 用 ratios-ttm。切换源之后，估值图上的旧点仍是另一套口径。
              </Text>
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing={<Pill size="sm">不是双源抢同一指标</Pill>}>
            期权两层
          </CardHeader>
          <CardBody>
            <Stack gap={12}>
              <Text>
                没有第二套全市场期权源。OptionsDaily 没接入。个股墙和 Cboe 概览是不同问题：一只股票的近月结构和全交易所当天成交结构。
              </Text>
              <H3>数字不能横比</H3>
              <Text tone="secondary">
                Cboe 总 P/C 0.76 是该所认沽成交量 ÷ 认购成交量。复盘里「Put/Call 持仓代理比」是 Alpaca 近月、靠近现价约 18 档的未平仓量比，indicative 不是完整 OPRA。Cboe 个股桶 0.58 也不是 NVDA 的墙。
              </Text>
              <Text tone="secondary">
                页面已分开：总览/复盘顶部是 Cboe；个股「资讯与期权」是 Alpaca 墙。情绪分里的期权 30% 也只用 Alpaca 墙，不用 Cboe。
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Divider />

      <Stack gap={8}>
        <H2>真正需要小心的三处</H2>
        <Table
          headers={["风险", "会不会进同一格子", "表现"]}
          rows={[
            [
              "切换 FMP 前留下的 Nasdaq 财报行",
              "摘要页按报告日去重；库内可并存",
              "财季标签不同或报告日差一天时，同比/超预期次数可能偏",
            ],
            [
              "估值页 PE 历史",
              "会。快照按时间全画",
              "Nasdaq 自算 PE 与 FMP TTM PE 连在同一条线",
            ],
            [
              "用户把两个 P/C 当成同一个",
              "不会写进同一字段",
              "总览 Cboe P/C 与个股墙代理比口径完全不同",
            ],
          ]}
          rowTone={["warning", "warning", "neutral"]}
        />
      </Stack>

      <Callout tone="neutral" title="Alpaca IEX 与 SIP">
        日线视图优先 SIP；逐笔资金流固定 SIP。免费层报价/期权默认 IEX / indicative。这是同一家供应商的 feed 等级，不是 FMP 对 Nasdaq 那种双供应商。
      </Callout>

      <Row gap={8} wrap>
        <Pill tone="neutral" size="sm">价格 Alpaca</Pill>
        <Pill tone="neutral" size="sm">财报 FMP 或 Nasdaq</Pill>
        <Pill tone="neutral" size="sm">新闻 Nasdaq</Pill>
        <Pill tone="neutral" size="sm">个股期权 Alpaca</Pill>
        <Pill tone="neutral" size="sm">全市场期权 Cboe</Pill>
      </Row>
    </Stack>
  );
}
