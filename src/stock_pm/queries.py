from __future__ import annotations

import time
from typing import Any

from .impact import macro_impact, THEME_NAMES
from .scoring import sentiment_from_components


WATCHLIST_CACHE_SECONDS = 60.0


EARNINGS_SQL = """
            SELECT
                e.symbol, e.report_date, e.report_timing, e.fiscal_period,
                e.fiscal_year, e.period_end, e.currency, e.eps_actual,
                e.eps_estimate, e.eps_surprise_pct, e.revenue_actual,
                e.revenue_estimate, e.revenue_surprise_pct, e.source,
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
                    ) AS close_50d_ago
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
                ROUND(100 * (close_price / NULLIF(close_5d_ago, 0) - 1), 2) AS return_5d_pct,
                ROUND(100 * (close_price / NULLIF(close_20d_ago, 0) - 1), 2) AS return_20d_pct,
                ROUND(100 * (close_price / NULLIF(close_50d_ago, 0) - 1), 2) AS return_50d_pct,
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
        return [by_symbol[symbol] for symbol in requested if symbol in by_symbol]

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
        }

    def chart_history(self, symbol: str, limit: int = 260) -> list[dict]:
        normalized = self._watchlist_symbol(symbol)
        rows = self.fetch_all(
            """
            SELECT * FROM (
                SELECT
                    symbol, bar_time, close_price, volume,
                    AVG(close_price) OVER (ORDER BY bar_time ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
                    AVG(close_price) OVER (ORDER BY bar_time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                    AVG(close_price) OVER (ORDER BY bar_time ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma50,
                    CASE WHEN COUNT(*) OVER (
                        ORDER BY bar_time ROWS BETWEEN 199 PRECEDING AND CURRENT ROW
                    ) >= 200 THEN AVG(close_price) OVER (
                        ORDER BY bar_time ROWS BETWEEN 199 PRECEDING AND CURRENT ROW
                    ) END AS ma200
                FROM daily_price_bars
                WHERE symbol = %s AND bar_size = '1d'
            ) data
            ORDER BY bar_time DESC
            LIMIT %s
            """,
            (normalized, limit),
        )
        return list(reversed(rows))

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
        return self.fetch_all(
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
        bars = self.fetch_all(
            """
            SELECT DISTINCT ON (bar_time::date)
                   bar_time, open_price, high_price, low_price, close_price, volume
            FROM price_bars
            WHERE symbol = %s AND bar_size = '1d'
              AND bar_time >= %s AND bar_time < %s::date + 1
            ORDER BY bar_time::date, bar_time DESC
            """,
            (normalized, start, end),
        )
        stats = None
        if bars:
            first, last = float(bars[0]["close_price"]), float(bars[-1]["close_price"])
            stats = {
                "bars": len(bars),
                "return_pct": round(100 * (last / first - 1), 2) if first else None,
                "high": max(float(b["high_price"]) for b in bars if b["high_price"] is not None),
                "low": min(float(b["low_price"]) for b in bars if b["low_price"] is not None),
                "total_volume": sum(float(b["volume"] or 0) for b in bars),
            }
        return {"symbol": normalized, "bars": bars, "stats": stats}

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
