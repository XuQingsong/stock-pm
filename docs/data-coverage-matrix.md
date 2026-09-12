# Phase 4A data coverage matrix

Recorded fixtures in tests are labeled as such. They are not live market prints.

| Dataset / metric | Source | Series / symbol | Refresh | Freshness | Fallback | Current contract |
| --- | --- | --- | --- | --- | --- | --- |
| daily_price_bars / close | Alpaca SIP | NVDA 1d | daily, last completed NY session | 7d | last valid stored OHLC only; never snapshot last onto high/low | split-adjusted; invalid OHLC isolated at ingest; no startup batch-delete |
| earnings_reports / eps | FMP (Nasdaq fallback) | NVDA earnings | on fundamentals job | 120d | existing `synced_at` row | maps `eps_estimate` + `synced_at` as latest consensus |
| earnings_prior_consensus | FMP | n/a | n/a | 120d | none | **gap**: Alpha Vantage not wired; no dated prior snapshot |
| SEC EDGAR | — | — | — | — | — | **not integrated** (status-only; no collector this phase) |
| macro_nfp / nfp | FRED | PAYEMS | calendar + FRED | 45d | last successful FRED cache (`stale`) | existing calendar path |
| macro_cpi / cpi | FRED | CPIAUCSL | monthly | 50d | API key JSON, else official `fredgraph.csv`; last successful cache | official CPI-U index; keyless CSV is first-party stlouisfed.org |
| macro_rates_confirm / us2y | FRED | DGS2 | daily | 14d | API key JSON, else official `fredgraph.csv`; last successful cache | US 2Y Treasury |
| macro_vix / vix | FRED | VIXCLS | daily | 7d | API key JSON, else official `fredgraph.csv`; last successful cache | CBOE VIX via FRED; not Cboe P/C HTML |
| macro_gold / gold | FRED | GOLDPMGBD228NLBM | daily | 7d | API key JSON, else official `fredgraph.csv`; last successful cache | optional; keep this series id; do not substitute another gold series |
| macro_wti / wti | FRED | DCOILWTICO | daily | 7d | API key JSON, else official `fredgraph.csv`; last successful cache | optional |
| macro_broad_usd_proxy / broad_usd_proxy | FRED | DTWEXBGS | daily | 7d | API key JSON, else official `fredgraph.csv`; last successful cache | **广义美元代理**；不得写成 DXY，也不得让 DXY 因代理健康而显示 ok |
| macro_dxy / dxy | ice | — | — | 7d | none | **not_configured / unavailable**：ICE DXY 未合法稳定接入 |

Each persisted observation keeps `source`, `series_or_symbol`, `observed_at` (fetch/observation clock), `as_of` (series period), `fetched_at`, `unit`, `frequency`, `status`. `event_time` / `release_date` / `fiscal_period` are not used as the observation clock. Tests assert this contract for CPI, US2Y, VIX, gold, WTI, and `broad_usd_proxy`; DXY stays unavailable.

Failure reasons stay distinct: `source_not_configured`, `upstream_empty`, `record_stale`, `record_invalid`, `query_error`.

## Failure-case tests (per series)

| Case | CPI | US2Y | VIX | gold | WTI | DXY / proxy |
| --- | --- | --- | --- | --- | --- | --- |
| empty response | `test_empty_response_per_series[cpi]` | `[us2y]` | `[vix]` | `[gold]` | `[wti]` | proxy `[broad_usd_proxy]`; DXY `test_dxy_stays_unavailable_for_every_failure_mode` |
| timeout | `test_timeout_without_cache_per_series` + `test_timeout_uses_stale_cache_per_series` | same | same | same | same | DXY stays not_configured |
| 429 | `test_429_without_cache_per_series` + `test_429_uses_stale_cache_per_series` | same | same | same | same | DXY stays not_configured |
| format change | `test_format_change_per_series` | same | same | same | same | DXY not fetched |
| stale-cache fallback | `test_timeout_uses_stale_cache_per_series`, `test_429_uses_stale_cache_per_series` | same | same | same | same | none |
| unit error | `test_unit_error_per_series[cpi]` | `[us2y]` | `[vix]` | `[gold]` | `[wti]` | `[broad_usd_proxy]` |
| date / as_of error | `test_date_as_of_error_per_series` + `test_build_macro_event_does_not_use_period_as_observed_clock` | same | same | same | same | DXY has no as_of |
| dedicated fixture | `test_monthly_cpi_fixture_is_not_a_daily_generalization` / `test_recorded_monthly_cpi_fixture_is_labeled` | `test_recorded_fred_fixture_is_labeled` | `test_daily_vix_fixture_is_not_dgs2` | `fred_goldpmgbd228nlbm.json` | `fred_dcoilwtico.json` | `fred_dtwexbgs.json` + `test_dxy_never_healthy_when_broad_usd_proxy_ok` |
| official keyless CSV | `test_keyless_uses_official_fredgraph_csv` + `test_api_failure_falls_back_to_official_csv` + `test_keyless_csv_parse_error` | same | same | `test_gold_official_csv_404_is_error_not_substitute` (keep GOLDPMGBD228NLBM) | same | DXY never fetched; proxy uses DTWEXBGS |
| fixture isolation | `test_collect_live_never_reads_test_fixtures` — recorded fixtures must not enter real runtime | | | | | |
| valid bars survive | `test_plan_daily_writes_keeps_valid_history`, `test_twenty_two_invalid_bars_do_not_delete_valid_history`, `test_quarantine_without_confirm_does_not_delete` | | | | | |

## Quarantine scope

Production ingest **rejects** illegal daily OHLC writes and **isolates** a recoverable copy in `price_bar_quarantine`. `isolate_invalid_daily_bars(confirm=True)` copies existing invalid rows into quarantine and **never deletes** live `price_bars`. `quarantine_invalid_daily_bars()` without confirm returns 0 and does not touch the database. Alpaca collect/startup never calls delete.

A prior developer-VM cleanup deleted 22 already-invalid daily bars after the snapshot-onto-bar bug. That was a one-time audited repair of unusable rows; valid historical bars were not in that set and are not deleted by ingest or unaudited startup. Those 22 bars are recoverable only by re-fetching split-adjusted daily bars from Alpaca, not by inventing numbers.
