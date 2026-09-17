"""Budgeted external intelligence. Discovery providers are not publishers."""

from __future__ import annotations

from typing import Any

from stock_pm.config import Settings
from stock_pm.research.extract import to_number
from stock_pm.research.llm_reason import compact_text

from .clients import (
    SearchBudget,
    alphavantage_news,
    alphavantage_overview,
    duckduckgo_search,
    exa_configured,
    exa_search,
    fill_missing_bodies,
    fred_macro_documents,
    recover_dates_from_pages,
    tavily_configured,
    tavily_search,
    within_days,
)
from .dedupe import dedupe_documents
from .extract import deterministic_facts, facts_to_evidence_bodies, llm_extract_facts
from .quality import host_of, source_family, source_tier
from .queries import allocate_queries, generate_search_plan
from .select import compress_reasoning_context, docs_for_extraction, select_reasoning_documents
from .types import EXA_SEARCH_BUDGET, NEWS_WINDOW_DAYS, PROVIDER_ROLES, TAVILY_SEARCH_BUDGET, empty_provider_status


BASE_QUERY_TYPES = {"company_official", "company_earnings", "company_news", "industry_news"}
CLAIM_QUERY_TYPES = {"claim", "related_entity", "customer", "supplier"}


def _settings(settings: Settings | None) -> Settings:
    return settings or Settings()


def official_documents_from_pack(pack: dict[str, Any] | None, ticker: str) -> list[dict[str, Any]]:
    from .clients import _document, parse_published

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in (pack or {}).get("official_documents") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("source_url") or "")
        title = str(row.get("title") or row.get("form") or row.get("doc_type") or "official document")
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        text = str(row.get("text") or row.get("body") or row.get("excerpt") or "")
        published = parse_published(row.get("published_at") or row.get("source_time") or row.get("filing_date"))
        rows.append(
            _document(
                provider=str(row.get("source_provider") or row.get("source") or "sec"),
                url=url or "https://www.sec.gov/",
                title=title,
                ticker=ticker,
                query="pack.official_documents",
                query_type="company_official",
                published_at=published,
                raw_text=text,
                clean_text=text,
                extra={"from_pack": True, "form": row.get("form") or row.get("doc_type")},
            )
        )
    return rows


def documents_to_news_hits(docs: list[dict[str, Any]], *, days: int) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for doc in docs:
        if str(doc.get("source_type") or "") == "macro":
            continue
        published = doc.get("published_at")
        if not within_days(published, days):
            continue
        body = str(doc.get("clean_text") or "") if doc.get("is_full_text") else ""
        hits.append(
            {
                "title": doc.get("title"),
                "url": doc.get("url"),
                "snippet": body[:400],
                "source": doc.get("source_family") or source_family(doc.get("url")),
                "published_at": published,
                "query": doc.get("query"),
                "provider": doc.get("provider"),
                "source_tier": doc.get("source_tier"),
                "source_type": doc.get("source_type"),
                "query_type": doc.get("query_type"),
                "is_full_text": bool(doc.get("is_full_text")),
                "is_dated": bool(doc.get("is_dated")),
            }
        )
    return hits


def _search_one(
    provider: str,
    query: str,
    *,
    settings: Settings,
    ticker: str,
    query_type: str,
    days: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if provider == "tavily":
        return tavily_search(query, settings=settings, ticker=ticker, query_type=query_type, days=days)
    if provider == "exa":
        return exa_search(query, settings=settings, ticker=ticker, query_type=query_type, days=days)
    return duckduckgo_search(query, ticker=ticker, query_type=query_type, days=days)


def _rollup(audits: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for audit in audits:
        provider = str(audit.get("provider") or "unknown")
        rec = out.get(provider) or empty_provider_status(provider, status=str(audit.get("status") or "ok"))
        rec["queries"].append(
            {
                "query": audit.get("query"),
                "query_type": audit.get("query_type"),
                "hit_count": audit.get("hit_count") or 0,
                "usable_count": audit.get("usable_count") or 0,
                "high_quality_count": audit.get("high_quality_count") or 0,
                "status": audit.get("status"),
                "error": audit.get("error"),
                "latency_ms": audit.get("latency_ms"),
            }
        )
        rec["hit_count"] = int(rec.get("hit_count") or 0) + int(audit.get("hit_count") or 0)
        rec["usable_count"] = int(rec.get("usable_count") or 0) + int(audit.get("usable_count") or 0)
        rec["high_quality_count"] = int(rec.get("high_quality_count") or 0) + int(audit.get("high_quality_count") or 0)
        rec["full_text_count"] = int(rec.get("full_text_count") or 0) + int(audit.get("full_text_count") or 0)
        rec["dated_count"] = int(rec.get("dated_count") or 0) + int(audit.get("dated_count") or 0)
        if audit.get("error") and not rec.get("error"):
            rec["error"] = audit.get("error")
        status = str(audit.get("status") or "")
        current = str(rec.get("status") or "ok")
        if status == "not_configured":
            rec["status"] = "not_configured"
            rec["error"] = audit.get("error") or rec.get("error")
        elif status == "failed":
            rec["status"] = "partial" if current in {"ok", "partial"} and rec.get("hit_count") else "failed"
            rec["error"] = audit.get("error") or rec.get("error")
        elif status == "partial" and current in {"ok", "partial"}:
            rec["status"] = "partial"
            rec["error"] = audit.get("error") or rec.get("error")
        elif current not in {"failed", "not_configured", "partial"}:
            rec["status"] = status or current
        out[provider] = rec
    return out


def _provider_stats(docs: list[dict[str, Any]], provider: str) -> dict[str, Any]:
    rows = [row for row in docs if row.get("provider") == provider]
    lengths = [len(str(row.get("clean_text") or "")) for row in rows if row.get("is_full_text")]
    return {
        "hit_count": len(rows),
        "dated_recent": sum(1 for row in rows if row.get("is_dated") and within_days(row.get("published_at"), NEWS_WINDOW_DAYS)),
        "full_text": sum(1 for row in rows if row.get("is_full_text")),
        "tier1_2": sum(1 for row in rows if int(row.get("source_tier") or 9) <= 2),
        "news": sum(1 for row in rows if row.get("query_type") in {"company_news", "industry_news"} or row.get("source_type") == "independent_news"),
        "industry": sum(1 for row in rows if row.get("query_type") in {"industry_news", "related_entity"} or row.get("source_type") == "industry"),
        "customer_supplier": sum(1 for row in rows if row.get("query_type") in {"customer", "supplier", "related_entity"}),
        "unique_domains": sorted({host_of(row.get("url")) for row in rows if host_of(row.get("url"))})[:20],
        "avg_full_text_chars": int(sum(lengths) / len(lengths)) if lengths else 0,
    }


def _winner(tavily: dict[str, Any], exa: dict[str, Any], field: str) -> str:
    left = int(tavily.get(field) or 0)
    right = int(exa.get(field) or 0)
    if left == 0 and right == 0:
        return "none"
    if left > right:
        return "tavily"
    if right > left:
        return "exa"
    return "tie"


def compare_tavily_exa(docs: list[dict[str, Any]], *, tavily_status: str, exa_status: str) -> dict[str, Any]:
    tavily = _provider_stats(docs, "tavily")
    exa = _provider_stats(docs, "exa")
    return {
        "tavily_status": tavily_status,
        "exa_status": exa_status,
        "tavily": tavily,
        "exa": exa,
        "better_for_news": _winner(tavily, exa, "news"),
        "better_for_industry": _winner(tavily, exa, "industry"),
        "better_for_customer_supplier": _winner(tavily, exa, "customer_supplier"),
        "better_for_full_text": _winner(tavily, exa, "full_text")
        if int(tavily.get("avg_full_text_chars") or 0) == int(exa.get("avg_full_text_chars") or 0)
        else ("tavily" if int(tavily.get("avg_full_text_chars") or 0) > int(exa.get("avg_full_text_chars") or 0) else "exa"),
        "note": "Exa is primary discovery; Tavily is topic=news supplement plus extract. They are not interchangeable. Publisher quality is taken from the original URL.",
        "roles": {"exa": PROVIDER_ROLES["exa"], "tavily": PROVIDER_ROLES["tavily"]},
    }


def cross_check_alphavantage(overview: dict[str, Any] | None, pack: dict[str, Any] | None) -> list[dict[str, str]]:
    if not overview:
        return []
    profile = (pack or {}).get("company_profile") or {}
    warnings: list[dict[str, str]] = []
    pairs = (
        ("RevenueTTM", profile.get("revenue_ttm"), "revenue_ttm", 0.03),
        ("EPS", profile.get("eps_ttm"), "eps_ttm", 0.10),
    )
    for av_key, pack_value, name, tolerance in pairs:
        av_value = to_number(overview.get(av_key))
        primary = to_number(pack_value)
        if av_value is None or primary is None or primary == 0:
            continue
        gap = abs(av_value - primary) / abs(primary)
        if gap > tolerance:
            warnings.append(
                {
                    "code": "INTEGRITY WARNING",
                    "axis": "Data Coverage",
                    "reason": (
                        f"Alpha Vantage {av_key}={av_value} disagrees with SEC/pack {name}={primary} "
                        f"by {round(100.0 * gap, 1)}%. SEC kept; AV is cross-check only."
                    ),
                }
            )
    return warnings


def build_report(
    docs: list[dict[str, Any]],
    *,
    days: int,
    duplicates_removed: int,
    raw_count: int,
    plan: dict[str, Any],
    allocated: list[dict[str, Any]],
    query_results: list[dict[str, Any]],
    providers: dict[str, Any],
    warnings: list[dict[str, str]],
    overview: dict[str, Any] | None,
    evidence_count: int,
    quality_stats: dict[str, Any] | None = None,
    reasoning_context: dict[str, Any] | None = None,
    date_recovered_count: int = 0,
) -> dict[str, Any]:
    recent = [row for row in docs if within_days(row.get("published_at"), days)]
    background = [row for row in docs if not within_days(row.get("published_at"), days)]
    def _count(predicate) -> int:
        return sum(1 for row in docs if predicate(row))

    gaps: list[str] = list(plan.get("coverage_gaps") or [])
    types = [str(item) for item in (plan.get("important_relationship_types") or []) if str(item).strip()]
    if types and not any(row.get("query_type") in CLAIM_QUERY_TYPES or row.get("relationship_type") for row in docs):
        gaps.append("No relationship/claim documents were retrieved for the business-model types.")
    if not any(int(row.get("source_tier") or 9) == 2 and within_days(row.get("published_at"), days) for row in docs):
        gaps.append("No Tier-2 dated independent news (Reuters/Bloomberg/FT/WSJ/CNBC) in the 30-day window.")
    if not any(row.get("is_full_text") and within_days(row.get("published_at"), days) for row in docs):
        gaps.append("No dated full-text news bodies in the 30-day window.")

    tavily_status = str((providers.get("tavily") or {}).get("status") or "not_run")
    exa_status = str((providers.get("exa") or {}).get("status") or "not_run")
    claim_rows = [row for row in allocated if row.get("query_type") in CLAIM_QUERY_TYPES]
    if not claim_rows:
        claim_rows = [row for row in query_results if row.get("query_type") in CLAIM_QUERY_TYPES]
    return {
        "official_documents": _count(lambda row: row.get("source_type") == "official" or int(row.get("source_tier") or 9) == 1),
        "independent_news": _count(lambda row: row.get("source_type") == "independent_news" or int(row.get("source_tier") or 9) == 2),
        "industry_sources": _count(
            lambda row: row.get("source_type") == "industry" or row.get("query_type") in {"industry_news", "related_entity"}
        ),
        "customer_sources": _count(
            lambda row: row.get("query_type") == "customer" or str((row.get("metadata") or {}).get("relation") or "") == "customer"
        ),
        "supplier_sources": _count(
            lambda row: row.get("query_type") == "supplier" or str((row.get("metadata") or {}).get("relation") or "") == "supplier"
        ),
        "dated_recent_items": len(recent),
        "undated_or_background_items": len(background),
        "full_text_items": _count(lambda row: row.get("is_full_text")),
        "tier1_count": _count(lambda row: int(row.get("source_tier") or 9) == 1),
        "tier2_count": _count(lambda row: int(row.get("source_tier") or 9) == 2),
        "tier3_count": _count(lambda row: int(row.get("source_tier") or 9) == 3),
        "tier4_count": _count(lambda row: int(row.get("source_tier") or 9) == 4),
        "tier5_count": _count(lambda row: int(row.get("source_tier") or 9) >= 5),
        "related_entities": plan.get("related_entities") or [],
        "claim_queries": [
            {
                "query": row.get("query"),
                "query_type": row.get("query_type"),
                "providers": row.get("providers") or ([row.get("provider")] if row.get("provider") else []),
                "claim_title": row.get("claim_title"),
                "entity": row.get("entity"),
            }
            for row in claim_rows
        ],
        "query_results": query_results,
        "duplicates_removed": duplicates_removed,
        "raw_count_before_dedupe": raw_count,
        "coverage_gaps": gaps[:12],
        "providers": providers,
        "tavily_vs_exa": compare_tavily_exa(docs, tavily_status=tavily_status, exa_status=exa_status),
        "alphavantage_overview": {
            "present": bool(overview),
            "symbol": (overview or {}).get("Symbol"),
            "revenue_ttm": (overview or {}).get("RevenueTTM"),
            "eps": (overview or {}).get("EPS"),
            "latest_quarter": (overview or {}).get("LatestQuarter"),
        }
        if overview
        else {"present": False},
        "warnings": warnings,
        "evidence_extracted": evidence_count,
        "window_days": days,
        "valuable_domains": sorted(
            {
                host_of(row.get("url"))
                for row in docs
                if int(row.get("source_tier") or 9) <= 3 and host_of(row.get("url"))
            }
        )[:24],
        "provider_roles": PROVIDER_ROLES,
        "important_relationship_types": plan.get("important_relationship_types") or [],
        "date_recovered_count": date_recovered_count,
        "discovered_docs": (quality_stats or {}).get("discovered_docs", len(docs)),
        "retained_for_reasoning": (quality_stats or {}).get("retained_for_reasoning"),
        "archived_docs": (quality_stats or {}).get("archived_docs"),
        "tier_distribution_before": (quality_stats or {}).get("tier_distribution_before"),
        "tier_distribution_after": (quality_stats or {}).get("tier_distribution_after"),
        "primary_source_count": (quality_stats or {}).get("primary_source_count"),
        "independent_source_count": (quality_stats or {}).get("independent_source_count"),
        "industry_source_count": (quality_stats or {}).get("industry_source_count"),
        "tier45_filtered_count": (quality_stats or {}).get("tier45_filtered_count"),
        "top_10_facts": (reasoning_context or {}).get("top_10_facts") or [],
        "reasoning_context": {
            "top_primary_facts": (reasoning_context or {}).get("top_primary_facts") or [],
            "top_independent_evidence": (reasoning_context or {}).get("top_independent_evidence") or [],
            "top_industry_evidence": (reasoning_context or {}).get("top_industry_evidence") or [],
            "top_counter_evidence": (reasoning_context or {}).get("top_counter_evidence") or [],
            "top_community_signals": (reasoning_context or {}).get("top_community_signals") or [],
            "open_gaps": (reasoning_context or {}).get("open_gaps") or [],
            "per_claim": (reasoning_context or {}).get("per_claim") or [],
        }
        if reasoning_context
        else None,
    }


def gather_external_intelligence(
    ticker: str,
    *,
    pack: dict[str, Any] | None = None,
    header: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
    understanding: dict[str, Any] | None = None,
    completer: Any | None = None,
    settings: Settings | None = None,
    days: int = NEWS_WINDOW_DAYS,
    fetch_live: bool = True,
    phase: str = "all",
    budget: SearchBudget | None = None,
    prior_urls: set[str] | None = None,
    include_macro: bool = True,
    include_alphavantage: bool = True,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    config = _settings(settings)
    pack = pack or {}
    header = header or {}
    claims = [row for row in (claims or []) if isinstance(row, dict)]
    llm_calls: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    query_results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    seen_urls = set(prior_urls or ())

    if phase in {"all", "base"}:
        for row in official_documents_from_pack(pack, symbol):
            url = str(row.get("canonical_url") or row.get("url") or "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            documents.append(row)

    plan: dict[str, Any] = {"related_entities": [], "queries": [], "coverage_gaps": []}
    allocated: list[dict[str, Any]] = []
    tavily_ok = tavily_configured(config)
    exa_ok = exa_configured(config)
    search_budget = budget or SearchBudget(
        tavily=TAVILY_SEARCH_BUDGET if tavily_ok else 0,
        exa=EXA_SEARCH_BUDGET if exa_ok else 0,
    )

    if fetch_live:
        plan, plan_audit = generate_search_plan(
            completer,
            ticker=symbol,
            pack=pack,
            header=header,
            understanding=understanding,
            claims=claims,
        )
        llm_calls.append(plan_audit)
        wanted = set(BASE_QUERY_TYPES | CLAIM_QUERY_TYPES)
        if phase == "base":
            wanted = set(BASE_QUERY_TYPES)
        elif phase == "claims":
            wanted = set(CLAIM_QUERY_TYPES)
        filtered = dict(plan)
        filtered["queries"] = [row for row in (plan.get("queries") or []) if str(row.get("query_type") or "") in wanted]
        if phase == "claims":
            extra: list[dict[str, Any]] = []
            for rtype in (plan.get("important_relationship_types") or [])[:6]:
                extra.append(
                    {
                        "query": f"{symbol} {rtype}",
                        "query_type": "related_entity",
                        "relationship_type": rtype,
                        "provider_hint": "exa",
                    }
                )
            for entity in (plan.get("related_entities") or [])[:4]:
                name = compact_text(entity.get("name"), 80)
                relation = str(entity.get("relation") or "related")
                if not name:
                    continue
                extra.append(
                    {
                        "query": f'{name} investor OR earnings OR "press release"',
                        "query_type": "related_entity",
                        "provider_hint": "exa",
                        "entity": name,
                        "relationship_type": relation,
                    }
                )
            filtered["queries"] = (filtered.get("queries") or []) + extra
        allocated = allocate_queries(
            filtered,
            tavily_budget=search_budget.tavily if tavily_ok else 0,
            exa_budget=search_budget.exa if exa_ok else 0,
        )
        if (
            tavily_ok
            and search_budget.tavily > 0
            and not any("tavily" in (row.get("providers") or []) for row in allocated)
        ):
            allocated.append(
                {
                    "query": f"{symbol} news",
                    "query_type": "company_news",
                    "providers": ["tavily"],
                    "provider_hint": "tavily",
                }
            )
        for item in allocated:
            for provider in item.get("providers") or []:
                if not search_budget.take(provider):
                    continue
                rows, audit = _search_one(
                    provider,
                    str(item.get("query") or ""),
                    settings=config,
                    ticker=symbol,
                    query_type=str(item.get("query_type") or "company_news"),
                    days=days,
                )
                audits.append(audit)
                kept = 0
                for row in rows:
                    url = str(row.get("canonical_url") or row.get("url") or "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    meta = dict(row.get("metadata") or {})
                    if item.get("claim_title"):
                        meta["claim_title"] = item.get("claim_title")
                    if item.get("entity"):
                        meta["entity"] = item.get("entity")
                        meta["relation"] = str(item.get("query_type") or "")
                    row["metadata"] = meta
                    documents.append(row)
                    kept += 1
                query_results.append(
                    {
                        "query": item.get("query"),
                        "query_type": item.get("query_type"),
                        "provider": provider,
                        "hit_count": audit.get("hit_count") or 0,
                        "usable_count": kept,
                        "high_quality_count": audit.get("high_quality_count") or 0,
                        "status": audit.get("status"),
                        "claim_title": item.get("claim_title"),
                        "entity": item.get("entity"),
                    }
                )

        if include_alphavantage and phase in {"all", "base"}:
            av_rows, av_audit = alphavantage_news(symbol, settings=config, days=days)
            audits.append(av_audit)
            for row in av_rows:
                url = str(row.get("canonical_url") or row.get("url") or "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                documents.append(row)
            overview, ov_audit = alphavantage_overview(symbol, settings=config)
            audits.append(ov_audit)
            warnings.extend(cross_check_alphavantage(overview, pack))
        else:
            overview = None

        if include_macro and phase in {"all", "base"}:
            fred_rows, fred_audit = fred_macro_documents(settings=config, ticker=symbol)
            audits.append(fred_audit)
            documents.extend(fred_rows)

        tavily_hits = int((_rollup(audits).get("tavily") or {}).get("hit_count") or 0)
        exa_hits = int((_rollup(audits).get("exa") or {}).get("hit_count") or 0)
        if tavily_hits == 0 and exa_hits == 0:
            fallback_items = list(filtered.get("queries") or [])[:5]
            if not fallback_items:
                fallback_items = [
                    {"query": f"{symbol} news", "query_type": "fallback"},
                    {"query": f"{symbol} earnings", "query_type": "company_earnings"},
                    {"query": f"{(header.get('company_name') or symbol)} customer OR supplier", "query_type": "industry_news"},
                ]
            for item in fallback_items:
                query = str(item.get("query") or "").strip()
                if not query:
                    continue
                qtype = str(item.get("query_type") or "fallback")
                rows, audit = duckduckgo_search(query, ticker=symbol, query_type=qtype, days=days, limit=5)
                audits.append(audit)
                kept = 0
                for row in rows:
                    url = str(row.get("canonical_url") or row.get("url") or "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    documents.append(row)
                    kept += 1
                query_results.append(
                    {
                        "query": query,
                        "query_type": qtype,
                        "provider": "duckduckgo",
                        "hit_count": audit.get("hit_count") or 0,
                        "usable_count": kept,
                        "high_quality_count": audit.get("high_quality_count") or 0,
                        "status": audit.get("status"),
                        "claim_title": item.get("claim_title"),
                        "entity": item.get("entity"),
                    }
                )
    else:
        overview = None

    raw_count = len(documents)
    documents, removed = dedupe_documents(documents)
    date_recovered_count = 0
    if fetch_live:
        primary_full = sum(
            1
            for row in documents
            if row.get("is_full_text") and int(row.get("source_tier") or 9) <= 2 and str(row.get("source_type") or "") != "macro"
        )
        need_bodies = [
            row
            for row in documents
            if not row.get("is_full_text")
            and int(row.get("source_tier") or 9) <= (3 if primary_full >= 8 else 4)
            and str(row.get("source_type") or "") != "macro"
        ]
        fill_missing_bodies(need_bodies[:12], settings=config, limit=8)
        for row in documents:
            if len(str(row.get("clean_text") or "")) >= 400:
                row["is_full_text"] = True
        date_recovered_count = recover_dates_from_pages(documents, limit=8)

    retained, archived, quality_stats = select_reasoning_documents(documents)
    extractable = docs_for_extraction(retained)
    facts: list[dict[str, Any]] = []
    llm_facts, extract_audit = llm_extract_facts(completer, extractable, ticker=symbol, claims=claims)
    llm_calls.append(extract_audit)
    facts.extend(llm_facts)
    if not facts:
        for row in extractable[:8]:
            facts.extend(deterministic_facts(row, limit=1))
    reasoning_context = compress_reasoning_context(retained, facts, claims)

    from .clients import _now

    retrieved_at = _now()
    evidence_bodies = facts_to_evidence_bodies(symbol, facts, retrieved_at=retrieved_at)
    providers = _rollup(audits)
    if fetch_live:
        if not tavily_ok and "tavily" not in providers:
            providers["tavily"] = empty_provider_status("tavily", status="not_configured", error="TAVILY_API_KEY missing")
        if not exa_ok and "exa" not in providers:
            providers["exa"] = empty_provider_status("exa", status="not_configured", error="EXA_API_KEY missing")
    report = build_report(
        documents,
        days=days,
        duplicates_removed=removed,
        raw_count=raw_count,
        plan=plan,
        allocated=allocated,
        query_results=query_results,
        providers=providers,
        warnings=warnings,
        overview=overview,
        evidence_count=len(evidence_bodies),
        quality_stats=quality_stats,
        reasoning_context=reasoning_context,
        date_recovered_count=date_recovered_count,
    )
    extra_gaps = list(reasoning_context.get("open_gaps") or [])
    merged_gaps = list(report.get("coverage_gaps") or [])
    for gap in extra_gaps:
        if gap not in merged_gaps:
            merged_gaps.append(gap)
    report["coverage_gaps"] = merged_gaps[:12]
    recent = [row for row in retained if within_days(row.get("published_at"), days) and row.get("source_type") != "macro"]
    background = [row for row in documents if row not in retained]
    return {
        "ticker": symbol,
        "documents": documents,
        "retained_documents": retained,
        "archived_documents": archived,
        "recent_documents": recent,
        "background_documents": background,
        "facts": facts,
        "evidence_bodies": evidence_bodies,
        "news_hits": documents_to_news_hits(retained, days=days),
        "related_entities": plan.get("related_entities") or [],
        "important_relationship_types": plan.get("important_relationship_types") or [],
        "claim_queries": report.get("claim_queries") or [],
        "query_results": query_results,
        "provider_audits": audits,
        "providers": providers,
        "llm_calls": llm_calls,
        "warnings": warnings,
        "duplicates_removed": removed,
        "raw_count": raw_count,
        "report": report,
        "reasoning_context": reasoning_context,
        "budget_remaining": {"tavily": search_budget.tavily, "exa": search_budget.exa},
        "phase": phase,
    }


def merge_intelligence(*parts: dict[str, Any]) -> dict[str, Any]:
    chunks = [part for part in parts if part]
    if not chunks:
        return {
            "ticker": "",
            "documents": [],
            "recent_documents": [],
            "background_documents": [],
            "facts": [],
            "evidence_bodies": [],
            "news_hits": [],
            "related_entities": [],
            "claim_queries": [],
            "query_results": [],
            "provider_audits": [],
            "providers": {},
            "llm_calls": [],
            "warnings": [],
            "duplicates_removed": 0,
            "raw_count": 0,
            "report": {},
            "reasoning_context": {},
            "retained_documents": [],
            "archived_documents": [],
            "important_relationship_types": [],
            "budget_remaining": {"tavily": 0, "exa": 0},
            "phase": "merged",
        }
    if len(chunks) == 1:
        return chunks[0]
    merged_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in chunks:
        for row in part.get("documents") or []:
            key = str(row.get("canonical_url") or row.get("url") or row.get("document_id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged_docs.append(row)
    docs, removed = dedupe_documents(merged_docs)
    facts: list[dict[str, Any]] = []
    bodies: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    llm_calls: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    query_results: list[dict[str, Any]] = []
    allocated: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    raw_count = 0
    overview = None
    ticker = str(chunks[-1].get("ticker") or "")
    for part in chunks:
        facts.extend(part.get("facts") or [])
        bodies.extend(part.get("evidence_bodies") or [])
        audits.extend(part.get("provider_audits") or [])
        llm_calls.extend(part.get("llm_calls") or [])
        warnings.extend(part.get("warnings") or [])
        query_results.extend(part.get("query_results") or [])
        allocated.extend(part.get("claim_queries") or [])
        entities.extend(part.get("related_entities") or [])
        raw_count += int(part.get("raw_count") or 0)
        report = part.get("report") or {}
        if (report.get("alphavantage_overview") or {}).get("present"):
            overview = {
                "Symbol": report["alphavantage_overview"].get("symbol"),
                "RevenueTTM": report["alphavantage_overview"].get("revenue_ttm"),
                "EPS": report["alphavantage_overview"].get("eps"),
                "LatestQuarter": report["alphavantage_overview"].get("latest_quarter"),
            }
    providers = _rollup(audits)
    for part in chunks:
        for name, rec in (part.get("providers") or {}).items():
            if name not in providers:
                providers[name] = rec
    entities_unique: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for item in entities:
        key = str(item.get("name") or "").strip().lower()
        if not key or key in seen_entities:
            continue
        seen_entities.add(key)
        entities_unique.append(item)
    entities = entities_unique[:12]
    relationship_types: list[str] = []
    seen_types: set[str] = set()
    for part in chunks:
        for item in part.get("important_relationship_types") or (part.get("report") or {}).get("important_relationship_types") or []:
            key = str(item or "").strip()
            if not key or key in seen_types:
                continue
            seen_types.add(key)
            relationship_types.append(key)
    retained, archived, quality_stats = select_reasoning_documents(docs)
    retained_ids = {str(row.get("document_id") or "") for row in retained}
    facts = [row for row in facts if str(row.get("document_id") or "") in retained_ids] or facts[:12]
    claim_rows = [
        {"title": row.get("claim_title") or row.get("title") or row.get("query")}
        for row in allocated
        if row.get("claim_title") or row.get("query_type") == "claim"
    ]
    reasoning_context = compress_reasoning_context(retained, facts, claim_rows)
    bodies = [row for row in bodies if str((row.get("raw_reference") or {}).get("document_id") or "") in retained_ids] or bodies
    plan = {
        "related_entities": entities,
        "queries": allocated,
        "coverage_gaps": list(reasoning_context.get("open_gaps") or []),
        "important_relationship_types": relationship_types,
    }
    report = build_report(
        docs,
        days=NEWS_WINDOW_DAYS,
        duplicates_removed=removed + sum(int(part.get("duplicates_removed") or 0) for part in chunks),
        raw_count=raw_count,
        plan=plan,
        allocated=allocated,
        query_results=query_results,
        providers=providers,
        warnings=warnings,
        overview=overview,
        evidence_count=len(bodies),
        quality_stats=quality_stats,
        reasoning_context=reasoning_context,
    )
    last = chunks[-1]
    return {
        "ticker": ticker,
        "documents": docs,
        "retained_documents": retained,
        "archived_documents": archived,
        "recent_documents": [row for row in retained if within_days(row.get("published_at"), NEWS_WINDOW_DAYS) and row.get("source_type") != "macro"],
        "background_documents": archived,
        "facts": facts,
        "evidence_bodies": bodies,
        "news_hits": documents_to_news_hits(retained, days=NEWS_WINDOW_DAYS),
        "related_entities": entities,
        "important_relationship_types": relationship_types,
        "claim_queries": allocated,
        "query_results": query_results,
        "provider_audits": audits,
        "providers": providers,
        "llm_calls": llm_calls,
        "warnings": warnings,
        "duplicates_removed": report["duplicates_removed"],
        "raw_count": raw_count,
        "report": report,
        "reasoning_context": reasoning_context,
        "budget_remaining": last.get("budget_remaining") or {"tavily": 0, "exa": 0},
        "phase": "merged",
    }
