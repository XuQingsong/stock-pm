from __future__ import annotations

import time
from datetime import date as date_cls, datetime, timezone
from typing import Any

from .calendar import last_trading_day, ny_today, session_status
from .analytics import (
    INTRADAY_MINUTES,
    SUPPORTED_INTERVALS,
    _number,
    earnings_scorecard,
    earnings_summary,
    enrich_chart_bars,
    growth_phase_label,
    ma_position_text,
    money_flow,
    percentile,
    quantile,
    reconstructed_pe_view,
    resample_bars,
    return_1y_pct,
    tape_health,
    volume_profile,
    yoy_from_rows,
)
from .environment import (
    failed_snapshot,
    snapshot_from_row,
    synthesize_symbol_environment,
)
from .errors import DatabaseError
from .tape import (
    SECTOR_THEMES,
    env_tape_conflict_sentence,
    failed_review_note,
    failed_tape,
    review_note_from_row,
    snapshot_from_row as tape_from_row,
    synthesize_review_note,
    synthesize_tape_analysis,
    tape_half_display,
)
from .impact import macro_impact, news_impacts, THEME_NAMES
from .philosophy import (
    build_shell,
    enrich_briefing_row,
    impact_row_thesis,
    quote_quality,
)
from .prediction import (
    OPEN_STATES,
    apply_supersede,
    check_from_row,
    failed_prediction,
    mark_legacy_hit_rate,
    parse_alert_id,
    prediction_badge,
    prediction_hit_rate,
    require_judgment_alert,
    snapshot_from_row as prediction_from_row,
    synthesize_prediction,
    withhold_unsourced_prediction,
)
from .ux_copy import (
    decorate_news_item,
    env_half_display,
    first_env_news,
    sort_attention_rows,
)
from .scoring import sentiment_from_components


WATCHLIST_CACHE_SECONDS = 60.0


EARNINGS_SQL = """
            SELECT
                e.symbol, e.report_date, e.report_timing, e.fiscal_period,
                e.fiscal_year, e.period_end, e.currency, e.eps_actual,
                e.eps_estimate, e.eps_surprise_pct, e.revenue_actual,
                e.revenue_estimate, e.revenue_surprise_pct,
                e.net_income_actual, e.net_income_estimate,
                e.net_income_surprise_pct, e.provider_fields, e.source,
                e.synced_at,
                before_5.close_price AS price_5d_before,
                before_1.close_price AS price_before,
                after_1.close_price AS price_after_1d,
                after_5.close_price AS price_after_5d,
                after_20.close_price AS price_after_20d,
                ROUND(100 * (before_1.close_price / NULLIF(before_5.close_price, 0) - 1), 2)
                    AS pre_5d_return_pct,
                ROUND(100 * (after_1.close_price / NULLIF(before_1.close_price, 0) - 1), 2)
                    AS post_1d_return_pct,
                ROUND(100 * (after_5.close_price / NULLIF(before_1.close_price, 0) - 1), 2)
                    AS post_5d_return_pct,
                ROUND(100 * (after_20.close_price / NULLIF(before_1.close_price, 0) - 1), 2)
                    AS post_20d_return_pct
            FROM earnings_reports e
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN e.report_timing IN ('before_market', 'during_market')
                        THEN e.report_date
                    ELSE e.report_date + 1
                END AS reaction_date
            ) event
            LEFT JOIN LATERAL (
                SELECT close_price FROM daily_price_bars
                WHERE symbol = e.symbol AND bar_size = '1d'
                  AND bar_time::date < event.reaction_date
                ORDER BY bar_time DESC OFFSET 4 LIMIT 1
            ) before_5 ON TRUE
            LEFT JOIN LATERAL (
                SELECT close_price FROM daily_price_bars
                WHERE symbol = e.symbol AND bar_size = '1d'
                  AND bar_time::date < event.reaction_date
                ORDER BY bar_time DESC LIMIT 1
            ) before_1 ON TRUE
            LEFT JOIN LATERAL (
                SELECT close_price FROM daily_price_bars
                WHERE symbol = e.symbol AND bar_size = '1d'
                  AND bar_time::date >= event.reaction_date
                ORDER BY bar_time ASC LIMIT 1
            ) after_1 ON TRUE
            LEFT JOIN LATERAL (
                SELECT close_price FROM daily_price_bars
                WHERE symbol = e.symbol AND bar_size = '1d'
                  AND bar_time::date >= event.reaction_date
                ORDER BY bar_time ASC OFFSET 4 LIMIT 1
            ) after_5 ON TRUE
            LEFT JOIN LATERAL (
                SELECT close_price FROM daily_price_bars
                WHERE symbol = e.symbol AND bar_size = '1d'
                  AND bar_time::date >= event.reaction_date
                ORDER BY bar_time ASC OFFSET 19 LIMIT 1
            ) after_20 ON TRUE
            WHERE e.symbol = ANY(%s)
              AND e.report_date >= CURRENT_DATE - INTERVAL '1 year'
            ORDER BY e.report_date DESC
"""

TECHNICAL_SQL = """
            WITH daily AS (
                SELECT
                    symbol, bar_time, close_price, high_price, low_price, volume,
                    LAG(close_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                    ) AS previous_close,
                    LAG(close_price, 5) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                    ) AS close_5d_ago,
                    LAG(close_price, 20) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                    ) AS close_20d_ago,
                    LAG(close_price, 50) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                    ) AS close_50d_ago,
                    LAG(close_price, 251) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                    ) AS close_252d_ago
                FROM daily_price_bars
                WHERE bar_size = '1d' AND symbol = ANY(%s)
            ), averages AS (
                SELECT
                    *,
                    AVG(close_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS ma5,
                    AVG(close_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS ma20,
                    AVG(close_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
                    ) AS ma50,
                    AVG(close_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 199 PRECEDING AND CURRENT ROW
                    ) AS ma200,
                    MAX(high_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                    ) AS prior_high_20,
                    MAX(high_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING
                    ) AS prior_high_50,
                    MAX(high_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS high_52w,
                    MIN(low_price) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                    ) AS low_52w,
                    AVG(volume) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS avg_volume_20,
                    AVG(GREATEST(close_price - previous_close, 0)) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                    ) AS avg_gain_14,
                    AVG(GREATEST(previous_close - close_price, 0)) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                    ) AS avg_loss_14,
                    STDDEV_SAMP(100 * (close_price / NULLIF(previous_close, 0) - 1)) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS daily_volatility_20,
                    COUNT(*) OVER (
                        PARTITION BY symbol ORDER BY bar_time
                        ROWS BETWEEN 199 PRECEDING AND CURRENT ROW
                    ) AS observations
                FROM daily
            ), signals AS (
                SELECT
                    *,
                    LAG(ma20) OVER (PARTITION BY symbol ORDER BY bar_time) AS previous_ma20,
                    LAG(ma50) OVER (PARTITION BY symbol ORDER BY bar_time) AS previous_ma50
                FROM averages
            ), latest AS (
                SELECT DISTINCT ON (symbol) *
                FROM signals
                ORDER BY symbol, bar_time DESC
            )
            SELECT
                symbol, bar_time, close_price, ma5, ma20, ma50,
                CASE WHEN observations >= 200 THEN ma200 END AS ma200,
                ROUND(100 * (close_price / NULLIF(ma20, 0) - 1), 2) AS distance_ma20_pct,
                CASE WHEN observations >= 200
                    THEN ROUND(100 * (close_price / NULLIF(ma200, 0) - 1), 2)
                END AS distance_ma200_pct,
                ROUND(100 * (close_price / NULLIF(previous_close, 0) - 1), 2) AS return_1d_pct,
                ROUND(100 * (close_price / NULLIF(close_5d_ago, 0) - 1), 2) AS return_5d_pct,
                ROUND(100 * (close_price / NULLIF(close_20d_ago, 0) - 1), 2) AS return_20d_pct,
                ROUND(100 * (close_price / NULLIF(close_50d_ago, 0) - 1), 2) AS return_50d_pct,
                ROUND(100 * (close_price / NULLIF(close_252d_ago, 0) - 1), 2) AS return_1y_pct,
                ROUND(
                    CASE
                        WHEN avg_loss_14 = 0 AND avg_gain_14 > 0 THEN 100
                        WHEN avg_loss_14 = 0 THEN NULL
                        ELSE 100 - 100 / (1 + avg_gain_14 / avg_loss_14)
                    END,
                    2
                ) AS rsi14,
                ROUND((daily_volatility_20 * SQRT(252))::numeric, 2)
                    AS annualized_volatility_pct,
                ROUND(volume / NULLIF(avg_volume_20, 0), 2) AS volume_ratio_20d,
                ROUND(100 * (close_price / NULLIF(high_52w, 0) - 1), 2) AS distance_52w_high_pct,
                ROUND(100 * (close_price / NULLIF(low_52w, 0) - 1), 2) AS distance_52w_low_pct,
                (close_price > ma20 AND previous_close <= previous_ma20) AS crossed_up_ma20,
                (close_price < ma20 AND previous_close >= previous_ma20) AS crossed_down_ma20,
                (close_price > ma50 AND previous_close <= previous_ma50) AS crossed_up_ma50,
                (close_price >= prior_high_20) AS new_high_20d,
                (close_price >= prior_high_50) AS new_high_50d,
                (ma5 > ma20 AND ma20 > ma50 AND ma50 > ma200 AND observations >= 200)
                    AS bullish_alignment,
                CASE
                    WHEN avg_loss_14 > 0
                         AND 100 - 100 / (1 + avg_gain_14 / avg_loss_14) >= 75
                        THEN 'RSI偏热'
                    WHEN close_price >= prior_high_50 THEN '50日新高'
                    WHEN close_price >= prior_high_20 THEN '20日新高'
                    WHEN close_price > ma20 AND previous_close <= previous_ma20 THEN '上穿20日线'
                    WHEN close_price < ma20 AND previous_close >= previous_ma20 THEN '下穿20日线'
                    WHEN close_price > ma50 AND previous_close <= previous_ma50 THEN '上穿50日线'
                    WHEN ma5 > ma20 AND ma20 > ma50 AND ma50 > ma200
                         AND observations >= 200 THEN '均线多头排列'
                    ELSE '暂无关键突破'
                END AS signal
            FROM latest
            ORDER BY symbol
"""


class QueryMixin:
    def watchlist_rows(self, include_inactive: bool = False) -> list[dict]:
        cached_at, rows = getattr(self, "_watchlist_cache", (0.0, []))
        if not rows or time.monotonic() - cached_at > WATCHLIST_CACHE_SECONDS:
            rows = self.fetch_all(
                """
                SELECT symbol, name, primary_exchange, asset_class, sector,
                       themes, rate_sensitivity, active, added_at
                FROM watchlist
                ORDER BY symbol
                """
            )
            self._watchlist_cache = (time.monotonic(), rows)
        if include_inactive:
            return rows
        return [row for row in rows if row["active"]]

    def active_symbols(self) -> list[str]:
        return [row["symbol"] for row in self.watchlist_rows()]

    def active_stock_symbols(self) -> list[str]:
        return [row["symbol"] for row in self.watchlist_rows() if str(row.get("asset_class") or "") == "stocks"]

    def active_etf_symbols(self) -> list[str]:
        return [row["symbol"] for row in self.watchlist_rows() if str(row.get("asset_class") or "") == "etf"]

    def theme_symbols(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for row in self.watchlist_rows():
            for theme in row["themes"] or []:
                mapping.setdefault(theme, []).append(row["symbol"])
        return mapping

    def _watchlist_symbols(self, symbols: list[str] | None = None) -> list[str]:
        active = self.active_symbols()
        requested = [symbol.upper() for symbol in (symbols or active)]
        unknown = sorted(set(requested) - set(active))
        if unknown:
            raise ValueError(f"Unknown watchlist symbols: {', '.join(unknown)}")
        return requested

    def _watchlist_symbol(self, symbol: str) -> str:
        return self._watchlist_symbols([symbol])[0]

    def latest_snapshots(self, symbols: list[str] | None = None) -> list[dict]:
        requested = self._watchlist_symbols(symbols)
        rows = self.fetch_all(
            """
            SELECT DISTINCT ON (symbol)
                symbol, contract_id, captured_at, last_price, bid, ask,
                open_price, high_price, low_price, prior_close, volume, halted,
                source, raw_data->>'delayed' AS delayed
            FROM market_snapshots
            WHERE symbol = ANY(%s)
            ORDER BY symbol, captured_at DESC
            """,
            (requested,),
        )
        by_symbol = {row["symbol"]: row for row in rows}
        result = []
        for symbol in requested:
            row = by_symbol.get(symbol)
            if not row:
                continue
            quality = quote_quality(row)
            row["quote_quality"] = quality
            row["displayed_last_price"] = (
                None if quality["hide_last_price"] else row.get("last_price")
            )
            result.append(row)
        return result

    def live_signals(self, symbols: list[str] | None = None) -> list[dict]:
        requested = self._watchlist_symbols(symbols)
        rows = self.fetch_all(
            """
            WITH ranked AS (
                SELECT symbol, bar_time, close_price, high_price, low_price, volume,
                       source,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY bar_time DESC) rn
                FROM price_bars
                WHERE bar_size = '1m' AND symbol = ANY(%s)
            ), stats AS (
                SELECT symbol,
                       MAX(bar_time) FILTER (WHERE rn = 1) AS bar_time,
                       MAX(close_price) FILTER (WHERE rn = 1) AS last_price,
                       MAX(source) FILTER (WHERE rn = 1) AS source,
                       SUM(close_price * volume) FILTER (WHERE rn <= 60)
                         / NULLIF(SUM(volume) FILTER (WHERE rn <= 60), 0) AS vwap_60m,
                       MAX(high_price) FILTER (WHERE rn BETWEEN 2 AND 21) AS prior_high_20m,
                       MIN(low_price) FILTER (WHERE rn BETWEEN 2 AND 21) AS prior_low_20m,
                       MAX(volume) FILTER (WHERE rn = 1) AS latest_volume,
                       AVG(volume) FILTER (WHERE rn BETWEEN 2 AND 21) AS avg_volume_20m,
                       COUNT(*) FILTER (WHERE rn <= 60) AS bars
                FROM ranked
                WHERE rn <= 60
                GROUP BY symbol
            )
            SELECT symbol, bar_time, last_price, source, bars,
                   ROUND(vwap_60m, 4) AS vwap_60m,
                   prior_high_20m, prior_low_20m,
                   ROUND(latest_volume / NULLIF(avg_volume_20m, 0), 2) AS volume_ratio_20m,
                   CASE
                     WHEN last_price > prior_high_20m THEN '向上突破20分钟高点'
                     WHEN last_price < prior_low_20m THEN '向下跌破20分钟低点'
                     WHEN last_price > vwap_60m THEN 'VWAP上方'
                     WHEN last_price < vwap_60m THEN 'VWAP下方'
                     ELSE '观察'
                   END AS signal
            FROM stats
            ORDER BY symbol
            """,
            (requested,),
        )
        by_symbol = {row["symbol"]: row for row in rows}
        return [by_symbol[symbol] for symbol in requested if symbol in by_symbol]

    def history(self, symbol: str, limit: int = 400, bar_size: str = "1d") -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        if bar_size not in {"1d", "1m"}:
            raise ValueError("bar_size must be 1d or 1m")
        table = "daily_price_bars" if bar_size == "1d" else "price_bars"
        return self.fetch_all(
            f"""
            SELECT symbol, bar_size, bar_time, open_price, high_price,
                   low_price, close_price, volume
            FROM {table}
            WHERE symbol = %s AND bar_size = %s
            ORDER BY bar_time DESC
            LIMIT %s
            """,
            (normalized, bar_size, limit),
        )

    def latest_daily_bar(self, symbol: str) -> dict | None:
        from .bars import decorate_bar
        from .fetch import utc_now

        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT symbol, bar_size, bar_time, open_price, high_price,
                   low_price, close_price, volume, source, raw_data
            FROM daily_price_bars
            WHERE symbol = %s AND bar_size = '1d'
            ORDER BY bar_time DESC
            LIMIT 1
            """,
            (normalized,),
        )
        if not rows:
            return None
        return decorate_bar(rows[0], fetched_at=utc_now(), source=str(rows[0].get("source") or "alpaca"))

    def latest_earnings_row(self, symbol: str) -> dict | None:
        rows = self.fetch_all(
            """
            SELECT symbol, report_date, report_timing, fiscal_period, fiscal_year,
                   period_end, currency, eps_actual, eps_estimate, eps_surprise_pct,
                   revenue_actual, revenue_estimate, revenue_surprise_pct,
                   net_income_actual, net_income_estimate, net_income_surprise_pct,
                   provider_fields, source, synced_at
            FROM earnings_reports
            WHERE symbol = %s
            ORDER BY report_date DESC
            LIMIT 1
            """,
            (self._watchlist_symbol(symbol),),
        )
        return rows[0] if rows else None

    def latest_macro_event(self, event_type: str) -> dict | None:
        rows = self.fetch_all(
            """
            SELECT event_type, event_time, name, actual, consensus, prior,
                   unit, surprise, confirmed, source, notes
            FROM macro_events
            WHERE event_type = %s
            ORDER BY event_time DESC
            LIMIT 1
            """,
            (event_type,),
        )
        return rows[0] if rows else None

    def latest_positions(self) -> list[dict]:
        return self.fetch_all(
            """
            SELECT contract_id, symbol, description, asset_class, currency,
                   quantity, average_price, market_price, market_value,
                   daily_pnl, unrealized_pnl, captured_at
            FROM position_snapshots
            WHERE captured_at = (SELECT MAX(captured_at) FROM position_snapshots)
            ORDER BY market_value DESC NULLS LAST
            """
        )

    def trades(self, limit: int = 200) -> list[dict]:
        return self.fetch_all(
            """
            SELECT trade_id, symbol, trade_time, side, quantity, price,
                   commission, realized_pnl, currency, exchange, company_name
            FROM trades
            ORDER BY trade_time DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )

    def latest_account(self) -> dict | None:
        rows = self.fetch_all(
            """
            SELECT captured_at, currency, net_liquidation, total_cash_value,
                   gross_position_value, available_funds, buying_power,
                   maintenance_margin, excess_liquidity
            FROM account_snapshots
            ORDER BY captured_at DESC
            LIMIT 1
            """
        )
        return rows[0] if rows else None

    def sync_status(self) -> dict | None:
        rows = self.fetch_all(
            """
            SELECT id, source, started_at, completed_at, status, item_counts, error
            FROM sync_runs
            ORDER BY completed_at DESC
            LIMIT 1
            """
        )
        return rows[0] if rows else None

    def technical_summary(self, symbols: list[str] | None = None) -> list[dict]:
        requested = self._watchlist_symbols(symbols)
        return self.fetch_all(TECHNICAL_SQL, (requested,))

    def latest_fundamentals(self, symbol: str) -> dict | None:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT symbol, captured_at, currency, market_cap, enterprise_value,
                   pe_ttm, pe_forward, peg_ratio, price_to_book, price_to_sales,
                   ev_to_ebitda, eps_ttm, revenue_ttm, gross_margin_pct,
                   operating_margin_pct, net_margin_pct, revenue_growth_yoy_pct,
                   eps_growth_yoy_pct, dividend_yield_pct, beta,
                   analyst_target_price, source
            FROM fundamentals_snapshots
            WHERE symbol = %s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (normalized,),
        )
        return rows[0] if rows else None

    def earnings_history(self, symbol: str) -> list[dict]:
        return self.fetch_all(EARNINGS_SQL, ([self._watchlist_symbol(symbol)],))

    def recent_earnings(self, limit: int = 8) -> list[dict]:
        return self.fetch_all(EARNINGS_SQL, (self.active_symbols(),))[:limit]

    def sentiment_summary(self, symbol: str) -> dict:
        normalized = self._watchlist_symbol(symbol)
        news = self.fetch_all(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive,
                   COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral,
                   COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative
            FROM news_articles
            WHERE symbol = %s
              AND published_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
            """,
            (normalized,),
        )[0]
        options = self.fetch_all(
            """
            WITH latest AS (
                SELECT MAX(captured_at) AS captured_at
                FROM option_wall_snapshots WHERE symbol = %s
            )
            SELECT SUM(call_open_interest) AS call_oi,
                   SUM(put_open_interest) AS put_oi,
                   SUM(call_volume) AS call_volume,
                   SUM(put_volume) AS put_volume
            FROM option_wall_snapshots o, latest l
            WHERE o.symbol = %s AND o.captured_at = l.captured_at
            """,
            (normalized, normalized),
        )[0]
        prices = self.fetch_all(
            """
            SELECT close_price FROM daily_price_bars
            WHERE symbol = %s AND bar_size = '1d'
            ORDER BY bar_time DESC LIMIT 21
            """,
            (normalized,),
        )
        return {"symbol": normalized, **sentiment_from_components(news, options, prices)}

    def investment_overview(self, symbol: str) -> dict:
        normalized = self._watchlist_symbol(symbol)
        technical = self.technical_summary([normalized])
        return {
            "symbol": normalized,
            "technical": technical[0] if technical else None,
            "sentiment": self.sentiment_summary(normalized),
            "valuation": self.latest_fundamentals(normalized),
            "earnings": self.earnings_history(normalized),
            "thesis": self.fundamentals_thesis_view(normalized),
        }

    def decision_bundle(self, symbol: str) -> dict:
        from .decision.clock import classify_macros, dataset_as_of, macro_window

        normalized = self._watchlist_symbol(symbol)
        watch = next(
            (row for row in self.watchlist_rows() if row["symbol"] == normalized),
            {"symbol": normalized, "themes": [], "rate_sensitivity": "medium"},
        )
        from .bars import decorate_bar, usable_daily_bars
        from .series import decorate_macro_row, map_earnings_health

        raw_bars = self.fetch_all(
            """
            SELECT symbol, bar_size, bar_time, open_price, high_price,
                   low_price, close_price, volume, source, raw_data
            FROM daily_price_bars
            WHERE symbol = %s AND bar_size = '1d'
            ORDER BY bar_time DESC
            LIMIT 8
            """,
            (normalized,),
        )
        fetched = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        bars_all = [
            decorate_bar(
                row,
                fetched_at=fetched,
                source=str(row.get("source") or "alpaca"),
            )
            for row in raw_bars
        ]
        bars = usable_daily_bars(bars_all)
        earnings = [map_earnings_health(row) for row in self.earnings_history(normalized)[:4]]
        macros = [
            decorate_macro_row(row)
            for row in self.fetch_all(
                """
                SELECT event_type, event_time, name, actual, consensus, prior,
                       unit, surprise, confirmed, source, notes
                FROM macro_events
                ORDER BY event_time DESC
                LIMIT 200
                """
            )
        ]
        clock = dataset_as_of(bars=bars, earnings=earnings, macros=macros)
        parts = classify_macros(macros, clock)
        window = None
        if clock is not None:
            start, end = macro_window(clock)
            window = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "dataset_as_of": clock.isoformat(),
            }
        return {
            "symbol": normalized,
            "watch": watch,
            "bars": bars,
            "bars_rejected": [row for row in bars_all if row not in bars],
            "earnings": earnings,
            "fundamentals": self.latest_fundamentals(normalized),
            "macro_events": parts.inside,
            "macro_events_stale": parts.stale,
            "macro_events_window_mismatch": parts.mismatch,
            "macro_events_scheduled": parts.scheduled,
            "macro_window": window,
            "clock_status": "ok" if clock is not None else "clock_insufficient",
            "news": self.news([normalized], 12),
            "cboe": self.cboe_option_stats(),
            "synthetic": False,
        }

    def chart_history(
        self, symbol: str, limit: int = 260, interval: str = "1d"
    ) -> dict:
        normalized = self._watchlist_symbol(symbol)
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(
                "interval must be one of 1m, 5m, 15m, 60m, 1d, 1w, 1M"
            )
        if interval in INTRADAY_MINUTES:
            factor = INTRADAY_MINUTES[interval]
            raw_limit = min(5000, max(limit * factor, 120))
            rows = self.fetch_all(
                """
                SELECT symbol, bar_time, open_price, high_price, low_price,
                       close_price, volume, source
                FROM price_bars
                WHERE symbol = %s AND bar_size = '1m'
                ORDER BY bar_time DESC
                LIMIT %s
                """,
                (normalized, raw_limit),
            )
        else:
            factor = 1 if interval == "1d" else 7 if interval == "1w" else 31
            raw_limit = min(1500, max(limit * factor, 60))
            rows = self.fetch_all(
                """
                SELECT symbol, bar_time, open_price, high_price, low_price,
                       close_price, volume, source
                FROM daily_price_bars
                WHERE symbol = %s AND bar_size = '1d'
                ORDER BY bar_time DESC
                LIMIT %s
                """,
                (normalized, raw_limit),
            )
        chronological = list(reversed(rows))
        sampled = resample_bars(chronological, interval)[-limit:]
        enriched = enrich_chart_bars(sampled)
        latest = enriched[-1] if enriched else None
        technical = self.technical_summary([normalized])
        daily_ma = None
        if technical:
            daily_ma = {
                "ma5": technical[0].get("ma5"),
                "ma20": technical[0].get("ma20"),
                "ma50": technical[0].get("ma50"),
                "ma200": technical[0].get("ma200"),
            }
        return {
            "symbol": normalized,
            "interval": interval,
            "bars": enriched,
            "as_of": latest["bar_time"] if latest else None,
            "source": latest.get("source") if latest else None,
            "delayed": interval in INTRADAY_MINUTES,
            "daily_ma": daily_ma,
        }

    def earnings_summary_view(self, symbol: str) -> dict:
        rows = self._prefer_earnings_rows(self.earnings_history(symbol))
        reported = [
            row for row in rows
            if row.get("eps_actual") is not None or row.get("revenue_actual") is not None
        ]
        summary = earnings_summary(reported)
        latest = summary["latest"]
        from .config import Settings

        provider_name = "fmp" if Settings().fmp_api_key else "nasdaq"
        source = str((latest or {}).get("source") or "")
        missing = []
        if latest:
            if latest.get("revenue_actual") is None:
                missing.append("营收")
            if latest.get("net_income_actual") is None:
                missing.append("净利润")
            if provider_name != "fmp" and latest.get("net_income_estimate") is None:
                missing.append("净利润预期")
        status = "ok" if provider_name == "fmp" else "partial"
        if provider_name == "fmp" and latest and "FMP" not in source:
            status = "stale"
        message = (
            "营收/EPS 来自 FMP；净利润实际值来自利润表，净利润预期需更高套餐，未作估算"
            if provider_name == "fmp"
            else "当前使用 Nasdaq 免费源，营收与净利润显示为未提供"
        )
        if missing:
            message += f"。缺失：{'、'.join(missing)}"
        return {
            **summary,
            "provider": {"name": provider_name, "status": status, "message": message},
            "thesis": self.fundamentals_thesis_view(symbol),
        }

    def _prefer_earnings_rows(self, rows: list[dict]) -> list[dict]:
        """Keep one row per report date, preferring FMP and more complete fields."""
        chosen: dict[str, dict] = {}
        for row in rows:
            key = str(row.get("report_date") or "")[:10]
            if not key:
                continue
            existing = chosen.get(key)
            if existing is None or self._earnings_row_score(row) > self._earnings_row_score(existing):
                chosen[key] = row
        return sorted(
            chosen.values(),
            key=lambda item: str(item.get("report_date")),
            reverse=True,
        )

    @staticmethod
    def _earnings_row_score(row: dict) -> tuple:
        source = str(row.get("source") or "")
        filled = sum(
            row.get(key) is not None
            for key in ("revenue_actual", "net_income_actual", "eps_actual", "eps_estimate")
        )
        return (1 if "FMP" in source else 0, filled)

    def valuation_history(self, symbol: str, limit: int = 260) -> dict:
        normalized = self._watchlist_symbol(symbol)
        series = self.fetch_all(
            """
            SELECT captured_at, pe_ttm, pe_forward, price_to_book, price_to_sales
            FROM fundamentals_snapshots
            WHERE symbol = %s
            ORDER BY captured_at
            LIMIT %s
            """,
            (normalized, limit),
        )
        pe_values = [float(row["pe_ttm"]) for row in series if row.get("pe_ttm") is not None]
        current = self.latest_fundamentals(normalized)
        pe_current = float(current["pe_ttm"]) if current and current.get("pe_ttm") is not None else (
            pe_values[-1] if pe_values else None
        )
        enough = len(pe_values) >= 8
        thesis = self.fundamentals_thesis_view(normalized)
        reconstructed = thesis.get("valuation") or {}
        return {
            "current": current,
            "series": series,
            "metrics": {
                "pe_percentile": reconstructed.get("pe_percentile")
                if reconstructed.get("pe_percentile") is not None
                else (percentile(pe_values, pe_current) if pe_current is not None else None),
                "pe_low": reconstructed.get("pe_low") if reconstructed.get("pe_low") is not None else (
                    quantile(pe_values, 0.1) if enough else None
                ),
                "pe_high": reconstructed.get("pe_high") if reconstructed.get("pe_high") is not None else (
                    quantile(pe_values, 0.9) if enough else None
                ),
                "samples": reconstructed.get("samples") or len(pe_values),
                "label": reconstructed.get("label"),
                "basis": reconstructed.get("basis"),
            },
            "coverage": {
                "from": series[0]["captured_at"] if series else None,
                "to": series[-1]["captured_at"] if series else None,
                "count": len(series),
                "band_ready": enough or (reconstructed.get("samples") or 0) >= 8,
            },
            "thesis": thesis,
        }

    def volume_profile_view(self, symbol: str, lookback: int = 60) -> dict:
        normalized = self._watchlist_symbol(symbol)
        bars = self.fetch_all(
            """
            SELECT bar_time, open_price, high_price, low_price, close_price, volume
            FROM daily_price_bars
            WHERE symbol = %s
            ORDER BY bar_time DESC
            LIMIT %s
            """,
            (normalized, lookback),
        )
        profile = volume_profile(bars, latest_first=True)
        return {
            **profile,
            "lookback": lookback,
            "basis": "OHLCV估算",
            "disclaimer": "按日K高低价区间分摊成交量，不是交易所披露的持仓成本或主力筹码。",
        }

    def capital_flow_view(self, symbol: str, days: int = 5) -> dict:
        from .config import Settings

        normalized = self._watchlist_symbol(symbol)
        trades = self.fetch_all(
            """
            SELECT trade_time, notional, side_inferred
            FROM large_trades
            WHERE symbol = %s
              AND trade_time >= CURRENT_TIMESTAMP - make_interval(days => %s)
            ORDER BY trade_time
            """,
            (normalized, days),
        )
        tiers = [
            {"name": "20–50万", "min_notional": 200_000, "max_notional": 500_000},
            {"name": "50–100万", "min_notional": 500_000, "max_notional": 1_000_000},
            {"name": "100万以上", "min_notional": 1_000_000, "max_notional": None},
        ]
        summarized = []
        for tier in tiers:
            buy = sell = 0.0
            count = 0
            for trade in trades:
                notional = float(trade["notional"] or 0)
                if notional < tier["min_notional"]:
                    continue
                if tier["max_notional"] is not None and notional >= tier["max_notional"]:
                    continue
                count += 1
                if trade["side_inferred"] == "buy":
                    buy += notional
                elif trade["side_inferred"] == "sell":
                    sell += notional
            summarized.append(
                {
                    **tier,
                    "buy_notional": round(buy, 2),
                    "sell_notional": round(sell, 2),
                    "net_notional": round(buy - sell, 2),
                    "count": count,
                }
            )
        by_day: dict[str, dict] = {}
        for trade in trades:
            day = str(trade["trade_time"])[:10]
            entry = by_day.setdefault(day, {"date": day, "buy_notional": 0.0, "sell_notional": 0.0})
            notional = float(trade["notional"] or 0)
            if trade["side_inferred"] == "buy":
                entry["buy_notional"] += notional
            elif trade["side_inferred"] == "sell":
                entry["sell_notional"] += notional
        timeline = [
            {
                **row,
                "buy_notional": round(row["buy_notional"], 2),
                "sell_notional": round(row["sell_notional"], 2),
                "net_notional": round(row["buy_notional"] - row["sell_notional"], 2),
            }
            for row in sorted(by_day.values(), key=lambda item: item["date"])
        ]
        daily = self.fetch_all(
            """
            SELECT bar_time, open_price, high_price, low_price, close_price, volume
            FROM daily_price_bars
            WHERE symbol = %s
            ORDER BY bar_time DESC
            LIMIT 40
            """,
            (normalized,),
        )
        flow = money_flow(daily)
        threshold = Settings().large_trade_notional
        return {
            "tiers": summarized,
            "timeline": timeline,
            **flow,
            "disclaimer": (
                f"仅统计单笔金额 ≥ ${threshold:,.0f} 的成交；买卖方向由 tick rule 推断，"
                "不能识别机构或散户身份，普通小单不计入方向统计。"
            ),
        }

    def intraday_history(self, symbol: str, limit: int = 600) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT symbol, bar_time, open_price, high_price, low_price,
                   close_price, volume, source
            FROM price_bars
            WHERE symbol = %s AND bar_size = '1m'
              AND bar_time >= (
                  SELECT MAX(bar_time) - INTERVAL '16 hours'
                  FROM price_bars
                  WHERE symbol = %s AND bar_size = '1m'
              )
            ORDER BY bar_time DESC
            LIMIT %s
            """,
            (normalized, normalized, limit),
        )
        return list(reversed(rows))

    def market_events(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        params: tuple[Any, ...]
        if symbol:
            where = "WHERE symbol = %s"
            params = (self._watchlist_symbol(symbol), limit)
        else:
            where = ""
            params = (limit,)
        return self.fetch_all(
            f"""
            SELECT symbol, event_time, event_type, severity, title,
                   details, source, detected_at
            FROM market_events
            {where}
            ORDER BY event_time DESC
            LIMIT %s
            """,
            params,
        )

    def latest_reviews(self, symbol: str | None = None) -> list[dict]:
        if symbol:
            return self.fetch_all(
                """SELECT * FROM daily_reviews WHERE symbol = %s
                   ORDER BY review_date DESC LIMIT 1""",
                (self._watchlist_symbol(symbol),),
            )
        return self.fetch_all(
            """
            SELECT DISTINCT ON (symbol) * FROM daily_reviews
            ORDER BY symbol, review_date DESC
            """
        )

    def option_wall(self, symbol: str) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        return self.fetch_all(
            """
            WITH latest AS (
                SELECT MAX(captured_at) AS captured_at
                FROM option_wall_snapshots
                WHERE symbol = %s
            ), expiry AS (
                SELECT MIN(expiration_date) AS expiration_date
                FROM option_wall_snapshots o, latest
                WHERE o.symbol = %s
                  AND o.captured_at = latest.captured_at
                  AND o.expiration_date >= CURRENT_DATE
            )
            SELECT o.symbol, o.expiration_date, o.strike, o.captured_at,
                   o.spot_price, o.call_last, o.call_bid, o.call_ask,
                   o.call_volume, o.call_open_interest, o.call_implied_volatility,
                   o.put_last, o.put_bid, o.put_ask, o.put_volume,
                   o.put_open_interest, o.put_implied_volatility
            FROM option_wall_snapshots o, latest l, expiry e
            WHERE o.symbol = %s
              AND o.captured_at = l.captured_at
              AND o.expiration_date = e.expiration_date
            ORDER BY o.strike
            """,
            (normalized, normalized, normalized),
        )

    def news(self, symbols: list[str] | None = None, limit: int = 60) -> list[dict]:
        requested = self._watchlist_symbols(symbols)
        rows = self.fetch_all(
            """
            SELECT symbol, headline, summary, source, published_at, url,
                   sentiment, themes
            FROM news_articles
            WHERE symbol = ANY(%s)
            ORDER BY published_at DESC NULLS LAST
            LIMIT %s
            """,
            (requested, limit),
        )
        mapping = self.theme_symbols()
        for row in rows:
            themes = list(row.get("themes") or [])
            row["theme_names"] = [THEME_NAMES.get(theme, theme) for theme in themes]
            row["impacts"] = news_impacts(row, mapping)
            decorate_news_item(row)
        return rows

    def segments(self, symbol: str, date: str | None = None) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        if date:
            return self.fetch_all(
                """
                SELECT * FROM intraday_segments
                WHERE symbol = %s AND trade_date = %s
                ORDER BY seg_no
                """,
                (normalized, date),
            )
        return self.fetch_all(
            """
            SELECT * FROM intraday_segments
            WHERE symbol = %s AND trade_date = (
                SELECT MAX(trade_date) FROM intraday_segments WHERE symbol = %s
            )
            ORDER BY seg_no
            """,
            (normalized, normalized),
        )

    def segments_by_date(self, date: str) -> list[dict]:
        return self.fetch_all(
            """
            SELECT * FROM intraday_segments
            WHERE trade_date = %s
            ORDER BY symbol, seg_no
            """,
            (date,),
        )

    def segments_between(self, symbol: str, start: str, end: str) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        return self.fetch_all(
            """
            SELECT * FROM intraday_segments
            WHERE symbol = %s AND trade_date >= %s AND trade_date <= %s
            ORDER BY trade_date, seg_no
            """,
            (normalized, start, end),
        )

    def reviews_between(self, symbol: str, start: str, end: str) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        return self.fetch_all(
            """
            SELECT * FROM daily_reviews
            WHERE symbol = %s AND review_date >= %s AND review_date <= %s
            ORDER BY review_date DESC
            """,
            (normalized, start, end),
        )

    def segment_dates(self, symbol: str) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        return self.fetch_all(
            """
            SELECT DISTINCT trade_date FROM intraday_segments
            WHERE symbol = %s ORDER BY trade_date DESC LIMIT 30
            """,
            (normalized,),
        )

    def large_trades(
        self,
        symbol: str,
        date: str | None = None,
        min_notional: float | None = None,
        limit: int = 500,
    ) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        clauses = ["symbol = %s"]
        params: list[Any] = [normalized]
        if date:
            clauses.append("trade_time::date = %s")
            params.append(date)
        if min_notional:
            clauses.append("notional >= %s")
            params.append(min_notional)
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT symbol, trade_time, price, size, notional, side_inferred, exchange
            FROM large_trades
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_time DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def reviews_by_date(self, date: str) -> list[dict]:
        return self.fetch_all(
            "SELECT * FROM daily_reviews WHERE review_date = %s ORDER BY symbol",
            (date,),
        )

    def latest_review_date(self) -> str | None:
        rows = self.fetch_all("SELECT MAX(review_date) AS review_date FROM daily_reviews")
        value = rows[0]["review_date"] if rows else None
        return str(value) if value else None

    def latest_bar_date(self) -> str | None:
        rows = self.fetch_all(
            """
            SELECT MAX((bar_time AT TIME ZONE 'America/New_York')::date) AS bar_date
            FROM price_bars
            WHERE bar_size = '1d'
            """
        )
        value = rows[0]["bar_date"] if rows else None
        return str(value) if value else None

    def default_review_date(self) -> str:
        return (
            self.latest_review_date()
            or self.latest_bar_date()
            or last_trading_day(ny_today()).isoformat()
        )

    def market_session(self, trade_date: str | None = None) -> dict:
        requested = date_cls.fromisoformat(trade_date) if trade_date else ny_today()
        info = session_status(requested)
        review_count = len(self.reviews_by_date(requested.isoformat()))
        previous = last_trading_day(requested)
        status = "closed"
        if info["is_trading_day"]:
            status = "reviewed" if review_count else "open"
        return {
            "date": requested.isoformat(),
            "is_trading_day": bool(info["is_trading_day"]),
            "status": status,
            "reason": info["reason"],
            "holiday_name": info["holiday_name"],
            "label": info["label"],
            "last_trading_date": previous.isoformat(),
            "default_review_date": self.default_review_date(),
            "has_reviews": review_count > 0,
            "review_count": review_count,
        }

    def review_row(self, symbol: str, review_date: str) -> dict | None:
        rows = self.fetch_all(
            """SELECT * FROM daily_reviews
               WHERE symbol = %s AND review_date = %s""",
            (self._watchlist_symbol(symbol), review_date),
        )
        return rows[0] if rows else None

    def news_on_date(self, symbol: str, date: str) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT symbol, headline, summary, source, published_at, url,
                   sentiment, themes
            FROM news_articles
            WHERE symbol = %s
              AND COALESCE((published_at AT TIME ZONE 'America/New_York')::date,
                           published_at::date) = %s
            ORDER BY published_at DESC NULLS LAST
            """,
            (normalized, date),
        )
        mapping = self.theme_symbols()
        for row in rows:
            themes = list(row.get("themes") or [])
            row["theme_names"] = [THEME_NAMES.get(theme, theme) for theme in themes]
            row["impacts"] = news_impacts(row, mapping)
            decorate_news_item(row)
        return rows

    def fundamentals_thesis_view(self, symbol: str) -> dict:
        normalized = self._watchlist_symbol(symbol)
        bars = self.history(normalized, 260, "1d")
        earnings = self._prefer_earnings_rows(self.earnings_history(normalized))
        current = self.latest_fundamentals(normalized) or {}
        watch = next(
            (row for row in self.watchlist_rows() if row["symbol"] == normalized),
            {},
        )
        own_rev = yoy_from_rows(earnings, "revenue_actual")
        own_eps = yoy_from_rows(earnings, "eps_actual")
        if own_rev is None:
            own_rev = current.get("revenue_growth_yoy_pct")
        if own_eps is None:
            own_eps = current.get("eps_growth_yoy_pct")
        prior_rev = yoy_from_rows(earnings[1:], "revenue_actual") if len(earnings) > 1 else None
        peer_values = []
        peer_symbols = []
        themes = list(watch.get("themes") or [])
        theme_map = self.theme_symbols()
        for theme in themes:
            for peer in theme_map.get(theme, []):
                if peer == normalized or peer in peer_symbols:
                    continue
                peer_symbols.append(peer)
                peer_rows = self._prefer_earnings_rows(self.earnings_history(peer))
                value = yoy_from_rows(peer_rows, "revenue_actual")
                if value is not None:
                    peer_values.append(value)
        peer_median = (
            round(sorted(peer_values)[len(peer_values) // 2], 2) if peer_values else None
        )
        closes = [
            float(row["close_price"])
            for row in bars
            if row.get("close_price") is not None
        ]
        valuation = reconstructed_pe_view(
            closes,
            float(current["eps_ttm"]) if current.get("eps_ttm") is not None else None,
            float(current["pe_ttm"]) if current.get("pe_ttm") is not None else None,
        )
        vs_peers = "样本不足"
        if own_rev is not None and peer_median is not None:
            vs_peers = "高于同主题中位" if own_rev >= peer_median else "低于同主题中位"
        tech = self.technical_summary([normalized])
        tech_row = tech[0] if tech else {}
        return {
            "symbol": normalized,
            "return_1y_pct": return_1y_pct(bars) or tech_row.get("return_1y_pct"),
            "distance_52w_high_pct": tech_row.get("distance_52w_high_pct"),
            "distance_52w_low_pct": tech_row.get("distance_52w_low_pct"),
            "earnings_year": earnings_scorecard(earnings),
            "growth": {
                "revenue_yoy_pct": own_rev,
                "eps_yoy_pct": own_eps,
                "phase": growth_phase_label(
                    float(own_rev) if own_rev is not None else None,
                    float(prior_rev) if prior_rev is not None else None,
                ),
                "peer_theme": themes[0] if themes else None,
                "peer_symbols": peer_symbols,
                "peer_revenue_yoy_median": peer_median,
                "vs_peers": vs_peers,
            },
            "valuation": valuation,
        }

    def review_hit_rate(self, days: int = 14) -> dict:
        rows = self.fetch_all(
            """
            SELECT symbol, outcome_vs_bias, user_confirmed_at IS NOT NULL AS confirmed
            FROM daily_reviews
            WHERE review_date >= CURRENT_DATE - make_interval(days => %s)
              AND outcome_vs_bias IS NOT NULL
            """,
            (days,),
        )
        def _rate(sample: list[dict]) -> dict:
            total = len(sample)
            hits = sum(1 for row in sample if row["outcome_vs_bias"] == "符合")
            return {
                "samples": total,
                "hits": hits,
                "rate_pct": round(100 * hits / total, 1) if total else None,
            }

        by_symbol = {}
        for row in rows:
            by_symbol.setdefault(row["symbol"], []).append(row)
        auto = _rate(rows)
        notes = _rate([row for row in rows if row["confirmed"]])
        return mark_legacy_hit_rate(
            {
                "days": days,
                "all": auto,
                "loop": auto,
                "confirmed": notes,
                "notes_saved": notes,
                "confirm_required": False,
                "by_symbol": {
                    symbol: _rate(sample) for symbol, sample in sorted(by_symbol.items())
                },
            }
        )

    def prediction_scorecard(self, days: int = 14) -> dict:
        try:
            rows = self.fetch_all(
                """
                SELECT DISTINCT ON (symbol, as_of_date)
                       symbol, state, as_of_date
                FROM predictions
                WHERE as_of_date >= CURRENT_DATE - make_interval(days => %s)
                ORDER BY symbol, as_of_date DESC, created_at DESC
                """,
                (days,),
            )
        except DatabaseError:
            rows = []
        return prediction_hit_rate(rows)

    def briefing(self, date: str | None = None) -> dict:
        session = self.market_session(date)
        if not date:
            date = session["default_review_date"]
            session = self.market_session(date)
        watch = self.watchlist_rows()
        technicals = {row["symbol"]: row for row in self.technical_summary()}
        stored = self.reviews_by_date(date) if date else []
        reviews = {row["symbol"]: row for row in stored}
        if not session["is_trading_day"] or not stored:
            snapshots = {row["symbol"]: row for row in self.latest_snapshots()}
            rows = []
            for item in watch:
                symbol = item["symbol"]
                tech = technicals.get(symbol) or {}
                rows.append(
                    enrich_briefing_row(
                        {
                            "symbol": symbol,
                            "name": item.get("name"),
                            "sector": item.get("sector"),
                            "has_review": False,
                            "health": tape_health(tech) if tech else None,
                            "return_5d_pct": tech.get("return_5d_pct"),
                            "return_20d_pct": tech.get("return_20d_pct"),
                            "return_1y_pct": tech.get("return_1y_pct"),
                            "rsi14": tech.get("rsi14"),
                            "volume_ratio_20d": tech.get("volume_ratio_20d"),
                            "distance_52w_high_pct": tech.get("distance_52w_high_pct"),
                            "ma_position": ma_position_text(tech) if tech else None,
                        },
                        snapshots.get(symbol),
                    )
                )
            self._attach_row_environments(rows, date, session=session, watch=watch)
            payload = {
                "date": date,
                "session": session,
                "has_reviews": False,
                "rows": rows,
                "hit_rate": self.review_hit_rate(),
                "prediction_hit_rate": self.prediction_scorecard(),
                "confirm_required": False,
            }
            return self._with_shell(payload, snapshots=list(snapshots.values()))
        prior_rows = self.fetch_all(
            """
            SELECT DISTINCT ON (symbol) *
            FROM daily_reviews
            WHERE review_date < %s AND outcome_vs_bias IS NOT NULL
            ORDER BY symbol, review_date DESC
            """,
            (date or "1970-01-01",),
        ) if date else []
        prior = {row["symbol"]: row for row in prior_rows}
        snapshots = {row["symbol"]: row for row in self.latest_snapshots()}
        rows = []
        for item in watch:
            symbol = item["symbol"]
            review = reviews.get(symbol)
            if not review:
                continue
            tech = technicals.get(symbol) or {}
            snap = snapshots.get(symbol) or {}
            metrics = (review or {}).get("metrics") or {}
            if isinstance(metrics, str):
                metrics = {}
            health = tape_health(tech, review)
            day_change = metrics.get("day_change_pct")
            quality = snap.get("quote_quality") or quote_quality(snap, review)
            if (
                day_change is None
                and not quality.get("hide_last_price")
                and snap.get("last_price")
                and snap.get("prior_close")
            ):
                day_change = round(
                    100 * (float(snap["last_price"]) / float(snap["prior_close"]) - 1), 2
                )
            prior_review = prior.get(symbol)
            rows.append(
                enrich_briefing_row(
                    {
                    "symbol": symbol,
                    "name": item.get("name"),
                    "sector": item.get("sector"),
                    "close_price": (review or {}).get("close_price"),
                    "last_price": snap.get("displayed_last_price")
                    if snap.get("quote_quality")
                    else snap.get("last_price") or tech.get("close_price"),
                    "day_change_pct": day_change,
                    "volume_ratio_20d": tech.get("volume_ratio_20d")
                    or metrics.get("relative_volume"),
                    "return_5d_pct": tech.get("return_5d_pct"),
                    "return_20d_pct": tech.get("return_20d_pct"),
                    "return_1y_pct": tech.get("return_1y_pct"),
                    "distance_52w_high_pct": tech.get("distance_52w_high_pct"),
                    "rsi14": tech.get("rsi14"),
                    "ma5": tech.get("ma5"),
                    "ma20": tech.get("ma20"),
                    "ma50": tech.get("ma50"),
                    "ma200": tech.get("ma200"),
                    "distance_ma20_pct": tech.get("distance_ma20_pct"),
                    "distance_ma200_pct": tech.get("distance_ma200_pct"),
                    "ma_position": ma_position_text(tech),
                    "health": health,
                    "support_price": (review or {}).get("support_price"),
                    "resistance_price": (review or {}).get("resistance_price"),
                    "breakout_status": (review or {}).get("breakout_status"),
                    "support_test": metrics.get("support_test"),
                    "tape": (review or {}).get("short_trend"),
                    "score": (review or {}).get("score"),
                    "rule_bias": (review or {}).get("rule_bias"),
                    "watch_low": (review or {}).get("watch_low"),
                    "watch_high": (review or {}).get("watch_high"),
                    "has_review": review is not None,
                    "llm_status": (review or {}).get("llm_status"),
                    "llm_why": (review or {}).get("llm_why"),
                    "llm_outlook": (review or {}).get("llm_outlook"),
                    "llm_bias": (review or {}).get("llm_bias"),
                    "llm_generated_at": (review or {}).get("llm_generated_at"),
                    "llm_error": (review or {}).get("llm_error"),
                    "user_bias": (review or {}).get("user_bias"),
                    "user_outlook": (review or {}).get("user_outlook"),
                    "user_note": (review or {}).get("user_note"),
                    "user_confirmed_at": (review or {}).get("user_confirmed_at"),
                    "summary": (review or {}).get("summary"),
                    "context": (review or {}).get("context") or {},
                    "review_date": (review or {}).get("review_date") or date,
                    "prior_outcome": {
                        "review_date": prior_review.get("review_date"),
                        "outcome_vs_bias": prior_review.get("outcome_vs_bias"),
                        "outcome_return_pct": prior_review.get("outcome_return_pct"),
                        "outcome_bias_source": prior_review.get("outcome_bias_source"),
                        "bias": prior_review.get("user_bias")
                        or prior_review.get("llm_bias")
                        or prior_review.get("rule_bias"),
                    }
                    if prior_review
                    else None,
                    },
                    snap,
                )
            )
        self._attach_row_environments(rows, date, session=session, watch=watch)
        payload = {
            "date": date,
            "session": session,
            "has_reviews": True,
            "rows": rows,
            "hit_rate": self.review_hit_rate(),
            "prediction_hit_rate": self.prediction_scorecard(),
            "confirm_required": False,
        }
        return self._with_shell(payload, snapshots=list(snapshots.values()))

    def latest_environment_snapshots(self, as_of_date: str | None) -> list[dict]:
        if not as_of_date:
            return []
        rows = self.fetch_all(
            """
            SELECT DISTINCT ON (scope, symbol)
                   id, as_of_date, scope, symbol, one_liner, row_thesis,
                   struct, missing_flags, publish_state, created_at
            FROM environment_snapshots
            WHERE as_of_date = %s
            ORDER BY scope, symbol, created_at DESC
            """,
            (as_of_date,),
        )
        return [snapshot_from_row(row) for row in rows if snapshot_from_row(row)]

    def latest_environment_snapshot(
        self,
        as_of_date: str | None,
        scope: str,
        symbol: str | None = None,
    ) -> dict | None:
        if not as_of_date:
            return None
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, scope, symbol, one_liner, row_thesis,
                   struct, missing_flags, publish_state, created_at
            FROM environment_snapshots
            WHERE as_of_date = %s AND scope = %s
              AND ((%s::text IS NULL AND symbol IS NULL) OR symbol = %s::text)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (as_of_date, scope, symbol, symbol),
        )
        return snapshot_from_row(rows[0]) if rows else None

    def environment_history(self, symbol: str, limit: int = 30) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, scope, symbol, one_liner, row_thesis,
                   struct, missing_flags, publish_state, created_at
            FROM environment_snapshots
            WHERE symbol = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (normalized, limit),
        )
        return [snapshot_from_row(row) for row in rows if snapshot_from_row(row)]

    def assemble_environment_inputs(
        self,
        symbol: str,
        as_of_date: str | None = None,
        *,
        technical: dict | None = None,
        thesis: dict | None = None,
        review: dict | None = None,
        impact: dict | None = None,
        news: list[dict] | None = None,
        peer_news: list[dict] | None = None,
        session: dict | None = None,
        watch: dict | None = None,
        briefing_row: dict | None = None,
    ) -> dict:
        normalized = self._watchlist_symbol(symbol)
        session = session or self.market_session(as_of_date)
        date = as_of_date or session.get("default_review_date") or session.get("date")
        watch = watch or next(
            (row for row in self.watchlist_rows() if row["symbol"] == normalized),
            {"symbol": normalized},
        )
        if technical is None:
            tech_rows = self.technical_summary([normalized])
            technical = tech_rows[0] if tech_rows else {}
        if thesis is None:
            try:
                thesis = self.fundamentals_thesis_view(normalized)
            except Exception:
                thesis = {}
        if impact is None:
            try:
                impact = self.market_impact()
            except Exception:
                impact = {"macro": []}
        if news is None:
            try:
                news = self.news([normalized], limit=24)
            except Exception:
                news = []
        if peer_news is None:
            peers: list[str] = []
            theme_map = self.theme_symbols()
            for theme in watch.get("themes") or []:
                for peer in theme_map.get(theme, []):
                    if peer != normalized and peer not in peers:
                        peers.append(peer)
            try:
                peer_news = self.news(peers[:6], limit=24) if peers else []
            except Exception:
                peer_news = []
        if review is None and date:
            try:
                review = self.review_row(normalized, date)
            except Exception:
                review = None
        return {
            "as_of_date": date,
            "symbol": normalized,
            "watch": watch,
            "thesis": thesis or {},
            "technical": technical or {},
            "news": news or [],
            "peer_news": peer_news or [],
            "impact": impact or {"macro": []},
            "briefing_row": briefing_row or review,
            "session": session,
        }

    def build_live_environment(
        self,
        symbol: str,
        as_of_date: str | None = None,
        **preloaded: Any,
    ) -> dict:
        try:
            inputs = self.assemble_environment_inputs(symbol, as_of_date, **preloaded)
            return synthesize_symbol_environment(**inputs, source="live")
        except Exception as exc:
            session = preloaded.get("session")
            date = as_of_date or (session or {}).get("default_review_date")
            return failed_snapshot(symbol, date, str(exc))

    def _attach_row_environments(
        self,
        rows: list[dict],
        as_of_date: str | None,
        *,
        session: dict | None = None,
        watch: list[dict] | None = None,
    ) -> None:
        stored: dict[str, dict] = {}
        try:
            for item in self.latest_environment_snapshots(as_of_date):
                if item and item.get("scope") == "symbol" and item.get("symbol"):
                    stored[item["symbol"]] = item
        except Exception:
            stored = {}
        watch_map = {item["symbol"]: item for item in (watch or [])}
        impact = None
        try:
            impact = self.market_impact()
        except Exception:
            impact = {"macro": []}
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            env = stored.get(symbol)
            if not env:
                env = self.build_live_environment(
                    symbol,
                    as_of_date,
                    technical={
                        "health": row.get("health"),
                        "return_5d_pct": row.get("return_5d_pct"),
                        "return_20d_pct": row.get("return_20d_pct"),
                        "return_1y_pct": row.get("return_1y_pct"),
                        "rsi14": row.get("rsi14"),
                        "volume_ratio_20d": row.get("volume_ratio_20d"),
                        "distance_52w_high_pct": row.get("distance_52w_high_pct"),
                    },
                    review=row,
                    impact=impact,
                    session=session,
                    watch=watch_map.get(symbol),
                    briefing_row=row,
                )
            row["environment"] = env
            row["env_half"] = env_half_display(env, env.get("one_liner"))
            row["env_news"] = first_env_news(env)
            if env.get("conflict"):
                row["row_thesis"] = env.get("row_thesis") or row.get("row_thesis")
            else:
                row["row_thesis"] = env.get("one_liner") or row.get("row_thesis")
        self._attach_row_tapes(rows, as_of_date, session=session)

    def _with_shell(
        self,
        briefing: dict,
        snapshots: list[dict] | None = None,
        symbol: str | None = None,
        symbol_environment: dict | None = None,
    ) -> dict:
        date = briefing.get("date")
        options = self.cboe_option_stats(date)
        options_payload = {"status": "ok", **options} if options else {
            "status": "missing",
            "trade_date": date,
        }
        try:
            impact = self.market_impact()
        except Exception:
            impact = {"macro": []}
        try:
            sync = self.sync_status()
        except Exception:
            sync = None
        if snapshots is None:
            try:
                snapshots = self.latest_snapshots([symbol] if symbol else None)
            except Exception:
                snapshots = []
        symbol_tape = None
        symbol_note = None
        symbol_prediction = None
        if symbol and symbol_environment is None:
            match = next(
                (
                    row.get("environment")
                    for row in briefing.get("rows") or []
                    if str(row.get("symbol") or "").upper() == symbol.upper()
                    and row.get("environment")
                ),
                None,
            )
            symbol_environment = match or self.latest_environment_snapshot(
                date, "symbol", symbol.upper()
            )
            if symbol_environment is None:
                symbol_environment = self.build_live_environment(symbol, date)
        if symbol:
            match_row = next(
                (
                    row
                    for row in briefing.get("rows") or []
                    if str(row.get("symbol") or "").upper() == symbol.upper()
                ),
                None,
            )
            symbol_tape = (match_row or {}).get("tape_analysis") or self.tape_payload(
                date, symbol
            )
            symbol_note = (match_row or {}).get("review_note") or self.review_note_payload(
                date, symbol
            )
            symbol_prediction = (match_row or {}).get("prediction") or self.prediction_payload(
                date, symbol
            )
        if not symbol and symbol_environment is None:
            try:
                symbol_environment = self.latest_environment_snapshot(date, "market", None)
            except Exception:
                symbol_environment = None
        pred_list = [
            row.get("prediction")
            for row in briefing.get("rows") or []
            if row.get("prediction")
        ]
        if symbol and symbol_prediction and symbol_prediction not in pred_list:
            pred_list.append(symbol_prediction)
        shell = build_shell(
            briefing=briefing,
            options=options_payload,
            snapshots=snapshots,
            impact=impact,
            sync=sync,
            symbol=symbol,
            symbol_environment=symbol_environment,
            predictions=pred_list,
        )
        extra = {}
        if symbol:
            extra["tape"] = symbol_tape
            extra["review_note"] = symbol_note
            extra["prediction"] = symbol_prediction
        return {**briefing, **shell, **extra}

    def shell_state(self, date: str | None = None, symbol: str | None = None) -> dict:
        briefing = self.briefing(date)
        if symbol:
            return self._with_shell(briefing, symbol=symbol)
        return {
            "as_of": briefing.get("as_of") or briefing.get("date"),
            "explicit_state": briefing.get("explicit_state"),
            "alerts": briefing.get("alerts") or [],
            "environment": briefing.get("environment"),
            "quote_quality": briefing.get("quote_quality") or {},
        }

    def environment_payload(self, date: str | None = None, symbol: str | None = None) -> dict:
        if symbol:
            session = self.market_session(date)
            as_of = date or session.get("default_review_date")
            stored = self.latest_environment_snapshot(as_of, "symbol", symbol.upper())
            return stored or self.build_live_environment(symbol, as_of)
        payload = self.shell_state(date)
        return payload.get("environment") or failed_snapshot(None, date, "environment missing")

    def latest_tape_analyses(self, as_of_date: str | None) -> list[dict]:
        if not as_of_date:
            return []
        rows = self.fetch_all(
            """
            SELECT DISTINCT ON (symbol)
                   id, as_of_date, symbol, one_liner, conclusion,
                   struct, missing_flags, publish_state, created_at
            FROM tape_analyses
            WHERE as_of_date = %s
            ORDER BY symbol, created_at DESC
            """,
            (as_of_date,),
        )
        return [tape_from_row(row) for row in rows if tape_from_row(row)]

    def latest_tape_analysis(self, as_of_date: str | None, symbol: str) -> dict | None:
        if not as_of_date:
            return None
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, one_liner, conclusion,
                   struct, missing_flags, publish_state, created_at
            FROM tape_analyses
            WHERE as_of_date = %s AND symbol = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (as_of_date, symbol),
        )
        return tape_from_row(rows[0]) if rows else None

    def tape_history(self, symbol: str, limit: int = 30) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, one_liner, conclusion,
                   struct, missing_flags, publish_state, created_at
            FROM tape_analyses
            WHERE symbol = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (normalized, limit),
        )
        return [tape_from_row(row) for row in rows if tape_from_row(row)]

    def latest_review_note(self, as_of_date: str | None, symbol: str) -> dict | None:
        if not as_of_date:
            return None
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, summary, explanation, unexplained,
                   struct, missing_flags, publish_state, created_at
            FROM review_notes
            WHERE as_of_date = %s AND symbol = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (as_of_date, symbol),
        )
        return review_note_from_row(rows[0]) if rows else None

    def review_note_history(self, symbol: str, limit: int = 30) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, summary, explanation, unexplained,
                   struct, missing_flags, publish_state, created_at
            FROM review_notes
            WHERE symbol = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (normalized, limit),
        )
        return [review_note_from_row(row) for row in rows if review_note_from_row(row)]

    def _tape_relative_inputs(self, symbol: str, metrics: dict) -> dict:
        extra: dict[str, Any] = {}
        try:
            watch = next(
                (row for row in self.watchlist_rows() if row["symbol"] == symbol),
                {"symbol": symbol, "themes": []},
            )
            tech_rows = {row["symbol"]: row for row in self.technical_summary()}
            own = tech_rows.get(symbol) or {}
            own_5d = _number(own.get("return_5d_pct"))
            if own_5d is not None:
                extra["return_5d_pct"] = own_5d
            themes = list(watch.get("themes") or [])
            sector_theme = next((item for item in themes if item in SECTOR_THEMES), None)
            if sector_theme:
                peer_days: list[float] = []
                peer_fives: list[float] = []
                for row in self.watchlist_rows():
                    if row["symbol"] == symbol:
                        continue
                    if sector_theme not in (row.get("themes") or []):
                        continue
                    peer = tech_rows.get(row["symbol"]) or {}
                    day = _number(peer.get("return_1d_pct"))
                    five = _number(peer.get("return_5d_pct"))
                    if day is not None:
                        peer_days.append(day)
                    if five is not None:
                        peer_fives.append(five)
                if peer_days:
                    extra["benchmark_kind"] = "sector"
                    extra["benchmark_name"] = (
                        f"板块（{THEME_NAMES.get(sector_theme, sector_theme)}）"
                    )
                    extra["benchmark_theme"] = sector_theme
                    extra["benchmark_day_change_pct"] = round(
                        sorted(peer_days)[len(peer_days) // 2], 2
                    )
                    if peer_fives:
                        extra["benchmark_return_5d_pct"] = round(
                            sorted(peer_fives)[len(peer_fives) // 2], 2
                        )
                    return extra
            market = tech_rows.get("QQQ") or {}
            extra["benchmark_kind"] = "market"
            extra["benchmark_name"] = "大盘（QQQ）"
            extra["benchmark_day_change_pct"] = _number(market.get("return_1d_pct"))
            extra["benchmark_return_5d_pct"] = _number(market.get("return_5d_pct"))
        except Exception:
            return extra
        return extra

    def build_live_tape(
        self,
        symbol: str,
        as_of_date: str | None = None,
        **preloaded: Any,
    ) -> dict:
        from .review import analyze_bars

        normalized = symbol.upper()
        session = preloaded.get("session") or self.market_session(as_of_date)
        date = as_of_date or session.get("default_review_date") or session.get("date")
        try:
            bars = preloaded.get("bars")
            if bars is None:
                bars = self.history(normalized, 260, "1d")
            complete = [
                row
                for row in bars
                if all(
                    row.get(key) is not None
                    for key in ("open_price", "high_price", "low_price", "close_price")
                )
            ]
            if date:
                dated = [
                    row
                    for row in complete
                    if str(row.get("bar_time") or "")[:10] <= str(date)[:10]
                ]
                if dated:
                    complete = dated
            if len(complete) < 20:
                return failed_tape(normalized, date, "need 20 daily bars")
            metrics = analyze_bars(complete)
            metrics.update(self._tape_relative_inputs(normalized, metrics))
            environment = preloaded.get("environment")
            if environment is None:
                environment = self.environment_payload(date, normalized)
            segments = preloaded.get("segments")
            if segments is None:
                try:
                    segments = self.segments(normalized, date)
                except Exception:
                    segments = []
            return synthesize_tape_analysis(
                as_of_date=date,
                symbol=normalized,
                metrics=metrics,
                environment=environment,
                segments=segments,
                session=session,
                source=preloaded.get("source") or "live",
            )
        except Exception as exc:
            return failed_tape(normalized, date, str(exc))

    def build_live_review_note(
        self,
        symbol: str,
        as_of_date: str | None = None,
        *,
        tape: dict | None = None,
        environment: dict | None = None,
        session: dict | None = None,
        source: str = "live",
    ) -> dict:
        normalized = symbol.upper()
        session = session or self.market_session(as_of_date)
        date = as_of_date or session.get("default_review_date") or session.get("date")
        try:
            tape = tape or self.tape_payload(date, normalized)
            environment = environment or self.environment_payload(date, normalized)
            return synthesize_review_note(
                as_of_date=date,
                symbol=normalized,
                tape=tape,
                environment=environment,
                session=session,
                source=source,
            )
        except Exception as exc:
            return failed_review_note(normalized, date, str(exc))

    def tape_payload(self, date: str | None = None, symbol: str | None = None) -> dict:
        if not symbol:
            raise ValueError("symbol is required")
        session = self.market_session(date)
        as_of = date or session.get("default_review_date")
        stored = self.latest_tape_analysis(as_of, symbol.upper())
        return stored or self.build_live_tape(symbol, as_of)

    def review_note_payload(self, date: str | None = None, symbol: str | None = None) -> dict:
        if not symbol:
            raise ValueError("symbol is required")
        session = self.market_session(date)
        as_of = date or session.get("default_review_date")
        stored = self.latest_review_note(as_of, symbol.upper())
        return stored or self.build_live_review_note(symbol, as_of)

    def _attach_row_tapes(
        self,
        rows: list[dict],
        as_of_date: str | None,
        *,
        session: dict | None = None,
    ) -> None:
        stored: dict[str, dict] = {}
        try:
            for item in self.latest_tape_analyses(as_of_date):
                if item and item.get("symbol"):
                    stored[item["symbol"]] = item
        except Exception:
            stored = {}
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            tape = stored.get(symbol)
            if not tape:
                tape = self.build_live_tape(
                    symbol,
                    as_of_date,
                    environment=row.get("environment"),
                    session=session,
                    source="live",
                )
            note = None
            try:
                note = self.latest_review_note(as_of_date, symbol)
            except Exception:
                note = None
            if not note:
                note = synthesize_review_note(
                    as_of_date=as_of_date,
                    symbol=symbol,
                    tape=tape,
                    environment=row.get("environment"),
                    session=session,
                    source="live",
                )
            row["tape_analysis"] = tape
            row["tape_half"] = tape_half_display(tape)
            row["review_note"] = note
            env = row.get("environment") or {}
            conflict = bool((tape or {}).get("conflict"))
            if conflict:
                row["env_tape_conflict"] = True
                row["row_thesis"] = env_tape_conflict_sentence(env, tape)
            else:
                row["env_tape_conflict"] = False
        self._attach_row_predictions(rows, as_of_date, session=session)

    def latest_predictions(self, as_of_date: str | None) -> list[dict]:
        if not as_of_date:
            return []
        rows = self.fetch_all(
            """
            SELECT DISTINCT ON (symbol)
                   id, as_of_date, symbol, state, window_start, window_end,
                   window_days, window_label, thesis, entry_price,
                   upside_bound_pct, downside_bound_pct, upside_price,
                   downside_price, struct, missing_flags, publish_state,
                   supersedes_id, superseded_by_id, change_reason, created_at
            FROM predictions
            WHERE as_of_date = %s
            ORDER BY symbol, created_at DESC
            """,
            (as_of_date,),
        )
        return [prediction_from_row(row) for row in rows if prediction_from_row(row)]

    def latest_open_prediction(self, symbol: str) -> dict | None:
        normalized = symbol.upper()
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, state, window_start, window_end,
                   window_days, window_label, thesis, entry_price,
                   upside_bound_pct, downside_bound_pct, upside_price,
                   downside_price, struct, missing_flags, publish_state,
                   supersedes_id, superseded_by_id, change_reason, created_at
            FROM predictions
            WHERE symbol = %s AND state = ANY(%s)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized, list(OPEN_STATES)),
        )
        return prediction_from_row(rows[0]) if rows else None

    def latest_prediction(
        self,
        as_of_date: str | None,
        symbol: str,
        *,
        open_only: bool = False,
    ) -> dict | None:
        if open_only:
            return self.latest_open_prediction(symbol)
        if not as_of_date:
            return self.latest_open_prediction(symbol)
        open_pred = self.latest_open_prediction(symbol)
        if open_pred:
            return open_pred
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, state, window_start, window_end,
                   window_days, window_label, thesis, entry_price,
                   upside_bound_pct, downside_bound_pct, upside_price,
                   downside_price, struct, missing_flags, publish_state,
                   supersedes_id, superseded_by_id, change_reason, created_at
            FROM predictions
            WHERE as_of_date = %s AND symbol = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (as_of_date, symbol.upper()),
        )
        return self._attach_judgment_alert(prediction_from_row(rows[0]) if rows else None)

    def prediction_history(self, symbol: str, limit: int = 30) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, state, window_start, window_end,
                   window_days, window_label, thesis, entry_price,
                   upside_bound_pct, downside_bound_pct, upside_price,
                   downside_price, struct, missing_flags, publish_state,
                   supersedes_id, superseded_by_id, change_reason, created_at
            FROM predictions
            WHERE symbol = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (normalized, limit),
        )
        return [prediction_from_row(row) for row in rows if prediction_from_row(row)]

    def prediction_checks(self, prediction_id: int, limit: int = 60) -> list[dict]:
        rows = self.fetch_all(
            """
            SELECT id, prediction_id, as_of_date, symbol, close_price,
                   high_price, low_price, max_gain_pct, max_drawdown_pct,
                   in_bounds, outcome, reason, struct, created_at
            FROM prediction_checks
            WHERE prediction_id = %s
            ORDER BY as_of_date DESC, created_at DESC
            LIMIT %s
            """,
            (prediction_id, limit),
        )
        return [check_from_row(row) for row in rows if check_from_row(row)]

    def prediction_by_id(self, prediction_id: int) -> dict | None:
        rows = self.fetch_all(
            """
            SELECT id, as_of_date, symbol, state, window_start, window_end,
                   window_days, window_label, thesis, entry_price,
                   upside_bound_pct, downside_bound_pct, upside_price,
                   downside_price, struct, missing_flags, publish_state,
                   supersedes_id, superseded_by_id, change_reason, created_at
            FROM predictions
            WHERE id = %s
            """,
            (prediction_id,),
        )
        return prediction_from_row(rows[0]) if rows else None

    def _entry_price_for(self, symbol: str, as_of_date: str | None, tape: dict | None) -> float | None:
        chips = (tape or {}).get("chips") or {}
        entry = _number(chips.get("close"))
        if entry is not None:
            return entry
        if as_of_date:
            try:
                reviews = self.reviews_by_date(as_of_date)
                match = next(
                    (
                        row
                        for row in reviews
                        if str(row.get("symbol") or "").upper() == symbol.upper()
                    ),
                    None,
                )
                if match and match.get("close_price") is not None:
                    return _number(match.get("close_price"))
            except Exception:
                pass
        try:
            bars = self.history(symbol, 5, "1d")
        except Exception:
            bars = []
        if as_of_date:
            day = next(
                (
                    row
                    for row in reversed(bars)
                    if str(row.get("bar_time") or "")[:10] == str(as_of_date)[:10]
                ),
                None,
            )
            if day:
                return _number(day.get("close_price"))
        if bars:
            return _number(bars[-1].get("close_price"))
        return None

    def build_live_prediction(
        self,
        symbol: str,
        as_of_date: str | None = None,
        *,
        environment: dict | None = None,
        tape: dict | None = None,
        review_note: dict | None = None,
        entry_price: float | None = None,
        session: dict | None = None,
        source: str = "live",
    ) -> dict:
        normalized = symbol.upper()
        session = session or self.market_session(as_of_date)
        date = as_of_date or session.get("default_review_date") or session.get("date")
        try:
            tape = tape or self.tape_payload(date, normalized)
            environment = environment or self.environment_payload(date, normalized)
            review_note = review_note or self.review_note_payload(date, normalized)
            entry = entry_price or self._entry_price_for(normalized, date, tape)
            return synthesize_prediction(
                as_of_date=date,
                symbol=normalized,
                environment=environment,
                tape=tape,
                review_note=review_note,
                entry_price=entry,
                session=session,
                source=source,
            )
        except Exception as exc:
            return failed_prediction(normalized, date, str(exc))

    def prediction_payload(self, date: str | None = None, symbol: str | None = None) -> dict:
        if not symbol:
            raise ValueError("symbol is required")
        session = self.market_session(date)
        as_of = date or session.get("default_review_date")
        stored = None
        try:
            stored = self.latest_prediction(as_of, symbol.upper())
        except DatabaseError:
            stored = None
        pred = stored or self.build_live_prediction(symbol, as_of)
        attached = self._attach_judgment_alert(pred) or pred
        return self._apply_direction_gate(attached, symbol)

    def _apply_direction_gate(self, pred: dict, symbol: str) -> dict:
        allowed = False
        try:
            from stock_pm.decision.assemble import assemble_from_bundle

            view = assemble_from_bundle(self.decision_bundle(symbol))
            allowed = bool(view.get("can_form_direction"))
        except Exception:
            allowed = False
        return withhold_unsourced_prediction(pred, can_form_direction=allowed)

    def _attach_row_predictions(
        self,
        rows: list[dict],
        as_of_date: str | None,
        *,
        session: dict | None = None,
    ) -> None:
        stored: dict[str, dict] = {}
        try:
            for item in self.latest_predictions(as_of_date):
                if item and item.get("symbol"):
                    stored[item["symbol"]] = item
            for row in rows:
                symbol = row.get("symbol")
                if not symbol or symbol in stored:
                    continue
                open_pred = self.latest_open_prediction(symbol)
                if open_pred:
                    stored[symbol] = open_pred
        except Exception:
            stored = {}
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            pred = stored.get(symbol)
            if not pred:
                pred = self.build_live_prediction(
                    symbol,
                    as_of_date,
                    environment=row.get("environment"),
                    tape=row.get("tape_analysis"),
                    review_note=row.get("review_note"),
                    entry_price=_number(row.get("close_price") or row.get("conclusion_price")),
                    session=session,
                    source="live",
                )
            gated = self._apply_direction_gate(self._attach_judgment_alert(pred) or pred, symbol)
            row["prediction"] = gated
            row["prediction_half"] = prediction_badge(gated)
            ctx = row.get("context")
            if isinstance(ctx, dict) and ctx.get("news"):
                ctx = dict(ctx)
                ctx["news"] = [decorate_news_item(item) for item in ctx.get("news") or []]
                row["context"] = ctx
        rows[:] = sort_attention_rows(rows)

    def severity_alert(self, alert_id: int | None) -> dict | None:
        parsed = parse_alert_id(alert_id)
        if parsed is None:
            return None
        rows = self.fetch_all(
            """
            SELECT id, alert_key, severity, title, message, symbol, active,
                   prediction_id, created_at, resolved_at
            FROM severity_alerts
            WHERE id = %s
            """,
            (parsed,),
        )
        return rows[0] if rows else None

    def latest_judgment_alert(self, symbol: str, prediction_id: int | None) -> dict | None:
        if not prediction_id:
            return None
        normalized = symbol.upper()
        key = f"face_slap:{normalized}:{int(prediction_id)}"
        rows = self.fetch_all(
            """
            SELECT id, alert_key, severity, title, message, symbol, active,
                   prediction_id, created_at, resolved_at
            FROM severity_alerts
            WHERE severity = 'severe' AND active = TRUE
              AND (
                    prediction_id = %s
                 OR alert_key = %s
              )
              AND (symbol IS NULL OR symbol = %s)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (int(prediction_id), key, normalized),
        )
        return rows[0] if rows else None

    def _attach_judgment_alert(self, pred: dict | None) -> dict | None:
        if not pred:
            return pred
        attached = dict(pred)
        if attached.get("state") != "invalidated" or not attached.get("id"):
            attached["judgment_alert"] = None
            return attached
        try:
            attached["judgment_alert"] = self.latest_judgment_alert(
                attached.get("symbol") or "", attached.get("id")
            )
        except DatabaseError:
            attached["judgment_alert"] = None
        return attached

    def supersede_prediction(self, prediction_id: int, body: dict[str, Any]) -> dict:
        old = self.prediction_by_id(prediction_id)
        if not old:
            raise ValueError(f"No prediction {prediction_id}")
        alert_id = parse_alert_id((body or {}).get("alert_id"))
        alert = self.severity_alert(alert_id)
        require_judgment_alert(
            alert,
            symbol=old["symbol"],
            prediction_id=old.get("id"),
            alert_id=(body or {}).get("alert_id"),
        )
        reason = (body.get("change_reason") or body.get("reason") or "").strip()
        symbol = old["symbol"]
        session = self.market_session(body.get("as_of_date") or old.get("as_of_date"))
        date = body.get("as_of_date") or session.get("default_review_date")
        new = synthesize_prediction(
            as_of_date=date,
            symbol=symbol,
            environment=self.environment_payload(date, symbol),
            tape=self.tape_payload(date, symbol),
            review_note=self.review_note_payload(date, symbol),
            entry_price=_number(body.get("entry_price"))
            or self._entry_price_for(symbol, date, self.tape_payload(date, symbol)),
            support=_number(body.get("support") or body.get("downside_price")),
            resistance=_number(body.get("resistance") or body.get("upside_price")),
            session=session,
            source="human",
            supersedes_id=old.get("id"),
            change_reason=reason,
        )
        if body.get("upside_bound_pct") is not None and body.get("downside_bound_pct") is not None:
            entry = _number(new.get("entry_price")) or _number(body.get("entry_price"))
            up = _number(body.get("upside_bound_pct"))
            down = _number(body.get("downside_bound_pct"))
            if entry and up is not None and down is not None:
                new["upside_bound_pct"] = up
                new["downside_bound_pct"] = down
                new["upside_price"] = round(entry * (1 + up / 100.0), 4)
                new["downside_price"] = round(entry * (1 + down / 100.0), 4)
                new["prediction_ready"] = True
                new["state"] = "pending"
                new["one_liner"] = (
                    f"{new.get('window_label') or '窗口'}改口约{up:g}%，"
                    f"期间跌幅不超过{abs(down):g}%。"
                )
        superseded, replacement = apply_supersede(
            old,
            new,
            change_reason=reason,
            alert_id=alert_id,
            alert=alert,
        )
        written = self.append_prediction(replacement)
        superseded["superseded_by_id"] = written.get("id")
        self.update_prediction_state(superseded)
        return {
            "superseded": {**old, "state": "superseded", "superseded_by_id": written.get("id")},
            "prediction": written,
        }

    def job_runs(self, limit: int = 20) -> list[dict]:
        dedicated: list[dict] = []
        try:
            dedicated = self.fetch_all(
                """
                SELECT id, job_name, started_at, completed_at, status, item_counts, error
                FROM job_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        except DatabaseError:
            dedicated = []
        sync: list[dict] = []
        try:
            sync = self.fetch_all(
                """
                SELECT source, started_at, completed_at, status, item_counts, error
                FROM sync_runs
                ORDER BY completed_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        except DatabaseError:
            sync = []
        merged: list[dict] = [{**row, "source_table": "job_runs"} for row in dedicated]
        for row in sync:
            merged.append(
                {
                    "job_name": row.get("source") or "sync",
                    "started_at": row.get("started_at"),
                    "completed_at": row.get("completed_at"),
                    "status": row.get("status"),
                    "item_counts": row.get("item_counts") or {},
                    "error": row.get("error"),
                    "source_table": "sync_runs",
                }
            )
        merged.sort(
            key=lambda row: str(row.get("started_at") or row.get("completed_at") or ""),
            reverse=True,
        )
        return merged[:limit]

    def events_between(
        self, start: str, end: str, symbol: str | None = None, limit: int = 300
    ) -> list[dict]:
        clauses = ["event_time >= %s", "event_time < %s::date + 1"]
        params: list[Any] = [start, end]
        if symbol:
            clauses.append("symbol = %s")
            params.append(self._watchlist_symbol(symbol))
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT symbol, event_time, event_type, severity, title, details, source
            FROM market_events
            WHERE {' AND '.join(clauses)}
            ORDER BY event_time DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def macro_events_between(self, start: str, end: str) -> list[dict]:
        return self.fetch_all(
            """
            SELECT event_type, event_time, name, actual, consensus, prior,
                   unit, surprise, confirmed, source, notes
            FROM macro_events
            WHERE event_time >= %s AND event_time < %s::date + 1
            ORDER BY event_time DESC
            """,
            (start, end),
        )

    def daily_range(self, symbol: str, start: str, end: str) -> dict:
        normalized = self._watchlist_symbol(symbol)
        if start > end:
            raise ValueError("from must be earlier than or equal to to")
        bars = self.fetch_all(
            """
            SELECT bar_time, open_price, high_price, low_price,
                   close_price, volume
            FROM price_bars
            WHERE symbol = %s AND bar_size = '1m'
              AND (bar_time AT TIME ZONE 'America/New_York')::date >= %s
              AND (bar_time AT TIME ZONE 'America/New_York')::date <= %s
              AND (bar_time AT TIME ZONE 'America/New_York')::time
                  BETWEEN TIME '09:30' AND TIME '16:00'
            ORDER BY bar_time
            """,
            (normalized, start, end),
        )
        stats = None
        volume = None
        if bars:
            first = float(bars[0]["open_price"] or bars[0]["close_price"])
            last = float(bars[-1]["close_price"])
            volumes = [float(bar["volume"] or 0) for bar in bars]
            average_volume = sum(volumes) / len(volumes)
            sorted_volumes = sorted(volumes)
            middle = len(sorted_volumes) // 2
            median_volume = (
                sorted_volumes[middle]
                if len(sorted_volumes) % 2
                else (sorted_volumes[middle - 1] + sorted_volumes[middle]) / 2
            )
            up_volume = down_volume = 0.0
            returns: list[float] = []
            patterns = {
                "放量上涨": 0,
                "放量下跌": 0,
                "缩量上涨": 0,
                "缩量下跌": 0,
                "量价平稳": 0,
            }
            enriched = []
            for bar, bar_volume in zip(bars, volumes):
                open_price = float(bar["open_price"] or bar["close_price"])
                close_price = float(bar["close_price"])
                change = 100 * (close_price / open_price - 1) if open_price else 0.0
                returns.append(change)
                if change >= 0:
                    up_volume += bar_volume
                else:
                    down_volume += bar_volume
                if bar_volume >= average_volume * 1.2 and change > 0:
                    pattern = "放量上涨"
                elif bar_volume >= average_volume * 1.2 and change < 0:
                    pattern = "放量下跌"
                elif bar_volume <= average_volume * 0.8 and change > 0:
                    pattern = "缩量上涨"
                elif bar_volume <= average_volume * 0.8 and change < 0:
                    pattern = "缩量下跌"
                else:
                    pattern = "量价平稳"
                patterns[pattern] += 1
                enriched.append(
                    {
                        "time": bar["bar_time"],
                        "volume": bar_volume,
                        "change_pct": round(change, 3),
                        "volume_ratio": (
                            round(bar_volume / average_volume, 2)
                            if average_volume
                            else None
                        ),
                        "pattern": pattern,
                    }
                )

            mean_return = sum(returns) / len(returns)
            covariance = sum(
                (ret - mean_return) * (bar_volume - average_volume)
                for ret, bar_volume in zip(returns, volumes)
            )
            return_variance = sum((ret - mean_return) ** 2 for ret in returns)
            volume_variance = sum(
                (bar_volume - average_volume) ** 2 for bar_volume in volumes
            )
            denominator = (return_variance * volume_variance) ** 0.5
            correlation = covariance / denominator if denominator else 0.0
            if correlation >= 0.25:
                conclusion = "量价偏多：较大成交量更多伴随价格上涨"
            elif correlation <= -0.25:
                conclusion = "量价偏空：较大成交量更多伴随价格下跌"
            else:
                conclusion = "量价中性：成交量与价格方向暂未形成明显共振"

            stats = {
                "bars": len(bars),
                "return_pct": round(100 * (last / first - 1), 2) if first else None,
                "high": max(float(b["high_price"]) for b in bars if b["high_price"] is not None),
                "low": min(float(b["low_price"]) for b in bars if b["low_price"] is not None),
                "total_volume": sum(volumes),
            }
            volume = {
                "average": round(average_volume, 2),
                "median": round(median_volume, 2),
                "latest": volumes[-1],
                "latest_ratio": (
                    round(volumes[-1] / average_volume, 2)
                    if average_volume
                    else None
                ),
                "up_volume": round(up_volume, 2),
                "down_volume": round(down_volume, 2),
                "up_down_ratio": (
                    round(up_volume / down_volume, 2)
                    if down_volume
                    else None
                ),
                "price_volume_correlation": round(correlation, 3),
                "conclusion": conclusion,
                "patterns": patterns,
                "top_bars": sorted(
                    enriched, key=lambda item: item["volume"], reverse=True
                )[:5],
            }
        return {
            "symbol": normalized,
            "interval": "1m",
            "bars": bars,
            "stats": stats,
            "volume_analysis": volume,
        }

    def market_impact(self, days: int = 14) -> dict:
        events = self.fetch_all(
            """
            SELECT event_type, event_time, name, actual, consensus, prior,
                   unit, surprise, confirmed, source, notes
            FROM macro_events
            WHERE event_time >= CURRENT_TIMESTAMP - make_interval(days => %s)
              AND event_time <= CURRENT_TIMESTAMP
            ORDER BY event_time DESC
            """,
            (days,),
        )
        upcoming = self.fetch_all(
            """
            SELECT event_type, event_time, name, consensus, prior, unit, confirmed
            FROM macro_events
            WHERE event_time > CURRENT_TIMESTAMP
            ORDER BY event_time
            LIMIT 8
            """
        )
        themes = self.theme_symbols()
        analyzed, unanalyzed = [], []
        for event in events:
            mapped = macro_impact(event, themes)
            if mapped:
                mapped["row_thesis"] = impact_row_thesis(mapped)
                analyzed.append(mapped)
            else:
                unanalyzed.append(event)
        news_themes = self.fetch_all(
            """
            SELECT unnest(themes) AS theme, sentiment, COUNT(*) AS articles
            FROM news_articles
            WHERE published_at >= CURRENT_TIMESTAMP - INTERVAL '3 days'
            GROUP BY 1, 2
            ORDER BY 1, 2
            """
        )
        theme_news: dict[str, dict] = {}
        for row in news_themes:
            entry = theme_news.setdefault(
                row["theme"],
                {
                    "theme": row["theme"],
                    "theme_name": THEME_NAMES.get(row["theme"], row["theme"]),
                    "positive": 0,
                    "neutral": 0,
                    "negative": 0,
                    "symbols": themes.get(row["theme"], []),
                },
            )
            entry[row["sentiment"]] = int(row["articles"])
        return {
            "macro": analyzed,
            "macro_unanalyzed": unanalyzed,
            "upcoming": upcoming,
            "news_themes": sorted(
                theme_news.values(),
                key=lambda item: item["positive"] + item["neutral"] + item["negative"],
                reverse=True,
            ),
        }

    def replay_day(self, date: str) -> dict:
        segments = self.segments_by_date(date)
        by_symbol: dict[str, dict] = {}
        for seg in segments:
            entry = by_symbol.setdefault(
                seg["symbol"],
                {
                    "symbol": seg["symbol"],
                    "segments": 0,
                    "large_buy_notional": 0.0,
                    "large_sell_notional": 0.0,
                    "largest_up": None,
                    "largest_down": None,
                },
            )
            entry["segments"] += 1
            entry["large_buy_notional"] += float(seg["large_buy_notional"] or 0)
            entry["large_sell_notional"] += float(seg["large_sell_notional"] or 0)
            change = float(seg["change_pct"] or 0)
            if change > 0 and (entry["largest_up"] is None or change > entry["largest_up"]["change_pct"]):
                entry["largest_up"] = {"change_pct": change, "start_time": seg["start_time"], "end_time": seg["end_time"], "rel_volume": seg["rel_volume"]}
            if change < 0 and (entry["largest_down"] is None or change < entry["largest_down"]["change_pct"]):
                entry["largest_down"] = {"change_pct": change, "start_time": seg["start_time"], "end_time": seg["end_time"], "rel_volume": seg["rel_volume"]}
        return {
            "date": date,
            "reviews": self.reviews_by_date(date),
            "segments_summary": sorted(by_symbol.values(), key=lambda x: x["symbol"]),
            "segments": segments,
            "events": self.events_between(date, date),
            "macro": self.macro_events_between(date, date),
        }

    def cboe_option_stats(self, trade_date: str | None = None) -> dict | None:
        if trade_date:
            rows = self.fetch_all(
                """SELECT trade_date, total_volume, total_call_volume, total_put_volume,
                          total_put_call, total_call_put, buckets, vix_put_call,
                          spx_put_call, source, disclaimer, captured_at
                   FROM cboe_option_stats WHERE trade_date = %s""",
                (trade_date,),
            )
        else:
            rows = self.fetch_all(
                """SELECT trade_date, total_volume, total_call_volume, total_put_volume,
                          total_put_call, total_call_put, buckets, vix_put_call,
                          spx_put_call, source, disclaimer, captured_at
                   FROM cboe_option_stats
                   ORDER BY trade_date DESC LIMIT 1"""
            )
        if not rows:
            return None
        row = dict(rows[0])
        row["trade_date"] = str(row["trade_date"]) if row.get("trade_date") else None
        return row
