"""Rebuild a Research Pack snapshot from existing tables and overlays."""

from __future__ import annotations

from typing import Any

from .classify import classify_from_issuer, classify_template
from .extract import first_present, nested_get, net_margin, to_number, yoy_from_quarters
from .issuer import merge_identity
from .sources import DatabasePackSource, PackSource


PACK_CONTENT_FIELDS = (
    "company_profile",
    "earnings_history",
    "guidance_history",
    "price_reaction_history",
    "industry_context",
    "competitive_context",
    "major_events",
)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _source_key(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol") or row.get("ticker"),
        "report_date": _iso(row.get("report_date")),
        "fiscal_period": row.get("fiscal_period"),
        "source": row.get("source"),
    }


def _fcf(row: dict[str, Any], fundamentals: dict[str, Any] | None) -> float | None:
    raw = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
    fields = row.get("provider_fields") if isinstance(row.get("provider_fields"), dict) else {}
    fund_raw = (fundamentals or {}).get("raw_data") if isinstance((fundamentals or {}).get("raw_data"), dict) else {}
    return to_number(
        first_present(
            {**fields, **raw, **(fundamentals or {}), **fund_raw},
            ("fcf", "free_cash_flow", "freeCashFlow", "freeCashFlowTTM"),
        )
        or nested_get(fund_raw, "metrics", "freeCashFlowTTM")
        or nested_get(raw, "cash_flow", "freeCashFlow")
    )


def _segments(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
    fields = row.get("provider_fields") if isinstance(row.get("provider_fields"), dict) else {}
    payload = fields.get("segments") or raw.get("segments") or []
    if not isinstance(payload, list):
        return []
    out = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("segment") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "revenue": to_number(item.get("revenue") or item.get("sales")),
                "growth_yoy_pct": to_number(item.get("growth_yoy_pct") or item.get("yoy")),
            }
        )
    return out


def _earnings_item(row: dict[str, Any], *, fundamentals: dict[str, Any] | None) -> dict[str, Any]:
    revenue = to_number(row.get("revenue_actual") or row.get("revenue"))
    earnings = to_number(row.get("net_income_actual") or row.get("earnings") or row.get("net_income"))
    eps = to_number(row.get("eps_actual") or row.get("eps"))
    item = {
        "fiscal_period": row.get("fiscal_period"),
        "fiscal_year": row.get("fiscal_year"),
        "report_date": _iso(row.get("report_date")),
        "period_end": _iso(row.get("period_end")),
        "report_timing": row.get("report_timing"),
        "currency": row.get("currency") or "USD",
        "revenue": revenue,
        "revenue_estimate": to_number(row.get("revenue_estimate")),
        "revenue_surprise_pct": to_number(row.get("revenue_surprise_pct")),
        "eps": eps,
        "eps_estimate": to_number(row.get("eps_estimate")),
        "eps_surprise_pct": to_number(row.get("eps_surprise_pct")),
        "earnings": earnings,
        "margin_pct": to_number(row.get("margin_pct")) or net_margin(revenue, earnings),
        "fcf": _fcf(row, fundamentals),
        "segments": _segments(row),
        "source": row.get("source"),
        "post_1d_return_pct": to_number(row.get("post_1d_return_pct")),
        "post_5d_return_pct": to_number(row.get("post_5d_return_pct")),
        "transcript_excerpts": list(row.get("transcript_excerpts") or []),
        "transcript_text": row.get("transcript_text") or "",
        "ref": _source_key(row),
    }
    return item


class PackBuilder:
    def __init__(self, source: PackSource | None = None) -> None:
        self.source = source

    def build(
        self,
        ticker: str,
        *,
        issuer: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        symbol = str(ticker or "").upper()
        source = self.source
        listed = (source.issuer(symbol) if source else None) or issuer or merge_identity(symbol)
        fundamentals = source.fundamentals(symbol) if source else None
        earnings_rows = source.earnings(symbol, limit=6) if source else []
        transcripts = source.transcripts(symbol) if source else []
        guidance_rows = list(source.guidance(symbol) if source else [])
        news = source.news(symbol) if source else []
        events = source.events(symbol) if source else []

        earnings_history = [_earnings_item(row, fundamentals=fundamentals) for row in earnings_rows]
        if transcripts and earnings_history:
            by_quarter = {str(item.get("quarter") or item.get("fiscal_period") or ""): item for item in transcripts}
            for row in earnings_history:
                attached = by_quarter.get(str(row.get("fiscal_period") or ""))
                if attached:
                    row["transcript_excerpts"] = list(attached.get("excerpts") or row.get("transcript_excerpts") or [])
                    row["transcript_text"] = attached.get("text") or row.get("transcript_text") or ""
        for item in transcripts:
            if item.get("guidance"):
                guidance_rows.extend(item.get("guidance") or [])
            for excerpt in item.get("excerpts") or []:
                text = excerpt.get("text") if isinstance(excerpt, dict) else str(excerpt)
                if "guidance" in str(text).lower():
                    guidance_rows.append(
                        {
                            "text": text,
                            "source": item.get("source") or "transcript",
                            "source_time": item.get("source_time") or item.get("published_at"),
                            "fiscal_period": item.get("quarter") or item.get("fiscal_period"),
                        }
                    )

        price_reaction = [
            {
                "report_date": row["report_date"],
                "fiscal_period": row["fiscal_period"],
                "post_1d_return_pct": row.get("post_1d_return_pct"),
                "post_5d_return_pct": row.get("post_5d_return_pct"),
                "ref": row.get("ref"),
            }
            for row in earnings_history
            if row.get("post_1d_return_pct") is not None or row.get("post_5d_return_pct") is not None
        ]
        major_events = []
        for row in events:
            major_events.append(
                {
                    "title": row.get("canonical_title") or row.get("title"),
                    "event_type": row.get("event_type"),
                    "event_time": _iso(row.get("event_time")),
                    "severity": row.get("severity"),
                    "source": "trusted_events",
                    "ref": {"event_id": row.get("event_id")},
                }
            )
        for row in news:
            major_events.append(
                {
                    "title": row.get("headline") or row.get("title"),
                    "summary": row.get("summary"),
                    "event_time": _iso(row.get("published_at")),
                    "source": row.get("source") or "news_articles",
                    "url": row.get("url"),
                    "ref": {"url": row.get("url")},
                }
            )

        profile = {
            "legal_name": listed.get("legal_name") or symbol,
            "cik": listed.get("cik"),
            "fiscal_year_end_month": listed.get("fiscal_year_end_month"),
            "sector": listed.get("sector"),
            "asset_class": listed.get("asset_class") or "stocks",
            "primary_exchange": listed.get("primary_exchange") or "",
            "revenue_ttm": to_number((fundamentals or {}).get("revenue_ttm")),
            "eps_ttm": to_number((fundamentals or {}).get("eps_ttm")),
            "gross_margin_pct": to_number((fundamentals or {}).get("gross_margin_pct")),
            "operating_margin_pct": to_number((fundamentals or {}).get("operating_margin_pct")),
            "net_margin_pct": to_number((fundamentals or {}).get("net_margin_pct")),
            "revenue_growth_yoy_pct": to_number((fundamentals or {}).get("revenue_growth_yoy_pct"))
            or yoy_from_quarters(earnings_history, "revenue"),
            "eps_growth_yoy_pct": to_number((fundamentals or {}).get("eps_growth_yoy_pct"))
            or yoy_from_quarters(earnings_history, "eps"),
            "fcf": _fcf({}, fundamentals),
            "transcripts": transcripts,
        }
        template_id = classify_from_issuer(listed) if listed else classify_template()
        missing: list[str] = []
        if not listed.get("cik"):
            missing.append("issuer.cik")
        if listed.get("fiscal_year_end_month") in (None, ""):
            missing.append("issuer.fiscal_year_end_month")
        if not earnings_history:
            missing.append("earnings_history")
        elif len(earnings_history) < 4:
            missing.append("earnings_history_depth")
        if not guidance_rows:
            missing.append("guidance_history")
        if not transcripts and not any(row.get("transcript_text") or row.get("transcript_excerpts") for row in earnings_history):
            missing.append("transcripts")
        if profile.get("fcf") is None and all(row.get("fcf") is None for row in earnings_history):
            missing.append("fcf")
        if all(not row.get("segments") for row in earnings_history):
            missing.append("segment_growth")
        if not price_reaction:
            missing.append("price_reaction_history")
        if not major_events:
            missing.append("major_events")
        if fundamentals is None:
            missing.append("fundamentals_snapshot")

        refs = {
            "issuer_profiles": symbol,
            "earnings_reports": [row.get("ref") for row in earnings_history],
            "fundamentals_snapshots": _iso((fundamentals or {}).get("captured_at")) if fundamentals else None,
            "daily_price_bars": "joined on earnings report_date" if price_reaction else None,
            "news_articles": [row.get("url") for row in news if row.get("url")],
            "trusted_events": [row.get("event_id") for row in events if row.get("event_id")],
            "transcripts": [item.get("source") or item.get("source_url") for item in transcripts],
        }
        return {
            "ticker": symbol,
            "template_id": template_id,
            "company_profile": profile,
            "earnings_history": earnings_history,
            "guidance_history": guidance_rows,
            "price_reaction_history": price_reaction,
            "industry_context": {},
            "competitive_context": {},
            "major_events": major_events[:20],
            "missing_fields": missing,
            "source_refs": refs,
            "workflow_run_id": workflow_run_id,
        }


def default_pack_source(store: Any) -> PackSource | None:
    attached = getattr(store, "pack_source", None)
    if attached is not None:
        return attached
    database = getattr(store, "database", None)
    if database is not None:
        return DatabasePackSource(database)
    return None
