"""Read-only sources for rebuilding a Research Pack. Do not copy raw tables."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class PackSource(Protocol):
    def issuer(self, ticker: str) -> dict[str, Any] | None: ...
    def earnings(self, ticker: str, *, limit: int = 12) -> list[dict[str, Any]]: ...
    def fundamentals(self, ticker: str) -> dict[str, Any] | None: ...
    def transcripts(self, ticker: str) -> list[dict[str, Any]]: ...
    def news(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]: ...
    def events(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]: ...
    def guidance(self, ticker: str) -> list[dict[str, Any]]: ...
    def filings(self, ticker: str) -> list[dict[str, Any]]: ...
    def press_releases(self, ticker: str) -> list[dict[str, Any]]: ...
    def official_documents(self, ticker: str) -> list[dict[str, Any]]: ...
    def closes(self, ticker: str) -> list[dict[str, Any]]: ...


class DictPackSource:
    """Fixture or test overlay. Production workflow uses DatabasePackSource."""

    is_fixture = True

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

    def earnings(self, ticker: str, *, limit: int = 12) -> list[dict[str, Any]]:
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

    def filings(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._row(ticker).get("filings") or [])]

    def press_releases(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._row(ticker).get("press_releases") or [])]

    def official_documents(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._row(ticker).get("official_documents") or [])]

    def closes(self, ticker: str) -> list[dict[str, Any]]:
        key = str(ticker or "").upper()
        own = self._row(key)
        if own.get("closes"):
            return [dict(item) for item in own["closes"]]
        for row in self.payload.values():
            benches = row.get("benchmarks") or {}
            if not isinstance(benches, dict):
                continue
            for name, bars in benches.items():
                if str(name).upper() == key:
                    return [dict(item) for item in (bars or [])]
        return []


def documents_to_transcripts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        excerpts = metadata.get("excerpts") or []
        if not excerpts and row.get("excerpt"):
            excerpts = [{"text": row.get("excerpt")}]
        out.append(
            {
                "quarter": row.get("fiscal_period") or metadata.get("quarter"),
                "fiscal_period": row.get("fiscal_period") or metadata.get("quarter"),
                "published_at": row.get("published_at"),
                "source_time": row.get("published_at"),
                "source": row.get("source_provider") or "transcript",
                "source_url": row.get("url"),
                "title": row.get("title"),
                "text": row.get("body") or row.get("excerpt") or "",
                "excerpts": excerpts,
            }
        )
    return out


def documents_to_guidance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        text = str(row.get("body") or row.get("excerpt") or row.get("title") or "").strip()
        if not text:
            continue
        out.append(
            {
                "text": text,
                "quote": text,
                "source": row.get("source_provider") or "guidance",
                "source_time": row.get("published_at"),
                "published_at": row.get("published_at"),
                "fiscal_period": row.get("fiscal_period"),
                "url": row.get("url"),
                "source_url": row.get("url"),
                "source_type": metadata.get("source_type") or "earnings_release",
                "move": metadata.get("move"),
                "excerpt": row.get("excerpt") or text,
            }
        )
    return out


OFFICIAL_DOC_TYPES = (
    "filing",
    "press_release",
    "earnings_release",
    "exhibit",
    "investor_presentation",
    "prepared_remarks",
)


def documents_to_official(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("body") or row.get("text") or row.get("excerpt") or "").strip()
        if len(text) < 80:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        out.append(
            {
                "title": row.get("title") or row.get("form") or row.get("doc_type"),
                "url": row.get("url"),
                "published_at": row.get("published_at"),
                "source": row.get("source_provider") or "official",
                "source_provider": row.get("source_provider"),
                "doc_type": row.get("doc_type") or metadata.get("kind") or "filing",
                "source_type": metadata.get("source_type") or row.get("doc_type") or "official_document",
                "text": text,
                "excerpt": str(row.get("excerpt") or text[:1200]),
                "form": metadata.get("form"),
            }
        )
    return out


class DatabasePackSource:
    is_fixture = False

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

    def earnings(self, ticker: str, *, limit: int = 12) -> list[dict[str, Any]]:
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
            ORDER BY (e.period_end IS NULL), COALESCE(e.period_end, e.report_date) DESC,
                     CASE WHEN COALESCE(e.source, '') LIKE '%%companyfacts%%' THEN 0 ELSE 1 END
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
        return documents_to_transcripts(self._documents(ticker, "transcript"))

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
        return documents_to_guidance(self._documents(ticker, "guidance"))

    def filings(self, ticker: str) -> list[dict[str, Any]]:
        return self._documents(ticker, "filing")

    def press_releases(self, ticker: str) -> list[dict[str, Any]]:
        return self._documents(ticker, "press_release")

    def official_documents(self, ticker: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc_type in OFFICIAL_DOC_TYPES:
            rows.extend(self._documents(ticker, doc_type))
        return documents_to_official(rows)

    def closes(self, ticker: str) -> list[dict[str, Any]]:
        return self._fetch(
            """
            SELECT DISTINCT ON (bar_time::date)
                   bar_time::date AS session_date,
                   close_price,
                   volume
            FROM daily_price_bars
            WHERE symbol = %s
            ORDER BY bar_time::date, bar_time DESC
            """,
            (ticker.upper(),),
        )

    def _documents(self, ticker: str, doc_type: str) -> list[dict[str, Any]]:
        return self._fetch(
            """
            SELECT ticker, doc_type, fiscal_period, published_at, title, url,
                   excerpt, body, source_provider, metadata
            FROM research_source_documents
            WHERE ticker = %s AND doc_type = %s
            ORDER BY published_at DESC NULLS LAST, captured_at DESC
            LIMIT 24
            """,
            (ticker.upper(), doc_type),
        )


class StorePackSource:
    """Read backfill overlays and source documents from an in-memory research store."""

    is_fixture = False

    def __init__(self, store: Any) -> None:
        self.store = store

    def issuer(self, ticker: str) -> dict[str, Any] | None:
        getter = getattr(self.store, "get_issuer", None)
        return getter(ticker) if callable(getter) else None

    def earnings(self, ticker: str, *, limit: int = 12) -> list[dict[str, Any]]:
        rows = list(getattr(self.store, "raw_earnings", {}).get(ticker.upper()) or [])
        return [dict(item) for item in rows[:limit]]

    def fundamentals(self, ticker: str) -> dict[str, Any] | None:
        row = getattr(self.store, "raw_fundamentals", {}).get(ticker.upper())
        return dict(row) if isinstance(row, dict) else None

    def transcripts(self, ticker: str) -> list[dict[str, Any]]:
        lister = getattr(self.store, "list_source_documents", None)
        rows = lister(ticker, "transcript") if callable(lister) else []
        return documents_to_transcripts(rows)

    def news(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        del days
        return [dict(item) for item in (getattr(self.store, "raw_news", {}).get(ticker.upper()) or [])]

    def events(self, ticker: str, *, days: int = 365) -> list[dict[str, Any]]:
        del days
        return [dict(item) for item in (getattr(self.store, "raw_events", {}).get(ticker.upper()) or [])]

    def guidance(self, ticker: str) -> list[dict[str, Any]]:
        lister = getattr(self.store, "list_source_documents", None)
        rows = lister(ticker, "guidance") if callable(lister) else []
        return documents_to_guidance(rows)

    def filings(self, ticker: str) -> list[dict[str, Any]]:
        lister = getattr(self.store, "list_source_documents", None)
        return list(lister(ticker, "filing") if callable(lister) else [])

    def press_releases(self, ticker: str) -> list[dict[str, Any]]:
        lister = getattr(self.store, "list_source_documents", None)
        return list(lister(ticker, "press_release") if callable(lister) else [])

    def official_documents(self, ticker: str) -> list[dict[str, Any]]:
        lister = getattr(self.store, "list_source_documents", None)
        if not callable(lister):
            return []
        rows: list[dict[str, Any]] = []
        for doc_type in OFFICIAL_DOC_TYPES:
            rows.extend(lister(ticker, doc_type) or [])
        return documents_to_official(rows)

    def closes(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(item) for item in (getattr(self.store, "raw_bars", {}).get(ticker.upper()) or [])]
