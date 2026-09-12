from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .errors import DatabaseError
from .impact import tag_news


class PersistMixin:
    def _invalidate_watchlist_cache(self) -> None:
        self._watchlist_cache = (0.0, [])

    def upsert_watchlist(self, row: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO watchlist
                        (symbol, name, primary_exchange, asset_class, sector,
                         themes, rate_sensitivity, active)
                    VALUES (%(symbol)s, %(name)s, %(primary_exchange)s,
                            %(asset_class)s, %(sector)s, %(themes)s,
                            %(rate_sensitivity)s, TRUE)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        primary_exchange = EXCLUDED.primary_exchange,
                        asset_class = EXCLUDED.asset_class,
                        sector = EXCLUDED.sector,
                        themes = EXCLUDED.themes,
                        rate_sensitivity = EXCLUDED.rate_sensitivity,
                        active = TRUE
                    """,
                    {
                        "symbol": row["symbol"].upper(),
                        "name": row.get("name") or row["symbol"].upper(),
                        "primary_exchange": row.get("primary_exchange", ""),
                        "asset_class": row.get("asset_class", "stocks"),
                        "sector": row.get("sector"),
                        "themes": list(row.get("themes") or []),
                        "rate_sensitivity": row.get("rate_sensitivity", "medium"),
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to upsert watchlist symbol: {exc}") from exc
        self._invalidate_watchlist_cache()

    def deactivate_watchlist(self, symbol: str) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    "UPDATE watchlist SET active = FALSE WHERE symbol = %s",
                    (symbol.upper(),),
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to deactivate watchlist symbol: {exc}") from exc
        self._invalidate_watchlist_cache()

    def store_large_trades(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        try:
            with self.pool.connection() as conn, conn.transaction():
                with conn.cursor() as cur:
                    for row in rows:
                        cur.execute(
                            """
                            INSERT INTO large_trades
                                (symbol, trade_time, price, size, notional,
                                 side_inferred, exchange, trade_id)
                            VALUES (%(symbol)s, %(trade_time)s, %(price)s,
                                    %(size)s, %(notional)s, %(side_inferred)s,
                                    %(exchange)s, %(trade_id)s)
                            ON CONFLICT (symbol, trade_time, price, size) DO NOTHING
                            """,
                            row,
                        )
            return len(rows)
        except Exception as exc:
            raise DatabaseError(f"Failed to store large trades: {exc}") from exc

    def store_segments(self, symbol: str, trade_date: str, segments: list[dict[str, Any]]) -> int:
        try:
            with self.pool.connection() as conn, conn.transaction():
                conn.execute(
                    "DELETE FROM intraday_segments WHERE symbol = %s AND trade_date = %s",
                    (symbol, trade_date),
                )
                with conn.cursor() as cur:
                    for seg in segments:
                        cur.execute(
                            """
                            INSERT INTO intraday_segments
                                (symbol, trade_date, seg_no, start_time, end_time,
                                 direction, start_price, end_price, change_pct,
                                 volume, rel_volume, vwap_side,
                                 large_buy_notional, large_sell_notional,
                                 large_trade_count)
                            VALUES (%(symbol)s, %(trade_date)s, %(seg_no)s,
                                    %(start_time)s, %(end_time)s, %(direction)s,
                                    %(start_price)s, %(end_price)s, %(change_pct)s,
                                    %(volume)s, %(rel_volume)s, %(vwap_side)s,
                                    %(large_buy_notional)s, %(large_sell_notional)s,
                                    %(large_trade_count)s)
                            """,
                            {**seg, "symbol": symbol, "trade_date": trade_date},
                        )
            return len(segments)
        except Exception as exc:
            raise DatabaseError(f"Failed to store segments: {exc}") from exc

    def store_macro_event(self, event: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO macro_events
                        (event_type, event_time, name, actual, consensus, prior,
                         unit, surprise, confirmed, source, notes)
                    VALUES (%(event_type)s, %(event_time)s, %(name)s, %(actual)s,
                            %(consensus)s, %(prior)s, %(unit)s, %(surprise)s,
                            %(confirmed)s, %(source)s, %(notes)s)
                    ON CONFLICT (event_type, event_time) DO UPDATE SET
                        name = EXCLUDED.name,
                        actual = COALESCE(EXCLUDED.actual, macro_events.actual),
                        consensus = COALESCE(EXCLUDED.consensus, macro_events.consensus),
                        prior = COALESCE(EXCLUDED.prior, macro_events.prior),
                        unit = COALESCE(EXCLUDED.unit, macro_events.unit),
                        surprise = CASE WHEN EXCLUDED.surprise <> 'unknown'
                                        THEN EXCLUDED.surprise
                                        ELSE macro_events.surprise END,
                        confirmed = EXCLUDED.confirmed,
                        source = EXCLUDED.source,
                        notes = COALESCE(EXCLUDED.notes, macro_events.notes)
                    """,
                    {
                        "actual": None,
                        "consensus": None,
                        "prior": None,
                        "unit": None,
                        "confirmed": True,
                        "source": "manual",
                        "notes": None,
                        **event,
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to store macro event: {exc}") from exc

    def quarantine_invalid_daily_bars(self) -> int:
        """Delete stored daily bars that fail OHLC constraints. Does not invent replacements."""
        from .bars import is_valid_ohlc

        try:
            with self.pool.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT symbol, bar_size, bar_time, open_price, high_price,
                           low_price, close_price
                    FROM price_bars WHERE bar_size = '1d'
                    """
                ).fetchall()
                removed = 0
                for row in rows:
                    payload = {
                        "open_price": row[3],
                        "high_price": row[4],
                        "low_price": row[5],
                        "close_price": row[6],
                    }
                    if is_valid_ohlc(payload):
                        continue
                    conn.execute(
                        """
                        DELETE FROM price_bars
                        WHERE symbol = %s AND bar_size = %s AND bar_time = %s
                        """,
                        (row[0], row[1], row[2]),
                    )
                    removed += 1
                return removed
        except Exception as exc:
            raise DatabaseError(f"Failed to quarantine invalid daily bars: {exc}") from exc
    def store_event(self, event: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO market_events (
                        symbol, event_time, event_type, severity, title,
                        details, source, unique_key
                    ) VALUES (
                        %(symbol)s, %(event_time)s, %(event_type)s, %(severity)s,
                        %(title)s, %(details)s, %(source)s, %(unique_key)s
                    ) ON CONFLICT (unique_key) DO NOTHING
                    """,
                    {**event, "details": Jsonb(event.get("details", {}))},
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to store market event: {exc}") from exc

    def store_review(self, review: dict[str, Any]) -> None:
        payload = {
            "rule_bias": None,
            "watch_low": None,
            "watch_high": None,
            "llm_why": None,
            "llm_outlook": None,
            "llm_bias": None,
            "llm_model": None,
            "llm_status": "missing_key",
            "llm_context_hash": None,
            "llm_generated_at": None,
            "llm_error": None,
            **review,
            "metrics": Jsonb(review.get("metrics", {})),
            "context": Jsonb(review.get("context", {})),
            "llm_status": review.get("llm_status") or "missing_key",
        }
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO daily_reviews (
                        symbol, review_date, close_price, short_trend,
                        medium_trend, long_trend, support_price, resistance_price,
                        breakout_status, large_trade_count, unusual_option_count,
                        score, summary, metrics, rule_bias, watch_low, watch_high,
                        context, llm_why, llm_outlook, llm_bias, llm_model, llm_status,
                        llm_context_hash, llm_generated_at, llm_error
                    ) VALUES (
                        %(symbol)s, %(review_date)s, %(close_price)s,
                        %(short_trend)s, %(medium_trend)s, %(long_trend)s,
                        %(support_price)s, %(resistance_price)s,
                        %(breakout_status)s, %(large_trade_count)s,
                        %(unusual_option_count)s, %(score)s, %(summary)s,
                        %(metrics)s, %(rule_bias)s, %(watch_low)s, %(watch_high)s,
                        %(context)s, %(llm_why)s, %(llm_outlook)s, %(llm_bias)s,
                        %(llm_model)s, %(llm_status)s, %(llm_context_hash)s,
                        %(llm_generated_at)s, %(llm_error)s
                    ) ON CONFLICT (symbol, review_date) DO UPDATE SET
                        close_price = EXCLUDED.close_price,
                        short_trend = EXCLUDED.short_trend,
                        medium_trend = EXCLUDED.medium_trend,
                        long_trend = EXCLUDED.long_trend,
                        support_price = EXCLUDED.support_price,
                        resistance_price = EXCLUDED.resistance_price,
                        breakout_status = EXCLUDED.breakout_status,
                        large_trade_count = EXCLUDED.large_trade_count,
                        unusual_option_count = EXCLUDED.unusual_option_count,
                        score = EXCLUDED.score,
                        summary = EXCLUDED.summary,
                        metrics = EXCLUDED.metrics,
                        rule_bias = EXCLUDED.rule_bias,
                        watch_low = EXCLUDED.watch_low,
                        watch_high = EXCLUDED.watch_high,
                        context = EXCLUDED.context,
                        llm_why = EXCLUDED.llm_why,
                        llm_outlook = EXCLUDED.llm_outlook,
                        llm_bias = EXCLUDED.llm_bias,
                        llm_model = EXCLUDED.llm_model,
                        llm_status = EXCLUDED.llm_status,
                        llm_context_hash = EXCLUDED.llm_context_hash,
                        llm_generated_at = EXCLUDED.llm_generated_at,
                        llm_error = EXCLUDED.llm_error,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    payload,
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to store daily review: {exc}") from exc

    def update_review_user(self, symbol: str, review_date: str, body: dict[str, Any]) -> dict:
        """Save optional user notes. This is not a daily confirm gate.

        Empty bias/outlook/note clears the saved note timestamp so the auto
        loop (rule/llm) remains the default outlook source.
        """
        from datetime import datetime, timezone

        from .analytics import VALID_BIASES

        bias = body.get("user_bias")
        if bias not in {None, "", *VALID_BIASES, "观望"}:
            raise ValueError("user_bias must be 偏多, 中性, 偏空 or 观望")
        outlook = body.get("user_outlook")
        note = body.get("user_note")
        confirmed = datetime.now(timezone.utc)
        try:
            with self.pool.connection() as conn:
                rows = list(
                    conn.execute(
                        """
                        UPDATE daily_reviews SET
                            user_bias = %s,
                            user_outlook = %s,
                            user_note = %s,
                            user_confirmed_at = %s
                        WHERE symbol = %s AND review_date = %s
                        RETURNING *
                        """,
                        (
                            bias or None,
                            outlook,
                            note,
                            confirmed if (bias or outlook or note) else None,
                            symbol,
                            review_date,
                        ),
                    )
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to update review notes: {exc}") from exc
        if not rows:
            raise ValueError(f"No review for {symbol} on {review_date}")
        return rows[0]

    def fill_review_outcome(self, symbol: str, review_date: str, actual: dict[str, Any]) -> None:
        from .analytics import judge_outcome, pick_outlook_bias

        try:
            with self.pool.connection() as conn:
                existing = conn.execute(
                    """SELECT * FROM daily_reviews
                       WHERE symbol = %s AND review_date = %s""",
                    (symbol, review_date),
                ).fetchone()
                if not existing:
                    return
                bias, source = pick_outlook_bias(existing)
                vs_bias = judge_outcome(
                    bias,
                    actual.get("outcome_return_pct"),
                    bool(actual.get("outcome_broke_support")),
                    bool(actual.get("broke_resistance")),
                )
                conn.execute(
                    """
                    UPDATE daily_reviews SET
                        outcome_return_pct = %s,
                        outcome_volume_ratio = %s,
                        outcome_broke_support = %s,
                        outcome_vs_bias = %s,
                        outcome_bias_source = %s
                    WHERE symbol = %s AND review_date = %s
                    """,
                    (
                        actual.get("outcome_return_pct"),
                        actual.get("outcome_volume_ratio"),
                        actual.get("outcome_broke_support"),
                        vs_bias,
                        source,
                        symbol,
                        review_date,
                    ),
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to fill review outcome: {exc}") from exc

    def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        captured_at = payload["captured_at"]
        source = payload.get("source", "alpaca")
        counts = {
            "snapshots": len(payload.get("snapshots", [])),
            "bars": sum(len(item.get("bars", [])) for item in payload.get("history", [])),
            "positions": len(payload.get("positions", [])),
            "trades": len(payload.get("trades", [])),
            "account": int(bool(payload.get("account"))),
            "options": len(payload.get("options", [])),
            "news": len(payload.get("news", [])),
            "fundamentals": len(payload.get("fundamentals", [])),
            "earnings": len(payload.get("earnings", [])),
        }
        try:
            with self.pool.connection() as conn, conn.transaction():
                with conn.cursor() as cur:
                    for row in payload.get("snapshots", []):
                        cur.execute(
                            """
                            INSERT INTO market_snapshots (
                                symbol, contract_id, captured_at, last_price, bid, ask,
                                open_price, high_price, low_price, prior_close, volume,
                                halted, source, raw_data
                            ) VALUES (
                                %(symbol)s, %(contract_id)s, %(captured_at)s,
                                %(last_price)s, %(bid)s, %(ask)s, %(open_price)s,
                                %(high_price)s, %(low_price)s, %(prior_close)s,
                                %(volume)s, %(halted)s, %(source)s, %(raw_data)s
                            ) ON CONFLICT (symbol, captured_at) DO UPDATE SET
                                last_price = EXCLUDED.last_price,
                                bid = EXCLUDED.bid,
                                ask = EXCLUDED.ask,
                                volume = EXCLUDED.volume,
                                source = EXCLUDED.source,
                                raw_data = EXCLUDED.raw_data
                            """,
                            {
                                **row,
                                "contract_id": row.get("contract_id") or 0,
                                "captured_at": captured_at,
                                "source": row.get("source", source),
                                "raw_data": Jsonb(row),
                            },
                        )
                    for series in payload.get("history", []):
                        from .bars import is_valid_ohlc

                        for bar in series.get("bars", []):
                            if series.get("bar_size", "1d") == "1d" and not is_valid_ohlc(bar):
                                continue
                            cur.execute(
                                """
                                INSERT INTO price_bars (
                                symbol, bar_size, bar_time, open_price, high_price,
                                low_price, close_price, volume, source, raw_data
                                ) VALUES (
                                    %(symbol)s, %(bar_size)s, %(bar_time)s,
                                    %(open_price)s, %(high_price)s, %(low_price)s,
                                    %(close_price)s, %(volume)s, %(source)s, %(raw_data)s
                                ) ON CONFLICT (symbol, bar_size, bar_time) DO UPDATE SET
                                    open_price = EXCLUDED.open_price,
                                    high_price = EXCLUDED.high_price,
                                    low_price = EXCLUDED.low_price,
                                    close_price = EXCLUDED.close_price,
                                    volume = EXCLUDED.volume,
                                    source = EXCLUDED.source,
                                    raw_data = EXCLUDED.raw_data
                                """,
                                {
                                    **bar,
                                    "symbol": series["symbol"],
                                    "bar_size": series.get("bar_size", "1d"),
                                    "source": series.get("source", source),
                                    "raw_data": Jsonb(bar),
                                },
                            )
                    for row in payload.get("positions", []):
                        cur.execute(
                            """
                            INSERT INTO position_snapshots (
                                captured_at, contract_id, symbol, description,
                                asset_class, currency, quantity, average_price,
                                market_price, market_value, daily_pnl, unrealized_pnl,
                                raw_data
                            ) VALUES (
                                %(captured_at)s, %(contract_id)s, %(symbol)s,
                                %(description)s, %(asset_class)s, %(currency)s,
                                %(quantity)s, %(average_price)s, %(market_price)s,
                                %(market_value)s, %(daily_pnl)s, %(unrealized_pnl)s,
                                %(raw_data)s
                            ) ON CONFLICT (captured_at, contract_id) DO NOTHING
                            """,
                            {**row, "captured_at": captured_at, "raw_data": Jsonb(row)},
                        )
                    for row in payload.get("trades", []):
                        cur.execute(
                            """
                            INSERT INTO trades (
                                trade_id, symbol, trade_time, side, quantity, price,
                                commission, realized_pnl, currency, exchange,
                                company_name, raw_data, synced_at
                            ) VALUES (
                                %(trade_id)s, %(symbol)s, %(trade_time)s, %(side)s,
                                %(quantity)s, %(price)s, %(commission)s,
                                %(realized_pnl)s, %(currency)s, %(exchange)s,
                                %(company_name)s, %(raw_data)s, %(synced_at)s
                            ) ON CONFLICT (trade_id) DO UPDATE SET
                                commission = EXCLUDED.commission,
                                realized_pnl = EXCLUDED.realized_pnl,
                                raw_data = EXCLUDED.raw_data,
                                synced_at = EXCLUDED.synced_at
                            """,
                            {**row, "synced_at": captured_at, "raw_data": Jsonb(row)},
                        )
                    account = payload.get("account")
                    if account:
                        cur.execute(
                            """
                            INSERT INTO account_snapshots (
                                captured_at, currency, net_liquidation,
                                total_cash_value, gross_position_value,
                                available_funds, buying_power, maintenance_margin,
                                excess_liquidity, raw_data
                            ) VALUES (
                                %(captured_at)s, %(currency)s, %(net_liquidation)s,
                                %(total_cash_value)s, %(gross_position_value)s,
                                %(available_funds)s, %(buying_power)s,
                                %(maintenance_margin)s, %(excess_liquidity)s,
                                %(raw_data)s
                            ) ON CONFLICT (captured_at) DO NOTHING
                            """,
                            {**account, "captured_at": captured_at, "raw_data": Jsonb(account)},
                        )
                    for row in payload.get("options", []):
                        cur.execute(
                            """
                            INSERT INTO option_wall_snapshots (
                                symbol, expiration_date, strike, captured_at,
                                spot_price, call_last, call_bid, call_ask,
                                call_volume, call_open_interest, call_implied_volatility,
                                put_last, put_bid, put_ask, put_volume,
                                put_open_interest, put_implied_volatility, raw_data
                            ) VALUES (
                                %(symbol)s, %(expiration_date)s, %(strike)s, %(captured_at)s,
                                %(spot_price)s, %(call_last)s, %(call_bid)s, %(call_ask)s,
                                %(call_volume)s, %(call_open_interest)s, %(call_implied_volatility)s,
                                %(put_last)s, %(put_bid)s, %(put_ask)s, %(put_volume)s,
                                %(put_open_interest)s, %(put_implied_volatility)s, %(raw_data)s
                            ) ON CONFLICT (symbol, expiration_date, strike, captured_at)
                              DO UPDATE SET
                                call_volume = EXCLUDED.call_volume,
                                call_open_interest = EXCLUDED.call_open_interest,
                                put_volume = EXCLUDED.put_volume,
                                put_open_interest = EXCLUDED.put_open_interest,
                                raw_data = EXCLUDED.raw_data
                            """,
                            {**row, "captured_at": captured_at, "raw_data": Jsonb(row)},
                        )
                    for row in payload.get("news", []):
                        themes = row.get("themes")
                        if themes is None:
                            themes = tag_news(
                                f"{row.get('headline', '')} {row.get('summary', '')}"
                            )
                        cur.execute(
                            """
                            INSERT INTO news_articles (
                                symbol, headline, summary, source, published_at,
                                url, sentiment, themes, synced_at, raw_data
                            ) VALUES (
                                %(symbol)s, %(headline)s, %(summary)s, %(source)s,
                                %(published_at)s, %(url)s, %(sentiment)s,
                                %(themes)s, %(synced_at)s, %(raw_data)s
                            ) ON CONFLICT (symbol, url) DO UPDATE SET
                                headline = EXCLUDED.headline,
                                summary = EXCLUDED.summary,
                                source = EXCLUDED.source,
                                published_at = EXCLUDED.published_at,
                                sentiment = EXCLUDED.sentiment,
                                themes = EXCLUDED.themes,
                                synced_at = EXCLUDED.synced_at,
                                raw_data = EXCLUDED.raw_data
                            """,
                            {
                                **row,
                                "themes": list(themes),
                                "synced_at": captured_at,
                                "raw_data": Jsonb(row),
                            },
                        )
                    for row in payload.get("fundamentals", []):
                        values = {
                            "symbol": row["symbol"].upper(),
                            "captured_at": row.get("captured_at", captured_at),
                            "currency": row.get("currency", "USD"),
                            "market_cap": row.get("market_cap"),
                            "enterprise_value": row.get("enterprise_value"),
                            "pe_ttm": row.get("pe_ttm"),
                            "pe_forward": row.get("pe_forward"),
                            "peg_ratio": row.get("peg_ratio"),
                            "price_to_book": row.get("price_to_book"),
                            "price_to_sales": row.get("price_to_sales"),
                            "ev_to_ebitda": row.get("ev_to_ebitda"),
                            "eps_ttm": row.get("eps_ttm"),
                            "revenue_ttm": row.get("revenue_ttm"),
                            "gross_margin_pct": row.get("gross_margin_pct"),
                            "operating_margin_pct": row.get("operating_margin_pct"),
                            "net_margin_pct": row.get("net_margin_pct"),
                            "revenue_growth_yoy_pct": row.get("revenue_growth_yoy_pct"),
                            "eps_growth_yoy_pct": row.get("eps_growth_yoy_pct"),
                            "dividend_yield_pct": row.get("dividend_yield_pct"),
                            "beta": row.get("beta"),
                            "analyst_target_price": row.get("analyst_target_price"),
                            "source": row.get("source", "fundamentals_feed"),
                            "raw_data": Jsonb(row),
                        }
                        cur.execute(
                            """
                            INSERT INTO fundamentals_snapshots (
                                symbol, captured_at, currency, market_cap,
                                enterprise_value, pe_ttm, pe_forward, peg_ratio,
                                price_to_book, price_to_sales, ev_to_ebitda,
                                eps_ttm, revenue_ttm, gross_margin_pct,
                                operating_margin_pct, net_margin_pct,
                                revenue_growth_yoy_pct, eps_growth_yoy_pct,
                                dividend_yield_pct, beta, analyst_target_price,
                                source, raw_data
                            ) VALUES (
                                %(symbol)s, %(captured_at)s, %(currency)s,
                                %(market_cap)s, %(enterprise_value)s, %(pe_ttm)s,
                                %(pe_forward)s, %(peg_ratio)s, %(price_to_book)s,
                                %(price_to_sales)s, %(ev_to_ebitda)s, %(eps_ttm)s,
                                %(revenue_ttm)s, %(gross_margin_pct)s,
                                %(operating_margin_pct)s, %(net_margin_pct)s,
                                %(revenue_growth_yoy_pct)s, %(eps_growth_yoy_pct)s,
                                %(dividend_yield_pct)s, %(beta)s,
                                %(analyst_target_price)s, %(source)s, %(raw_data)s
                            ) ON CONFLICT (symbol, captured_at) DO UPDATE SET
                                market_cap = EXCLUDED.market_cap,
                                pe_ttm = EXCLUDED.pe_ttm,
                                pe_forward = EXCLUDED.pe_forward,
                                revenue_growth_yoy_pct = EXCLUDED.revenue_growth_yoy_pct,
                                eps_growth_yoy_pct = EXCLUDED.eps_growth_yoy_pct,
                                analyst_target_price = EXCLUDED.analyst_target_price,
                                raw_data = EXCLUDED.raw_data
                            """,
                            values,
                        )
                    for row in payload.get("earnings", []):
                        values = {
                            "symbol": row["symbol"].upper(),
                            "report_date": row["report_date"],
                            "report_timing": row.get("report_timing", "unknown"),
                            "fiscal_period": row["fiscal_period"],
                            "fiscal_year": row.get("fiscal_year"),
                            "period_end": row.get("period_end"),
                            "currency": row.get("currency", "USD"),
                            "eps_actual": row.get("eps_actual"),
                            "eps_estimate": row.get("eps_estimate"),
                            "eps_surprise_pct": row.get("eps_surprise_pct"),
                            "revenue_actual": row.get("revenue_actual"),
                            "revenue_estimate": row.get("revenue_estimate"),
                            "revenue_surprise_pct": row.get("revenue_surprise_pct"),
                            "net_income_actual": row.get("net_income_actual"),
                            "net_income_estimate": row.get("net_income_estimate"),
                            "net_income_surprise_pct": row.get("net_income_surprise_pct"),
                            "provider_fields": Jsonb(row.get("provider_fields", {})),
                            "source": row.get("source", "earnings_feed"),
                            "synced_at": captured_at,
                            "raw_data": Jsonb(row),
                        }
                        cur.execute(
                            """
                            INSERT INTO earnings_reports (
                                symbol, report_date, report_timing, fiscal_period,
                                fiscal_year, period_end, currency, eps_actual,
                                eps_estimate, eps_surprise_pct, revenue_actual,
                                revenue_estimate, revenue_surprise_pct,
                                net_income_actual, net_income_estimate,
                                net_income_surprise_pct, provider_fields,
                                source, synced_at, raw_data
                            ) VALUES (
                                %(symbol)s, %(report_date)s, %(report_timing)s,
                                %(fiscal_period)s, %(fiscal_year)s, %(period_end)s,
                                %(currency)s, %(eps_actual)s, %(eps_estimate)s,
                                %(eps_surprise_pct)s, %(revenue_actual)s,
                                %(revenue_estimate)s, %(revenue_surprise_pct)s,
                                %(net_income_actual)s, %(net_income_estimate)s,
                                %(net_income_surprise_pct)s, %(provider_fields)s,
                                %(source)s, %(synced_at)s, %(raw_data)s
                            ) ON CONFLICT (symbol, report_date, fiscal_period) DO UPDATE SET
                                eps_actual = EXCLUDED.eps_actual,
                                eps_estimate = EXCLUDED.eps_estimate,
                                eps_surprise_pct = EXCLUDED.eps_surprise_pct,
                                revenue_actual = EXCLUDED.revenue_actual,
                                revenue_estimate = EXCLUDED.revenue_estimate,
                                revenue_surprise_pct = EXCLUDED.revenue_surprise_pct,
                                net_income_actual = EXCLUDED.net_income_actual,
                                net_income_estimate = EXCLUDED.net_income_estimate,
                                net_income_surprise_pct = EXCLUDED.net_income_surprise_pct,
                                provider_fields = EXCLUDED.provider_fields,
                                report_timing = EXCLUDED.report_timing,
                                source = EXCLUDED.source,
                                synced_at = EXCLUDED.synced_at,
                                raw_data = EXCLUDED.raw_data
                            """,
                            values,
                        )
                    cur.execute(
                        """
                        INSERT INTO sync_runs
                            (source, started_at, status, item_counts)
                        VALUES (%(source)s, %(captured_at)s, 'success', %(counts)s)
                        """,
                        {
                            "source": source,
                            "captured_at": captured_at,
                            "counts": Jsonb(counts),
                        },
                    )
            return counts
        except Exception as exc:
            raise DatabaseError(f"PostgreSQL ingestion failed: {exc}") from exc

    def store_cboe_option_stats(self, snapshot: dict[str, Any]) -> None:
        payload = {
            "trade_date": snapshot["trade_date"],
            "total_volume": snapshot.get("total_volume"),
            "total_call_volume": snapshot.get("total_call_volume"),
            "total_put_volume": snapshot.get("total_put_volume"),
            "total_put_call": snapshot.get("total_put_call"),
            "total_call_put": snapshot.get("total_call_put"),
            "buckets": Jsonb(snapshot.get("buckets") or []),
            "vix_put_call": snapshot.get("vix_put_call"),
            "spx_put_call": snapshot.get("spx_put_call"),
            "source": snapshot.get("source") or "cboe",
            "disclaimer": snapshot.get("disclaimer"),
            "raw": Jsonb(snapshot.get("raw") or {}),
        }
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO cboe_option_stats (
                        trade_date, total_volume, total_call_volume, total_put_volume,
                        total_put_call, total_call_put, buckets, vix_put_call,
                        spx_put_call, source, disclaimer, raw
                    ) VALUES (
                        %(trade_date)s, %(total_volume)s, %(total_call_volume)s,
                        %(total_put_volume)s, %(total_put_call)s, %(total_call_put)s,
                        %(buckets)s, %(vix_put_call)s, %(spx_put_call)s,
                        %(source)s, %(disclaimer)s, %(raw)s
                    ) ON CONFLICT (trade_date) DO UPDATE SET
                        total_volume = EXCLUDED.total_volume,
                        total_call_volume = EXCLUDED.total_call_volume,
                        total_put_volume = EXCLUDED.total_put_volume,
                        total_put_call = EXCLUDED.total_put_call,
                        total_call_put = EXCLUDED.total_call_put,
                        buckets = EXCLUDED.buckets,
                        vix_put_call = EXCLUDED.vix_put_call,
                        spx_put_call = EXCLUDED.spx_put_call,
                        source = EXCLUDED.source,
                        disclaimer = EXCLUDED.disclaimer,
                        raw = EXCLUDED.raw,
                        captured_at = CURRENT_TIMESTAMP
                    """,
                    payload,
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to store Cboe option stats: {exc}") from exc

    def append_environment_snapshot(self, snapshot: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO environment_snapshots (
                        as_of_date, scope, symbol, one_liner, row_thesis,
                        struct, missing_flags, publish_state
                    ) VALUES (
                        %(as_of_date)s, %(scope)s, %(symbol)s, %(one_liner)s,
                        %(row_thesis)s, %(struct)s, %(missing_flags)s,
                        %(publish_state)s
                    )
                    """,
                    {
                        "as_of_date": snapshot.get("as_of_date"),
                        "scope": snapshot.get("scope") or "market",
                        "symbol": snapshot.get("symbol"),
                        "one_liner": snapshot.get("one_liner"),
                        "row_thesis": snapshot.get("row_thesis"),
                        "struct": Jsonb(snapshot.get("struct") or {}),
                        "missing_flags": Jsonb(snapshot.get("missingFlags") or []),
                        "publish_state": snapshot.get("publishState") or "draft",
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to append environment snapshot: {exc}") from exc

    def append_severity_alerts(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not alerts:
            return []
        written: list[dict[str, Any]] = []
        try:
            with self.pool.connection() as conn:
                for alert in alerts:
                    row = conn.execute(
                        """
                        INSERT INTO severity_alerts (
                            alert_key, severity, title, message, symbol, active,
                            prediction_id
                        ) VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                        RETURNING id
                        """,
                        (
                            alert.get("alert_key"),
                            alert.get("severity") or "severe",
                            alert.get("title") or "",
                            alert.get("message") or "",
                            alert.get("symbol"),
                            alert.get("prediction_id"),
                        ),
                    ).fetchone()
                    if row:
                        alert["id"] = row["id"]
                    written.append(alert)
        except Exception as exc:
            raise DatabaseError(f"Failed to append severity alerts: {exc}") from exc
        return written

    def append_tape_analysis(self, snapshot: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tape_analyses (
                        as_of_date, symbol, one_liner, conclusion,
                        struct, missing_flags, publish_state
                    ) VALUES (
                        %(as_of_date)s, %(symbol)s, %(one_liner)s, %(conclusion)s,
                        %(struct)s, %(missing_flags)s, %(publish_state)s
                    )
                    """,
                    {
                        "as_of_date": snapshot.get("as_of_date"),
                        "symbol": snapshot.get("symbol"),
                        "one_liner": snapshot.get("one_liner"),
                        "conclusion": snapshot.get("conclusion") or snapshot.get("one_liner"),
                        "struct": Jsonb(snapshot.get("struct") or {}),
                        "missing_flags": Jsonb(snapshot.get("missingFlags") or []),
                        "publish_state": snapshot.get("publishState") or "draft",
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to append tape analysis: {exc}") from exc

    def append_review_note(self, note: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO review_notes (
                        as_of_date, symbol, summary, explanation, unexplained,
                        struct, missing_flags, publish_state
                    ) VALUES (
                        %(as_of_date)s, %(symbol)s, %(summary)s, %(explanation)s,
                        %(unexplained)s, %(struct)s, %(missing_flags)s,
                        %(publish_state)s
                    )
                    """,
                    {
                        "as_of_date": note.get("as_of_date"),
                        "symbol": note.get("symbol"),
                        "summary": note.get("summary"),
                        "explanation": note.get("explanation"),
                        "unexplained": bool(note.get("unexplained")),
                        "struct": Jsonb(note.get("struct") or {}),
                        "missing_flags": Jsonb(note.get("missingFlags") or []),
                        "publish_state": note.get("publishState") or "draft",
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to append review note: {exc}") from exc

    def append_prediction(self, snapshot: dict[str, Any]) -> dict:
        try:
            with self.pool.connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO predictions (
                        as_of_date, symbol, state, window_start, window_end,
                        window_days, window_label, thesis, entry_price,
                        upside_bound_pct, downside_bound_pct, upside_price,
                        downside_price, struct, missing_flags, publish_state,
                        supersedes_id, superseded_by_id, change_reason
                    ) VALUES (
                        %(as_of_date)s, %(symbol)s, %(state)s, %(window_start)s,
                        %(window_end)s, %(window_days)s, %(window_label)s,
                        %(thesis)s, %(entry_price)s, %(upside_bound_pct)s,
                        %(downside_bound_pct)s, %(upside_price)s,
                        %(downside_price)s, %(struct)s, %(missing_flags)s,
                        %(publish_state)s, %(supersedes_id)s, %(superseded_by_id)s,
                        %(change_reason)s
                    )
                    RETURNING id
                    """,
                    {
                        "as_of_date": snapshot.get("as_of_date"),
                        "symbol": snapshot.get("symbol"),
                        "state": snapshot.get("state") or "missing",
                        "window_start": snapshot.get("window_start"),
                        "window_end": snapshot.get("window_end"),
                        "window_days": snapshot.get("window_days"),
                        "window_label": snapshot.get("window_label"),
                        "thesis": snapshot.get("thesis") or snapshot.get("one_liner"),
                        "entry_price": snapshot.get("entry_price"),
                        "upside_bound_pct": snapshot.get("upside_bound_pct"),
                        "downside_bound_pct": snapshot.get("downside_bound_pct"),
                        "upside_price": snapshot.get("upside_price"),
                        "downside_price": snapshot.get("downside_price"),
                        "struct": Jsonb(snapshot.get("struct") or {}),
                        "missing_flags": Jsonb(snapshot.get("missingFlags") or []),
                        "publish_state": snapshot.get("publishState") or "draft",
                        "supersedes_id": snapshot.get("supersedes_id"),
                        "superseded_by_id": snapshot.get("superseded_by_id"),
                        "change_reason": snapshot.get("change_reason"),
                    },
                ).fetchone()
        except Exception as exc:
            raise DatabaseError(f"Failed to append prediction: {exc}") from exc
        if row:
            snapshot["id"] = row["id"]
        return snapshot

    def update_prediction_state(self, snapshot: dict[str, Any]) -> None:
        """Advance state / leave-trace pointers. Never rewrite bounds or thesis."""
        pred_id = snapshot.get("id")
        if not pred_id:
            return
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    UPDATE predictions SET
                        state = %s,
                        superseded_by_id = COALESCE(%s, superseded_by_id),
                        change_reason = COALESCE(%s, change_reason),
                        struct = %s
                    WHERE id = %s
                    """,
                    (
                        snapshot.get("state"),
                        snapshot.get("superseded_by_id"),
                        snapshot.get("change_reason"),
                        Jsonb(snapshot.get("struct") or {}),
                        pred_id,
                    ),
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to update prediction state: {exc}") from exc

    def append_prediction_check(self, check: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO prediction_checks (
                        prediction_id, as_of_date, symbol, close_price,
                        high_price, low_price, max_gain_pct, max_drawdown_pct,
                        in_bounds, outcome, reason, struct
                    ) VALUES (
                        %(prediction_id)s, %(as_of_date)s, %(symbol)s,
                        %(close_price)s, %(high_price)s, %(low_price)s,
                        %(max_gain_pct)s, %(max_drawdown_pct)s, %(in_bounds)s,
                        %(outcome)s, %(reason)s, %(struct)s
                    )
                    """,
                    {
                        "prediction_id": check.get("prediction_id"),
                        "as_of_date": check.get("as_of_date"),
                        "symbol": check.get("symbol"),
                        "close_price": check.get("close_price"),
                        "high_price": check.get("high_price"),
                        "low_price": check.get("low_price"),
                        "max_gain_pct": check.get("max_gain_pct"),
                        "max_drawdown_pct": check.get("max_drawdown_pct"),
                        "in_bounds": check.get("in_bounds"),
                        "outcome": check.get("outcome") or "tracking",
                        "reason": check.get("reason"),
                        "struct": Jsonb(
                            {
                                "next_state": check.get("next_state"),
                                "outcome": check.get("outcome"),
                            }
                        ),
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to append prediction check: {exc}") from exc

    def append_job_run(self, job: dict[str, Any]) -> None:
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO job_runs (
                        job_name, started_at, completed_at, status, item_counts, error
                    ) VALUES (
                        %(job_name)s, COALESCE(%(started_at)s, CURRENT_TIMESTAMP),
                        %(completed_at)s, %(status)s, %(item_counts)s, %(error)s
                    )
                    """,
                    {
                        "job_name": job.get("job_name") or "unknown",
                        "started_at": job.get("started_at"),
                        "completed_at": job.get("completed_at"),
                        "status": job.get("status") or "success",
                        "item_counts": Jsonb(job.get("item_counts") or {}),
                        "error": job.get("error"),
                    },
                )
        except Exception as exc:
            raise DatabaseError(f"Failed to append job run: {exc}") from exc
