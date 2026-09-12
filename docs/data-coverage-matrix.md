# Phase 4A data coverage matrix

Recorded fixtures in tests are labeled as such. They are not live market prints.

| Dataset / metric | Source | Series / symbol | Refresh | Freshness | Fallback | Current contract |
| --- | --- | --- | --- | --- | --- | --- |
| daily_price_bars / close | Alpaca SIP | NVDA 1d | daily, last completed NY session | 7d | last valid stored OHLC only; never snapshot last onto high/low | split-adjusted; invalid OHLC skipped at ingest and quarantined |
| earnings_reports / eps | FMP (Nasdaq fallback) | NVDA earnings | on fundamentals job | 120d | existing `synced_at` row | maps `eps_estimate` + `synced_at` as latest consensus |
| earnings_prior_consensus | FMP | n/a | n/a | 120d | none | **gap**: Alpha Vantage not wired; no dated prior snapshot |
| SEC EDGAR | — | — | — | — | — | **not integrated** (status-only; no collector this phase) |
| macro_nfp / nfp | FRED | PAYEMS | calendar + FRED | 45d | last successful FRED cache (`stale`) | existing calendar path |
| macro_cpi / cpi | FRED | CPIAUCSL | monthly | 50d | last successful FRED cache | official CPI-U index |
| macro_rates_confirm / us2y | FRED | DGS2 | daily | 14d | last successful FRED cache | US 2Y Treasury |
| macro_vix / vix | FRED | VIXCLS | daily | 7d | last successful FRED cache | CBOE VIX via FRED; not Cboe P/C HTML |
| macro_gold / gold | FRED | GOLDPMGBD228NLBM | daily | 7d | last successful FRED cache | optional; missing does not drop other facts |
| macro_wti / wti | FRED | DCOILWTICO | daily | 7d | last successful FRED cache | optional |
| macro_dxy / dxy | FRED | DTWEXBGS | daily | 7d | last successful FRED cache | Fed broad dollar, not ICE DXY |

Each persisted observation keeps `source`, `series/symbol`, `observed_at` (fetch clock), `as_of` (period), `fetched_at`, `unit`, `frequency`, `status` in `macro_events.notes` JSON. `event_time` / `release_date` are not used as the observation clock.

Failure reasons stay distinct: `source_not_configured`, `upstream_empty`, `record_stale`, `record_invalid`, `query_error`.
