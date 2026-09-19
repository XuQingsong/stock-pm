# V1 Step 2 — 市场总览页

Step 2 only. Page: `/market`. Data: `GET /api/market/overview` from persisted product_read.

## Wiring

```text
Browser /market → GET /api/market/overview → product_read.build_market_overview
```

- `llm_invoked` must stay `false`. The page refuses to render if it is true.
- No `run_brain` / GLM on open. No company / claim / graph / events pages.
- Visual baseline: locked `design-hifi-v1/market.html` (主导/次主导/辅助 rows) + empty-state copy.
- Product page only renders real `pricing_axis` / `dominant_drivers`. No padded Top 3.

## Display rules

| UI | Source | Honest empty |
| --- | --- | --- |
| 定价主轴分条 | `pricing_axis[].role` + `name` / `display_name` | hide rows; show `当前尚未形成明确主导变量` |
| 主导变量卡片 | `dominant_drivers` (max 3, no padding) | same empty sentence; never fake Top 3 |
| 枚举 | 前端中文：很高/高/中/低；正在增强/高位持续/影响减弱/基本消退 | omit chip if enum missing |
| 支持 / 反向信号 | `supporting_signals` / `counter_signals` labels only | 暂无已记录条目（不展示 id） |
| 触发事件层 | `trigger_events[]` under drivers, not peer cards | 近窗暂无改写主轴的触发事件 |
| 最近变化 | `recent_driver_changes` + `kind_label` / `summary` | 近窗暂无主轴或触发的实质变化 |
| 相关标的 | `affected_tickers` on real drivers | 暂无已关联标的 |

Main path does not print English type names (`MarketDominantDriver`, raw ids, `llm_invoked`).

## Smoke / self-check

```bash
pytest tests/test_v1_step2_market_page.py tests/test_v1_step1_product_read.py -q
```

Manual:

1. Open `/market`. Network tab: only `GET /api/market/overview` for data.
2. Empty store → first screen shows `当前尚未形成明确主导变量`. No Top 1/2/3 cards.
3. Seeded AI-capex cluster (AVGO+LITE) → one 主导 row `AI 资本开支`; Meta capex is a trigger card, not a peer axis.
4. Response JSON: `llm_invoked === false`.

## PM report fields (Step 2 slice)

| Field | Result |
| --- | --- |
| 市场总览 | PASS (page wired; company/claim pages not in this step) |
| Trigger 分层 | PASS (trigger section is a lower layer; Meta-style issuer capex is not a driver card) |
| 无 LLM | PASS (`llm_invoked=false`; page open does not call `run_brain`) |
| Persistence | PASS (read-only persisted Brain; empty stays empty) |
| 公司投资总览 | not this step |
| 核心判断详情 | not this step |

Not done: Step 3–4 pages, Step 5 live AVGO/LITE walkthrough on 43.166.2.31, Step 6 deploy.
