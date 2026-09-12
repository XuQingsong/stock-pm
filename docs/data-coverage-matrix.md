# Phase 4A data coverage matrix

Recorded fixtures in tests are labeled as such. They are not live market prints.

| Dataset / metric | Source | Series / symbol | Refresh | Freshness | Fallback | Current contract |
| --- | --- | --- | --- | --- | --- | --- |
| daily_price_bars / close | Alpaca SIP | NVDA 1d | daily, last completed NY session | 7d | last valid stored OHLC only; never snapshot last onto high/low | split-adjusted; invalid OHLC skipped at ingest; no startup batch-delete |
| earnings_reports / eps | FMP (Nasdaq fallback) | NVDA earnings | on fundamentals job | 120d | existing `synced_at` row | maps `eps_estimate` + `synced_at` as latest consensus |
| earnings_prior_consensus | FMP | n/a | n/a | 120d | none | **gap**: Alpha Vantage not wired; no dated prior snapshot |
| SEC EDGAR | — | — | — | — | — | **not integrated** (status-only; no collector this phase) |
| macro_nfp / nfp | FRED | PAYEMS | calendar + FRED | 45d | last successful FRED cache (`stale`) | existing calendar path |
| macro_cpi / cpi | FRED | CPIAUCSL | monthly | 50d | last successful FRED cache | official CPI-U index |
| macro_rates_confirm / us2y | FRED | DGS2 | daily | 14d | last successful FRED cache | US 2Y Treasury |
| macro_vix / vix | FRED | VIXCLS | daily | 7d | last successful FRED cache | CBOE VIX via FRED; not Cboe P/C HTML |
| macro_gold / gold | FRED | GOLDPMGBD228NLBM | daily | 7d | last successful FRED cache | optional; missing does not drop other facts |
| macro_wti / wti | FRED | DCOILWTICO | daily | 7d | last successful FRED cache | optional |
| macro_usd_broad / usd_broad | FRED | DTWEXBGS | daily | 7d | last successful FRED cache | **广义美元代理**；不得写成 DXY，也不得让 DXY 因代理健康而显示 ok |
| macro_dxy / dxy | ice | — | — | 7d | none | **not_configured**：ICE DXY 未合法稳定接入 |

Each persisted observation keeps `source`, `series/symbol`, `observed_at` (fetch/observation clock), `as_of` (series period), `fetched_at`, `unit`, `frequency`, `status`. `event_time` / `release_date` / `fiscal_period` are not used as the observation clock. Tests assert this contract for CPI, US2Y, VIX, gold, WTI, and the USD broad proxy; DXY stays unavailable.

Failure reasons stay distinct: `source_not_configured`, `upstream_empty`, `record_stale`, `record_invalid`, `query_error`.

## Failure-case tests

| Case | Test |
| --- | --- |
| empty response | `test_parse_fred_observations_empty_list`, `test_sync_empty_observations_is_upstream_empty` |
| timeout | `test_timeout_uses_cache` |
| 429 | `test_429_without_cache_is_error`, `test_429_uses_cache` |
| format change | `test_parse_fred_format_change_is_invalid` |
| stale-cache fallback | `test_timeout_uses_cache`, `test_429_uses_cache` |
| unit / non-numeric error | `test_parse_fred_non_numeric_is_invalid` |
| date / `as_of` error | `test_parse_fred_bad_date_is_invalid`, `test_build_macro_event_does_not_use_period_as_observed_clock` |
| monthly CPI fixture | `test_recorded_monthly_cpi_fixture_is_labeled` |
| daily market series fixture | `test_recorded_fred_fixture_is_labeled` (DGS2) |
| DXY vs proxy split | `test_dxy_never_healthy_when_usd_broad_ok`, `test_sync_reports_dxy_unavailable_even_when_fred_configured` |
| valid bars survive | `test_partition_keeps_valid_historical_bars`, `test_quarantine_without_confirm_does_not_delete` |

## Quarantine scope

Production ingest only **rejects** illegal daily OHLC writes (`invalid_daily_bars_rejected`). `quarantine_invalid_daily_bars(confirm=True)` is an explicit operator repair and is **not** called on collect/startup.

A prior developer-VM cleanup deleted 22 already-invalid daily bars after the snapshot-onto-bar bug. That was a one-time audited repair of unusable rows; valid historical bars were not in that set and are not deleted by ingest or unaudited startup. Those 22 bars are recoverable only by re-fetching split-adjusted daily bars from Alpaca, not by inventing numbers.
