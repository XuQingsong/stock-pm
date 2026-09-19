# V1 Step 1 — API / data mapping (persisted Brain reads)

Step 1 only. No market / company / claim HTML pages. No GLM on page open.
No second Brain kernel: this layer **maps existing persisted objects**.

## Existing Brain objects (source of truth)

| Persist table / store | Serializer | Role |
| --- | --- | --- |
| `brain_market_hypotheses` | `upsert_hypothesis` / `list_hypotheses` / `list_all_hypotheses` | Ticker-level Market Driver Hypothesis. **Not** a global driver by itself. |
| `brain_market_attention` | `upsert_market_attention` / `list_market_attentions` | Support / counter signals. |
| `brain_expectations` | `upsert_expectation` / `list_expectations` | Expectation State; trend / comparison. |
| `brain_events` | `insert_event` / `list_events` | Trigger / evidence only when issuer-specific (Meta capex, prints). |
| `brain_states` (`macro` / `industry` / `market_expectation`) | `insert_state` / `list_states` | Cross-ticker support for a global theme. |
| `brain_value_drivers` | `insert_driver` / `list_drivers` | Ticker structural exposure to a theme. |
| `brain_exposures` | `insert_exposure` / `list_exposures` | Mechanism + linked_exposure_ids. |
| `brain_price_divergences` | `upsert_divergence` / `list_divergences` | Price Feedback / unexplained remainder. |
| `brain_claims` + links + versions | `insert_claim` / `list_active_claims` | Core Claims (fundamental only on the company page). |
| `brain_thesis_snapshots` | `upsert_thesis` / `latest_thesis` | ThesisSnapshot. |
| `brain_financial_impacts` | `list_financial_impacts` | Financial summary. |
| `brain_scenarios` | `list_scenarios` | Scenario summary. |
| `brain_valuation_states` | `latest_valuation_state` | Valuation sensitivity (kept off the Core Claim list). |
| `brain_causal_edges` | `list_causal_edges` | Structural paths. Event nodes are not long-term roots. |
| `brain_history` | `list_history` | Real field deltas only. |
| `brain_research_questions` | `list_questions` | Open questions. |

Thin view module: `src/stock_pm/brain/product_read.py`.
Store helpers `list_all_*` only scan existing tables — they do not add objects.

## Response mapping

### `GET /api/market/overview`

| Field | Maps from |
| --- | --- |
| `llm_invoked` | Always `false` |
| `dominant_drivers[]` | **View** `MarketDominantDriver`: cluster market-wide hypotheses (`ai_demand`, `sector_macro`) + attentions + expectations + macro/industry states. Promote only with **2+ tickers** or a macro state. Never a single ticker hypothesis. Never an Event. |
| `dominant_drivers[].trigger_event_ids` | Matching issuer events (Meta capex, etc.) as **triggers**, not peers. |
| `pricing_axis` | Ranked real drivers only: 主导 / 次主导 / 辅助. No padding to 3. |
| `recent_driver_changes` | `brain_history` on member hypothesis / attention / expectation / macro state ids. Timestamp-only skipped. |
| `cross_asset_summary` / `sector_summary` | Honest empty until persisted cross-asset rows exist. |
| `empty_state` | `当前尚未形成明确主导变量` when the cluster rule fails. |

### `GET /api/brain/{symbol}/pm-view` (extended; no parallel `/api/company/...`)

| UI / field | Maps from |
| --- | --- |
| `llm_invoked` | `false` |
| `thesis` | `brain_thesis_snapshots` (`current_thesis`, `confidence`, supporting / risk claim ids). |
| `core_claims` | Core Claim rows that are fundamental (`structural` / `operating`). Drops `valuation` / `event` / “市场在交易X” / rate-sensitivity items. |
| `valuation_or_market_claims` | Those dropped rows, for the independent market-pricing module. |
| `what_changed` | Existing durable history filter. |
| `market_environment` | Global `MarketDominantDriver` × `TickerMarketSensitivity` × `current_relevance`. |
| `market_view.active_hypotheses` | Ticker-level Market Driver Hypothesis (unchanged). |
| `price_attribution` | Global drivers + sensitivity + ticker hypotheses + company events + PriceFundamentalDivergence. Multiple explanations allowed. `forced_single_cause=false`. |
| `structural_paths` | Causal edges whose **root is not an Event**. Events may appear only in `evidence_ids`. |
| `financial_summary` / `scenario_summary` / `valuation_summary` | Existing investment snapshot. |
| `open_research_questions` | Open ResearchQuestion (existing PM View filter). |
| `quote` | Run header / pack last price if persisted; else empty. |

`TickerMarketSensitivity` is a view, not a table:

| Field | Maps from |
| --- | --- |
| `market_driver_id` | Aggregated global driver id (`gmdd_{theme}`). |
| `sensitivity` | Structural: matching value drivers / exposures (magnitude). |
| `current_relevance` | Now: hypothesis status + attention. **Distinct calculation.** |
| `mechanism` | Exposure.mechanism / driver.why_it_matters. |
| `linked_exposure_ids` / `linked_driver_ids` | Existing exposure / driver ids. |

Trigger events never become a sensitivity row.

### `GET /api/brain/{symbol}/claims/{claim_id}` (extended)

| Field | Maps from |
| --- | --- |
| `llm_invoked` | `false` |
| `claim` / support / oppose | Existing claim + evidence links. |
| `what_would_invalidate` | Persisted `claim.what_would_invalidate` / reasoning only. Never generated. |
| `recent_change` / `claim_history` | Claim versions + history. |
| `market_pricing_assumptions` | Ticker Market Driver Hypotheses (visually independent). |
| `valuation_sensitivity` | `ValuationState`. |
| `financial_impacts` / `scenarios` | Existing downstream objects linked to the claim. |
| `price_feedback` | PriceFundamentalDivergence. `price_is_not_claim_invalidation=true`. |
| `questions` | Related ResearchQuestion. |

## Layering (API-layer)

1. Meta-style issuer capex = trigger / evidence. Not `MarketDominantDriver`, not a sensitivity row, not a structural graph root.
2. Core Claim list stays fundamental.
3. Price attribution may be partial / unexplained; never a forced single cause.
4. Missing persisted fields → empty states, no mocks, no GLM.

## Out of scope (later steps)

Market / company / claim HTML, full causal-graph page, events page, portfolio / DCF, new providers, Brain rewrite, deploy to 43.166.2.31.

## Step 1 completion note

- APIs live: `GET /api/market/overview`, extended `GET /api/brain/{symbol}/pm-view`, extended `GET /api/brain/{symbol}/claims/{claim_id}`.
- No new Brain tables. `MarketDominantDriver` / `TickerMarketSensitivity` are read views in `product_read.py`.
- Page paths set `llm_invoked=false`. Empty persisted data stays empty.
- Cases 1–2 and 4–7 covered at the API layer. Phase 0–4 / Persistence / Investment Reasoning / PM View: PASS.
- AVGO / LITE: endpoints accept whatever is persisted; missing fields return honest empties.
- Not done at Step 1 close: three HTML pages, Step 5 live data check, Step 6 deploy.
- Step 2 (separate): `/market` page. See `V1_STEP2_MARKET_PAGE.md`.
