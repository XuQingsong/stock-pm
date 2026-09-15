"""Read-only sources for rebuilding a Research Pack. Do not copy raw tables."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class PackSource(Protocol):
    def issuer(self, ticker: str) -> dict[str, Any] | None: ...
    def earnings(self, ticker: str, *, limit: int = 6) -> list[dict[str, Any]]: ...
    def fundamentals(self, ticker: str) -> dict[str, Any] | None: ...
    def transcripts(self, ticker: str) -> list[dict[str, Any]]: ...
    def news(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]: ...
    def events(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]: ...
    def guidance(self, ticker: str) -> list[dict[str, Any]]: ...


class DictPackSource:
    """Fixture or test overlay. Production workflow uses DatabasePackSource."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = {str(key).upper(): dict(value or {}) for key, value in (payload or {}).items()}

    @classmethod
    def from_mapping(cls, ticker: str, row: dict[str, Any]) -> "DictPackSource":
        return cls({ticker: row})

    def _row(self, ticker: str) -> dict[str, Any]:
        return dict(self.payload.get(str(ticker or "").upper()) or {})

    def issuer(self, ticker: str) -> dict[str, Any] | None:
        row = self._row(ticker).get("issuer")
        return dict(row) if isinstance(row, dict) else None

    def earnings(self, ticker: str, *, limit: int = 6) -> list[dict[str, Any]]:
        rows = list(self._row(ticker).get("earnings") or [])
        return [dict(item) for item in rows[:limit]]

    def fundamentals(self, ticker: str) -> dict[str, Any] | None:
        row = self._row(ticker).get("fundamentals")
        return dict(row) if isinstance(row, dict) else None

    def transcripts(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._row(ticker).get("transcripts") or [])]

    def news(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        del days
        return [dict(item) for item in (self._row(ticker).get("news") or [])]

    def events(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        del days
        return [dict(item) for item in (self._row(ticker).get("events") or [])]

    def guidance(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._row(ticker).get("guidance") or [])]


class DatabasePackSource:
    def __init__(self, database: Any) -> None:
        self.database = database

    def _fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            if hasattr(self.database, "ping") and not self.database.ping():
                return []
            return list(self.database.fetch_all(sql, params) or [])
        except Exception:
            return []

    def issuer(self, ticker: str) -> dict[str, Any] | None:
        rows = self._fetch(
            "SELECT * FROM issuer_profiles WHERE ticker = %s",
            (ticker.upper(),),
        )
        return rows[0] if rows else None

    def earnings(self, ticker: str, *, limit: int = 6) -> list[dict[str, Any]]:
        sql = """
            SELECT
                e.symbol, e.report_date, e.report_timing, e.fiscal_period,
                e.fiscal_year, e.period_end, e.currency, e.eps_actual,
                e.eps_estimate, e.eps_surprise_pct, e.revenue_actual,
                e.revenue_estimate, e.revenue_surprise_pct,
                e.net_income_actual, e.net_income_estimate,
                e.net_income_surprise_pct, e.provider_fields, e.source,
                e.synced_at, e.raw_data,
                before_1.close_price AS price_before,
                after_1.close_price AS price_after_1d,
                after_5.close_price AS price_after_5d,
                ROUND(100 * (after_1.close_price / NULLIF(before_1.close_price, 0) - 1), 2)
                    AS post_1d_return_pct,
                ROUND(100 * (after_5.close_price / NULLIF(before_1.close_price, 0) - 1), 2)
                    AS post_5d_return_pct
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
            WHERE e.symbol = %s
            ORDER BY e.report_date DESC
            LIMIT %s
        """
        return self._fetch(sql, (ticker.upper(), limit))

    def fundamentals(self, ticker: str) -> dict[str, Any] | None:
        rows = self._fetch(
            """
            SELECT symbol, captured_at, currency, market_cap, enterprise_value,
                   pe_ttm, pe_forward, eps_ttm, revenue_ttm, gross_margin_pct,
                   operating_margin_pct, net_margin_pct, revenue_growth_yoy_pct,
                   eps_growth_yoy_pct, source, raw_data
            FROM fundamentals_snapshots
            WHERE symbol = %s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (ticker.upper(),),
        )
        return rows[0] if rows else None

    def transcripts(self, ticker: str) -> list[dict[str, Any]]:
        del ticker
        return []

    def news(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return self._fetch(
            """
            SELECT headline, summary, source, published_at, url
            FROM news_articles
            WHERE symbol = %s
              AND published_at >= %s
            ORDER BY published_at DESC NULLS LAST
            LIMIT 20
            """,
            (ticker.upper(), cutoff),
        )

    def events(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        needle = f'%"{ticker.upper()}"%'
        return self._fetch(
            """
            SELECT event_id, canonical_title, event_type, event_time, severity, entities, coverage
            FROM trusted_events
            WHERE status = 'active'
              AND entities::text ILIKE %s
              AND (event_time IS NULL OR event_time >= %s)
            ORDER BY event_time DESC NULLS LAST
            LIMIT 20
            """,
            (needle, cutoff),
        )

    def guidance(self, ticker: str) -> list[dict[str, Any]]:
        del ticker
        return []
