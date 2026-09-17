"""Rebuild a Research Pack snapshot from existing tables and overlays."""

from __future__ import annotations

import re
from typing import Any

from .classify import classify_from_issuer, classify_template
from .extract import extract_guidance_mentions, first_present, is_operating_guidance, nested_get, net_margin, to_number, yoy_from_quarters
from .live_fetch import dedupe_earnings_prints
from .issuer import merge_identity
from .prices import index_closes, index_volumes, price_reaction_for_print
from .snapshot import source_is_fixture
from .sources import DatabasePackSource, PackSource, StorePackSource
from .templates import load_template


PACK_CONTENT_FIELDS = (
    "company_profile",
    "earnings_history",
    "guidance_history",
    "price_reaction_history",
    "industry_context",
    "competitive_context",
    "major_events",
    "official_documents",
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
    fields = row.get("provider_fields") if isinstance(row.get("provider_fields"), dict) else {}
    net_m = to_number(fields.get("net_margin_pct") or row.get("net_margin_pct")) or net_margin(revenue, earnings)
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
        "gross_margin_pct": to_number(fields.get("gross_margin_pct") or row.get("gross_margin_pct")),
        "operating_margin_pct": to_number(fields.get("operating_margin_pct") or row.get("operating_margin_pct")),
        "net_margin_pct": net_m,
        "margin_pct": net_m,
        "diluted_shares": to_number(fields.get("diluted_shares") or row.get("diluted_shares")),
        "provider_fields": fields,
        "fcf": _fcf(row, fundamentals),
        "segments": _segments(row),
        "source": row.get("source"),
        "post_1d_return_pct": to_number(row.get("post_1d_return_pct")),
        "post_3d_return_pct": to_number(row.get("post_3d_return_pct")),
        "post_5d_return_pct": to_number(row.get("post_5d_return_pct")),
        "pre_5d_return_pct": to_number(row.get("pre_5d_return_pct")),
        "day_return_pct": to_number(row.get("day_return_pct")),
        "vs_spy_1d_pct": to_number(row.get("vs_spy_1d_pct")),
        "vs_qqq_1d_pct": to_number(row.get("vs_qqq_1d_pct")),
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
        earnings_rows = source.earnings(symbol, limit=24) if source else []
        transcripts = source.transcripts(symbol) if source else []
        guidance_rows = list(source.guidance(symbol) if source else [])
        news = source.news(symbol) if source else []
        events = source.events(symbol) if source else []
        filings = list(source.filings(symbol) if source and hasattr(source, "filings") else [])
        press = list(source.press_releases(symbol) if source and hasattr(source, "press_releases") else [])
        official_documents = list(source.official_documents(symbol) if source and hasattr(source, "official_documents") else [])
        stock_rows = list(source.closes(symbol) if source and hasattr(source, "closes") else [])
        stock_px = index_closes(stock_rows)
        spy_px = index_closes(list(source.closes("SPY") if source and hasattr(source, "closes") else []))
        qqq_px = index_closes(list(source.closes("QQQ") if source and hasattr(source, "closes") else []))
        template_id = classify_from_issuer(listed) if listed else classify_template()
        template = load_template(template_id)
        benchmark_etf = str(template.get("benchmark_etf") or "SPY").upper()
        sector_px = []
        if benchmark_etf == "SPY":
            sector_px = spy_px
        elif benchmark_etf == "QQQ":
            sector_px = qqq_px
        elif source and hasattr(source, "closes"):
            sector_px = index_closes(list(source.closes(benchmark_etf)))
        volumes = index_volumes(stock_rows)

        deduped_earnings = dedupe_earnings_prints(earnings_rows)
        dated_earnings = [row for row in deduped_earnings if row.get("period_end")]
        earnings_history = [
            _earnings_item(row, fundamentals=fundamentals)
            for row in (dated_earnings or deduped_earnings)
        ]
        earnings_history.sort(
            key=lambda row: str(row.get("period_end") or row.get("report_date") or ""),
            reverse=True,
        )
        earnings_history.sort(key=lambda row: 0 if row.get("period_end") else 1)
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
                            "source_type": "transcript",
                            "excerpt": text,
                        }
                    )

        if official_documents:
            for item in official_documents:
                text = str(item.get("text") or item.get("body") or "")
                if not text:
                    continue
                source_type = str(item.get("source_type") or item.get("doc_type") or "official_document")
                stamp = item.get("published_at") or item.get("source_time")
                for hit in extract_guidance_mentions(text)[:8]:
                    guidance_rows.append(
                        {
                            "text": hit["quote"],
                            "quote": hit["quote"],
                            "excerpt": hit["quote"],
                            "source": item.get("source") or item.get("source_provider") or "official",
                            "source_time": stamp,
                            "published_at": stamp,
                            "url": item.get("url"),
                            "source_url": item.get("url"),
                            "source_type": source_type,
                            "move": hit.get("move"),
                        }
                    )

        unique_guidance: list[dict[str, Any]] = []
        seen_guidance: set[str] = set()
        for row in guidance_rows:
            text = str(row.get("text") or row.get("quote") or row.get("excerpt") or "")
            source_type = str(row.get("source_type") or row.get("doc_type") or row.get("source") or "")
            if not is_operating_guidance(text, source_type=source_type):
                continue
            key = re.sub(r"\s+", " ", text).strip().lower()[:200]
            if not key or key in seen_guidance:
                continue
            seen_guidance.add(key)
            unique_guidance.append(row)
        unique_guidance.sort(
            key=lambda row: str(row.get("source_time") or row.get("published_at") or ""),
            reverse=True,
        )
        unique_guidance.sort(
            key=lambda row: 0
            if any(
                item in str(row.get("source_type") or row.get("doc_type") or row.get("source") or "").lower()
                for item in ("earnings_release", "exhibit", "transcript", "investor_presentation", "8-k", "8k")
            )
            else 1
        )
        guidance_rows = unique_guidance

        price_reaction = []
        for row in earnings_history:
            computed = price_reaction_for_print(
                row.get("report_date"),
                row.get("report_timing"),
                stock_px,
                spy_px,
                qqq_px,
                sector_px,
                volumes,
            ) if stock_px else {}
            for key, value in computed.items():
                if value is not None:
                    row[key] = value
            item = {
                "report_date": row["report_date"],
                "fiscal_period": row["fiscal_period"],
                "pre_5d_return_pct": row.get("pre_5d_return_pct"),
                "day_return_pct": row.get("day_return_pct"),
                "post_1d_return_pct": row.get("post_1d_return_pct"),
                "post_3d_return_pct": row.get("post_3d_return_pct"),
                "post_5d_return_pct": row.get("post_5d_return_pct"),
                "vs_spy_1d_pct": row.get("vs_spy_1d_pct"),
                "vs_qqq_1d_pct": row.get("vs_qqq_1d_pct"),
                "vs_spy_5d_pct": row.get("vs_spy_5d_pct"),
                "vs_qqq_5d_pct": row.get("vs_qqq_5d_pct"),
                "vs_sector_1d_pct": row.get("vs_sector_1d_pct"),
                "vs_sector_5d_pct": row.get("vs_sector_5d_pct"),
                "volume_vs_20d_avg": row.get("volume_vs_20d_avg"),
                "pre_20d_realized_vol": row.get("pre_20d_realized_vol"),
                "benchmark_etf": benchmark_etf,
                "ref": row.get("ref"),
            }
            if any(item.get(key) is not None for key in ("post_1d_return_pct", "post_5d_return_pct", "day_return_pct", "pre_5d_return_pct")):
                price_reaction.append(item)
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
        for row in press:
            major_events.append(
                {
                    "title": row.get("title") or "Press release",
                    "summary": row.get("excerpt") or row.get("body"),
                    "event_time": _iso(row.get("published_at")),
                    "source": row.get("source_provider") or "press_release",
                    "url": row.get("url"),
                    "ref": {"url": row.get("url"), "doc_type": "press_release"},
                }
            )
        for row in filings:
            form = str((row.get("metadata") or {}).get("form") or row.get("title") or "filing")
            major_events.append(
                {
                    "title": form,
                    "event_type": "sec_filing",
                    "event_time": _iso(row.get("published_at") or (row.get("metadata") or {}).get("filing_date")),
                    "source": row.get("source_provider") or "sec",
                    "url": row.get("url"),
                    "ref": {"url": row.get("url"), "form": form},
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

        fund = fundamentals or {}
        fund_raw = fund.get("raw_data") if isinstance(fund.get("raw_data"), dict) else {}
        profile = {
            "legal_name": listed.get("legal_name") or symbol,
            "cik": listed.get("cik"),
            "fiscal_year_end_month": listed.get("fiscal_year_end_month"),
            "sector": listed.get("sector"),
            "asset_class": listed.get("asset_class") or "stocks",
            "primary_exchange": listed.get("primary_exchange") or "",
            "revenue_ttm": to_number(fund.get("revenue_ttm")),
            "eps_ttm": to_number(fund.get("eps_ttm")),
            "gross_margin_pct": to_number(fund.get("gross_margin_pct")),
            "operating_margin_pct": to_number(fund.get("operating_margin_pct")),
            "net_margin_pct": to_number(fund.get("net_margin_pct")),
            "revenue_growth_yoy_pct": to_number(fund.get("revenue_growth_yoy_pct"))
            or yoy_from_quarters(earnings_history, "revenue"),
            "eps_growth_yoy_pct": to_number(fund.get("eps_growth_yoy_pct"))
            or yoy_from_quarters(earnings_history, "eps"),
            "fcf": _fcf({}, fundamentals),
            "market_cap": to_number(fund.get("market_cap") or fund_raw.get("market_cap")),
            "pe_forward": to_number(fund.get("pe_forward") or fund_raw.get("pe_forward")),
            "pe_ttm": to_number(fund.get("pe_ttm")),
            "net_income_ttm": to_number(fund.get("net_income_ttm") or fund_raw.get("net_income_ttm")),
            "diluted_shares": to_number(
                fund.get("diluted_shares")
                or fund_raw.get("diluted_shares")
                or fund.get("diluted_weighted_average_shares")
            ),
            "diluted_shares_origin": fund.get("diluted_shares_origin") or fund_raw.get("diluted_shares_origin"),
            "diluted_shares_period": fund.get("diluted_shares_period") or fund_raw.get("diluted_shares_period"),
            "diluted_shares_source": fund.get("diluted_shares_source") or fund_raw.get("diluted_shares_source") or fund.get("source"),
            "diluted_shares_source_url": fund.get("diluted_shares_source_url") or fund_raw.get("diluted_shares_source_url"),
            "transcripts": transcripts,
            "official_documents": official_documents,
        }
        last_close = stock_px[-1][1] if stock_px else None
        profile["last_close"] = last_close
        eps_ttm = to_number(profile.get("eps_ttm"))
        if profile.get("pe_ttm") is None and last_close not in (None, 0) and eps_ttm not in (None, 0):
            profile["pe_ttm"] = round(float(last_close) / float(eps_ttm), 2)
        if profile.get("diluted_shares") in (None, 0):
            for row in earnings_history:
                if to_number(row.get("diluted_shares")) not in (None, 0):
                    profile["diluted_shares"] = to_number(row.get("diluted_shares"))
                    profile["diluted_shares_origin"] = profile.get("diluted_shares_origin") or "earnings_release"
                    profile["diluted_shares_period"] = str(row.get("fiscal_period") or row.get("period_end") or "")
                    profile["diluted_shares_source"] = str(row.get("source") or "earnings_print")
                    break
        profile["recent_closes"] = [{"session_date": day.isoformat(), "close": price} for day, price in stock_px[-40:]]
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
        if profile.get("net_margin_pct") is None and all(
            row.get("net_margin_pct") is None and row.get("margin_pct") is None for row in earnings_history
        ):
            missing.append("net_margin")
        if profile.get("diluted_shares") in (None, 0) and all(row.get("diluted_shares") in (None, 0) for row in earnings_history):
            missing.append("diluted_shares")
        if not price_reaction:
            missing.append("price_reaction_history")
        if not major_events:
            missing.append("major_events")
        if fundamentals is None:
            missing.append("fundamentals_snapshot")

        is_fixture = source_is_fixture(source, fundamentals=fundamentals) or bool(
            (fundamentals or {}).get("is_fixture")
        )
        refs = {
            "issuer_profiles": symbol,
            "earnings_reports": [row.get("ref") for row in earnings_history],
            "fundamentals_snapshots": _iso((fundamentals or {}).get("captured_at")) if fundamentals else None,
            "daily_price_bars": "joined on earnings report_date" if price_reaction else None,
            "news_articles": [row.get("url") for row in news if row.get("url")],
            "trusted_events": [row.get("event_id") for row in events if row.get("event_id")],
            "transcripts": [item.get("source") or item.get("source_url") for item in transcripts],
            "research_source_documents": {
                "transcripts": len(transcripts),
                "filings": len(filings),
                "press_releases": len(press),
                "guidance": len(guidance_rows),
                "official_documents": len(official_documents),
            },
        }
        return {
            "ticker": symbol,
            "template_id": template_id,
            "benchmark_etf": benchmark_etf,
            "company_profile": profile,
            "earnings_history": earnings_history,
            "guidance_history": guidance_rows,
            "price_reaction_history": price_reaction,
            "industry_context": {},
            "competitive_context": {},
            "major_events": major_events[:20],
            "official_documents": official_documents[:24],
            "missing_fields": missing,
            "source_refs": refs,
            "workflow_run_id": workflow_run_id,
            "is_fixture": is_fixture,
            "source": "fixture" if is_fixture else "production",
        }


def default_pack_source(store: Any) -> PackSource | None:
    attached = getattr(store, "pack_source", None)
    if attached is not None:
        return attached
    database = getattr(store, "database", None)
    if database is not None:
        return DatabasePackSource(database)
    if hasattr(store, "list_source_documents") or hasattr(store, "raw_earnings"):
        return StorePackSource(store)
    return None
