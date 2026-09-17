"""Claim-driven and related-entity query generation. LLM proposes; templates fill gaps."""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text, complete_structured, dump_user

from .types import TAVILY_NEWS_TYPES


def load_external_prompt(name: str) -> str:
    from importlib.resources import files

    return files("stock_pm").joinpath(f"brain/prompts/{name}").read_text(encoding="utf-8").strip()


def _profile(pack: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    profile = dict((pack or {}).get("company_profile") or {})
    return {
        "ticker": header.get("ticker") or pack.get("ticker"),
        "company_name": header.get("company_name") or profile.get("legal_name"),
        "sector": header.get("sector") or profile.get("sector"),
        "industry": header.get("industry"),
    }


FALLBACK_RELATED = {
    "AVGO": [
        {"name": "Google", "relation": "hyperscaler/customer", "why": "custom silicon / TPU adjacency"},
        {"name": "Meta", "relation": "hyperscaler/customer", "why": "custom AI accelerator adjacency"},
        {"name": "Microsoft", "relation": "hyperscaler/customer", "why": "hyperscaler networking and AI spend"},
        {"name": "Amazon", "relation": "hyperscaler/customer", "why": "hyperscaler capex"},
        {"name": "TSMC", "relation": "supplier", "why": "advanced packaging / foundry"},
        {"name": "Oracle", "relation": "hyperscaler/customer", "why": "datacenter AI build"},
    ],
    "AAPL": [
        {"name": "TSMC", "relation": "supplier", "why": "foundry / advanced process"},
        {"name": "Foxconn", "relation": "supplier", "why": "assembly"},
        {"name": "China", "relation": "geography", "why": "regulatory and demand exposure"},
        {"name": "Apple Intelligence", "relation": "product", "why": "on-device AI monetization"},
    ],
    "LITE": [
        {"name": "Coherent", "relation": "peer", "why": "optical peer"},
        {"name": "Fabrinet", "relation": "supplier", "why": "optical manufacturing revenue"},
        {"name": "hyperscalers", "relation": "hyperscaler/customer", "why": "datacenter optical demand"},
        {"name": "800G", "relation": "technology", "why": "current AI optical ramp"},
        {"name": "1.6T", "relation": "technology", "why": "next optical generation"},
    ],
}

DEFAULT_RELATIONSHIP_TYPES = {
    "AAPL": ["product", "supplier", "channel", "geography", "regulation", "developer ecosystem"],
    "AVGO": ["hyperscaler/customer", "supplier", "technology", "competitor", "datacenter infrastructure"],
    "LITE": ["hyperscaler/customer", "peer", "supplier", "technology", "capacity", "optical ecosystem"],
}

QUERY_TYPE_SET = {
    "company_official",
    "company_earnings",
    "company_news",
    "industry_news",
    "claim",
    "related_entity",
    "customer",
    "supplier",
}


def relationship_types_for(ticker: str) -> list[str]:
    return list(DEFAULT_RELATIONSHIP_TYPES.get(str(ticker).upper()) or ["product", "technology", "regulation"])


def fallback_plan(ticker: str, pack: dict[str, Any], header: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    info = _profile(pack, header)
    name = info.get("company_name") or ticker
    sector = info.get("sector") or "industry"
    types = relationship_types_for(ticker)
    entities: list[dict[str, Any]] = list(FALLBACK_RELATED.get(str(ticker).upper()) or [])
    queries: list[dict[str, Any]] = [
        {
            "query": f'{ticker} OR "{name}" (investor OR "press release" OR 8-K OR 10-Q OR earnings)',
            "query_type": "company_official",
            "provider_hint": "exa",
        },
        {"query": f'{ticker} "{name}" news', "query_type": "company_news", "provider_hint": "tavily"},
        {"query": f"{name} {sector} {types[0] if types else 'demand'}", "query_type": "industry_news", "provider_hint": "exa"},
    ]
    for rtype in types[:6]:
        queries.append(
            {
                "query": f"{name} {rtype}",
                "query_type": "related_entity",
                "relationship_type": rtype,
                "provider_hint": "exa",
            }
        )
    for entity in entities[:4]:
        relation = entity.get("relation") or "related"
        queries.append(
            {
                "query": f'{entity["name"]} investor OR earnings OR "press release" {name}',
                "query_type": "related_entity",
                "provider_hint": "exa",
                "entity": entity["name"],
                "relationship_type": relation,
            }
        )
    for claim in claims[:4]:
        title = compact_text(claim.get("title") or claim.get("statement") or "", 80)
        if not title:
            continue
        queries.append(
            {
                "query": f'{ticker} OR "{name}" {title} (investor OR "press release" OR 8-K OR 10-Q)',
                "query_type": "claim",
                "provider_hint": "exa",
                "claim_title": title,
            }
        )
        if entities:
            queries.append(
                {
                    "query": f'{entities[0]["name"]} investor OR earnings {title}',
                    "query_type": "claim",
                    "provider_hint": "exa",
                    "claim_title": title,
                    "entity": entities[0]["name"],
                }
            )
    return {
        "important_relationship_types": types,
        "related_entities": entities,
        "queries": queries[:16],
        "coverage_gaps": ["LLM search plan unavailable; used official-first relationship queries."],
    }


def _normalize_query_type(value: Any) -> str:
    qtype = str(value or "company_news")
    if qtype in QUERY_TYPE_SET:
        return qtype
    return "related_entity"


def _hint_for(qtype: str, hint: str) -> str:
    if qtype in TAVILY_NEWS_TYPES:
        return "tavily"
    if hint == "tavily" and qtype in TAVILY_NEWS_TYPES:
        return "tavily"
    return "exa"


def generate_search_plan(
    completer: Any,
    *,
    ticker: str,
    pack: dict[str, Any],
    header: dict[str, Any],
    understanding: dict[str, Any] | None,
    claims: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    types = relationship_types_for(ticker)
    user = {
        "ticker": ticker,
        "company": _profile(pack, header),
        "company_understanding": {
            "how_company_makes_money": (understanding or {}).get("how_company_makes_money"),
            "largest_growth_driver": (understanding or {}).get("largest_growth_driver"),
            "largest_operating_risk": (understanding or {}).get("largest_operating_risk"),
            "value_variables_1to3y": (understanding or {}).get("value_variables_1to3y"),
        },
        "core_claims": [
            {
                "title": compact_text(row.get("title"), 80),
                "statement": compact_text(row.get("statement"), 240),
                "why_it_matters": compact_text(row.get("why_it_matters"), 160),
            }
            for row in claims[:5]
            if isinstance(row, dict)
        ],
        "example_relationship_types": types,
        "rules": [
            "Output important_relationship_types from this company's business model. Do not default every ticker to customers/suppliers/competitors.",
            "Primary source first for each Core Claim: company official, related-entity official, government/regulatory, then media.",
            "Do not invent customers, contracts, or numbers.",
            "Queries must be searchable, not ticker canned slogans.",
            "Exa is primary discovery. Tavily is news supplement only. Never set provider_hint to both.",
        ],
    }
    payload, audit = complete_structured(
        completer,
        system=load_external_prompt("external_search_plan.txt"),
        user=dump_user(user),
    )
    audit = dict(audit or {})
    audit["step"] = "external_search_plan"
    if not payload:
        plan = fallback_plan(ticker, pack, header, claims)
        audit["fallback_used"] = True
        return plan, audit
    queries: list[dict[str, Any]] = []
    for item in payload.get("queries") or []:
        if isinstance(item, str):
            text = compact_text(item, 160)
            if text:
                queries.append({"query": text, "query_type": "company_news", "provider_hint": "tavily"})
            continue
        if not isinstance(item, dict):
            continue
        text = compact_text(item.get("query") or item.get("q"), 160)
        if not text:
            continue
        qtype = _normalize_query_type(item.get("query_type"))
        hint = _hint_for(qtype, str(item.get("provider_hint") or ""))
        queries.append(
            {
                "query": text,
                "query_type": qtype,
                "provider_hint": hint,
                "claim_title": compact_text(item.get("claim_title"), 80) or None,
                "entity": compact_text(item.get("entity"), 80) or None,
                "relationship_type": compact_text(item.get("relationship_type"), 60) or None,
            }
        )
    entities = []
    for item in payload.get("related_entities") or []:
        if isinstance(item, str):
            name = compact_text(item, 80)
            if name:
                entities.append({"name": name, "relation": "related"})
            continue
        if not isinstance(item, dict):
            continue
        name = compact_text(item.get("name") or item.get("entity"), 80)
        if not name:
            continue
        entities.append(
            {
                "name": name,
                "relation": compact_text(item.get("relation") or "related", 40),
                "why": compact_text(item.get("why"), 160),
            }
        )
    parsed_types = [
        compact_text(item, 60)
        for item in (payload.get("important_relationship_types") or [])
        if str(item).strip()
    ]
    if not parsed_types:
        parsed_types = sorted({str(row.get("relation") or "") for row in entities if row.get("relation")}) or types
    if not queries:
        return fallback_plan(ticker, pack, header, claims), audit
    return {
        "important_relationship_types": parsed_types[:8],
        "related_entities": entities[:10],
        "queries": queries[:16],
        "coverage_gaps": [compact_text(item, 160) for item in (payload.get("coverage_gaps") or []) if str(item).strip()][:8],
    }, audit


def allocate_queries(plan: dict[str, Any], *, tavily_budget: int, exa_budget: int) -> list[dict[str, Any]]:
    """Exa = primary discovery. Tavily = topic=news supplement only. Never dual-run a query."""
    out: list[dict[str, Any]] = []
    tavily_left = tavily_budget
    exa_left = exa_budget
    for item in plan.get("queries") or []:
        qtype = str(item.get("query_type") or "company_news")
        if qtype in TAVILY_NEWS_TYPES:
            if tavily_left <= 0:
                continue
            provider = "tavily"
            tavily_left -= 1
        else:
            if exa_left <= 0:
                continue
            provider = "exa"
            exa_left -= 1
        row = dict(item)
        row["providers"] = [provider]
        row["provider_hint"] = provider
        out.append(row)
        if tavily_left <= 0 and exa_left <= 0:
            break
    return out
