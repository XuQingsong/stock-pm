"""Claim-driven and related-entity query generation. LLM proposes; templates fill gaps."""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text, complete_structured, dump_user


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
        {"name": "Google", "relation": "customer", "why": "custom silicon / TPU adjacency"},
        {"name": "Meta", "relation": "customer", "why": "custom AI accelerator adjacency"},
        {"name": "Microsoft", "relation": "customer", "why": "hyperscaler networking and AI spend"},
        {"name": "Amazon", "relation": "customer", "why": "hyperscaler capex"},
        {"name": "TSMC", "relation": "supplier", "why": "advanced packaging / foundry"},
        {"name": "Oracle", "relation": "customer", "why": "datacenter AI build"},
    ],
    "AAPL": [
        {"name": "TSMC", "relation": "supplier", "why": "foundry / advanced process"},
        {"name": "Foxconn", "relation": "supplier", "why": "assembly"},
        {"name": "China", "relation": "market", "why": "regulatory and demand exposure"},
        {"name": "Apple Intelligence", "relation": "technology", "why": "on-device AI monetization"},
    ],
    "LITE": [
        {"name": "Coherent", "relation": "competitor", "why": "optical peer"},
        {"name": "Fabrinet", "relation": "supplier", "why": "optical manufacturing revenue"},
        {"name": "hyperscalers", "relation": "customer", "why": "datacenter optical demand"},
        {"name": "800G", "relation": "technology", "why": "current AI optical ramp"},
        {"name": "1.6T", "relation": "technology", "why": "next optical generation"},
    ],
}


def fallback_plan(ticker: str, pack: dict[str, Any], header: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    info = _profile(pack, header)
    name = info.get("company_name") or ticker
    sector = info.get("sector") or "industry"
    queries = [
        {"query": f'{ticker} OR "{name}" earnings OR 8-K OR 10-Q', "query_type": "company_official", "provider_hint": "tavily"},
        {"query": f'{ticker} "{name}" news', "query_type": "company_news", "provider_hint": "tavily"},
        {"query": f"{name} {sector} demand OR customer OR supplier", "query_type": "industry_news", "provider_hint": "exa"},
    ]
    entities: list[dict[str, Any]] = list(FALLBACK_RELATED.get(str(ticker).upper()) or [])
    for entity in entities[:4]:
        relation = entity.get("relation") or "related"
        qtype = "customer" if relation == "customer" else "supplier" if relation == "supplier" else "related_entity"
        queries.append(
            {
                "query": f'{entity["name"]} {name} {relation} demand OR capex OR supply',
                "query_type": qtype,
                "provider_hint": "exa",
                "entity": entity["name"],
            }
        )
    for claim in claims[:5]:
        title = compact_text(claim.get("title") or claim.get("statement") or "", 80)
        statement = compact_text(claim.get("statement") or "", 160)
        if not title:
            continue
        queries.append({"query": f"{name} {title}", "query_type": "claim", "provider_hint": "exa", "claim_title": title})
        queries.append(
            {
                "query": f"{statement} customer OR supplier OR capex" if statement else f"{name} {title} industry",
                "query_type": "claim",
                "provider_hint": "tavily",
                "claim_title": title,
            }
        )
    return {
        "related_entities": entities,
        "queries": queries[:14],
        "coverage_gaps": ["LLM search plan unavailable; used generic official/news/industry queries."],
    }


def generate_search_plan(
    completer: Any,
    *,
    ticker: str,
    pack: dict[str, Any],
    header: dict[str, Any],
    understanding: dict[str, Any] | None,
    claims: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        "rules": [
            "Do not invent customers, contracts, or numbers.",
            "Queries must be searchable, not ticker canned slogans.",
            "Prefer customers, suppliers, industry demand, and technologies that could change the claims.",
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
        qtype = str(item.get("query_type") or "company_news")
        if qtype not in {
            "company_official",
            "company_earnings",
            "company_news",
            "industry_news",
            "claim",
            "related_entity",
            "customer",
            "supplier",
        }:
            qtype = "industry_news"
        hint = str(item.get("provider_hint") or "")
        if hint not in {"tavily", "exa", "both"}:
            hint = "exa" if qtype in {"claim", "related_entity", "customer", "supplier", "industry_news"} else "tavily"
        queries.append(
            {
                "query": text,
                "query_type": qtype,
                "provider_hint": hint,
                "claim_title": compact_text(item.get("claim_title"), 80) or None,
                "entity": compact_text(item.get("entity"), 80) or None,
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
    if not queries:
        return fallback_plan(ticker, pack, header, claims), audit
    return {
        "related_entities": entities[:10],
        "queries": queries[:16],
        "coverage_gaps": [compact_text(item, 160) for item in (payload.get("coverage_gaps") or []) if str(item).strip()][:8],
    }, audit


def allocate_queries(plan: dict[str, Any], *, tavily_budget: int, exa_budget: int) -> list[dict[str, Any]]:
    """Cap provider calls. Shared comparison queries consume both budgets."""
    out: list[dict[str, Any]] = []
    tavily_left = tavily_budget
    exa_left = exa_budget
    comparison_left = 3
    for item in plan.get("queries") or []:
        hint = str(item.get("provider_hint") or "tavily")
        qtype = str(item.get("query_type") or "company_news")
        providers: list[str] = []
        want_both = hint == "both" or (comparison_left > 0 and qtype in {"company_news", "industry_news", "claim"})
        if want_both and tavily_left > 0 and exa_left > 0:
            providers = ["tavily", "exa"]
            tavily_left -= 1
            exa_left -= 1
            comparison_left -= 1
        elif hint == "exa" and exa_left > 0:
            providers = ["exa"]
            exa_left -= 1
        elif tavily_left > 0:
            providers = ["tavily"]
            tavily_left -= 1
        elif exa_left > 0:
            providers = ["exa"]
            exa_left -= 1
        if not providers:
            continue
        row = dict(item)
        row["providers"] = providers
        out.append(row)
        if tavily_left <= 0 and exa_left <= 0:
            break
    return out
