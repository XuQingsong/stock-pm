"""Judge whether a fact is valid evidence for a specific assumption.

Linking is per (evidence, assumption statement, category). Keyword presence
is not enough. Price reactions stay market context unless the claim is about
valuation.
"""

from __future__ import annotations

import re
from typing import Any


LINK_RELEVANCE = ("direct", "indirect", "background")
SOURCE_QUALITIES = ("primary", "high_quality_secondary", "secondary", "weak")

QUALITY_WEIGHT = {
    "primary": 1.0,
    "high_quality_secondary": 0.75,
    "secondary": 0.45,
    "weak": 0.2,
}
RELEVANCE_WEIGHT = {"direct": 1.0, "indirect": 0.45, "background": 0.12}
STRENGTH_WEIGHT = {"strong": 1.0, "moderate": 0.6, "weak": 0.28}

PRIMARY_SOURCE_TYPES = {
    "sec_filing",
    "earnings_release",
    "transcript",
    "official_document",
    "filing",
}
HIGH_SECONDARY_SOURCE_TYPES = {
    "investor_presentation",
    "conference_remarks",
    "press_release",
}

HARD_COUNTER_RE = re.compile(
    r"\b("
    r"postpone|postponed|delayed|delay|cancell?ed|cancellation|"
    r"push[- ]out|slipped|slippage|shortfall|"
    r"cut capex|reduc(?:ed|ing) capital|capex cut|"
    r"power (?:short(?:age)?|constrain)|grid constrain|"
    r"supply miss|missed supply|"
    r"customer cancell|"
    r"lowered guidance|cut outlook|reduc(?:ed|ing) (?:deploy|outlook|guidance)"
    r")\b",
    re.I,
)
PRICE_RE = re.compile(
    r"earnings-window|post_1d|vs_spy|vs_qqq|vs_sector|ttm pe|post-print \d+d return|realized volatility",
    re.I,
)
CONTRACT_RE = re.compile(
    r"multi-year|long[- ]term contract|recognized as revenue over|lease agreement|"
    r"customer contracts|backstop agreement",
    re.I,
)
CAPEX_RE = re.compile(r"capital expend|capital spend|\bcapex\b", re.I)
DEMAND_RE = re.compile(
    r"customer (?:demand|forecast|deploy)|hyperscal|frontier ai|end demand|customer-side",
    re.I,
)
SUPPLY_RE = re.compile(
    r"foundry|wafer|packag|supply (?:capacity|agreement)|production capacity|factory ramp",
    re.I,
)
POWER_RE = re.compile(r"\bpower\b|electricit|data[- ]center (?:site|build|capacity|deploy)", re.I)
GUIDANCE_RE = re.compile(r"\bguidance\b|\boutlook\b|expects? .{0,40}revenue", re.I)
GROWTH_RE = re.compile(r"year-over-year|latest print|revenue=|yoy", re.I)
MARGIN_RE = re.compile(r"gross margin|margin mix|mix shift|margin press|due to revenue mix", re.I)
CONC_RE = re.compile(r"largest customer|customer concentration|\d[\d\.]*\s*(%|percent) of revenue", re.I)
COMP_RE = re.compile(r"competitor|competition|market share", re.I)

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "management",
    "stated",
    "can",
    "deliver",
    "commitment",
    "latest",
    "over",
    "next",
    "into",
}


def _hay(text: Any) -> str:
    return str(text or "").lower()


def _tokens(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z]{4,}", _hay(text)) if part not in STOPWORDS}


def evidence_kind(fact: str) -> str:
    text = str(fact or "")
    if HARD_COUNTER_RE.search(text):
        return "hard_counter"
    if PRICE_RE.search(text):
        return "price_reaction"
    if CONTRACT_RE.search(text):
        return "contract"
    if CAPEX_RE.search(text):
        return "customer_capex"
    if DEMAND_RE.search(text):
        return "customer_demand"
    if SUPPLY_RE.search(text):
        return "supply"
    if POWER_RE.search(text):
        return "power_infra"
    if CONC_RE.search(text):
        return "concentration"
    if MARGIN_RE.search(text):
        return "margin"
    if GUIDANCE_RE.search(text):
        return "guidance"
    if GROWTH_RE.search(text):
        return "growth_print"
    if COMP_RE.search(text):
        return "competition"
    return "other"


def assumption_kind(assumption: dict[str, Any] | None) -> str:
    row = assumption or {}
    category = str(row.get("category") or "").lower()
    stmt = _hay(row.get("statement"))
    if category == "valuation" or "valuation" in stmt or "multiple" in stmt:
        return "valuation"
    if category == "margin" or ("margin" in stmt and "growth" not in stmt):
        return "margin"
    if category == "supply" or (category != "demand" and "supply" in stmt and "demand" not in stmt):
        return "supply"
    if category == "guidance_delivery" or "guidance" in stmt or "consensus" in stmt:
        return "guidance"
    if category == "execution" or "stated commitment" in stmt or "stated commitment:" in stmt:
        return "execution"
    if category == "competition" or "competitive" in stmt:
        return "competition"
    if category == "demand" and any(token in stmt for token in ("persist", "sustain", "run-rate", "two year", "next two")):
        return "growth_persist"
    if category == "demand":
        return "demand_visibility"
    return category or "other"


def source_quality_for(evidence: dict[str, Any] | None) -> str:
    row = evidence or {}
    explicit = str(row.get("source_quality") or "").strip()
    if explicit in SOURCE_QUALITIES:
        return explicit
    source_type = str(row.get("source_type") or "")
    evidence_type = str(row.get("evidence_type") or "")
    if evidence_type == "quant" or source_type == "structured_provider":
        return "secondary"
    if source_type in PRIMARY_SOURCE_TYPES or evidence_type in {"filing", "guidance", "transcript"}:
        return "primary"
    if source_type in HIGH_SECONDARY_SOURCE_TYPES:
        return "high_quality_secondary"
    return "secondary"


def claim_family(fact: str) -> str:
    kind = evidence_kind(fact)
    mapping = {
        "contract": "contract_visibility",
        "customer_demand": "contract_visibility",
        "customer_capex": "capex_demand",
        "hard_counter": "hard_counter",
        "price_reaction": "price_window",
        "supply": "supply",
        "power_infra": "power_infra",
        "guidance": "guidance",
        "growth_print": "growth_print",
        "margin": "margin",
        "concentration": "concentration",
        "competition": "competition",
    }
    return mapping.get(kind, kind or "other")


def independence_key_for(evidence: dict[str, Any] | None) -> str:
    row = evidence or {}
    existing = str(row.get("independence_key") or "").strip()
    if existing:
        return existing
    url = str(row.get("source_url") or row.get("source") or "").strip().lower().split("?")[0]
    stamp = str(row.get("source_time") or "")[:10]
    family = claim_family(str(row.get("fact") or row.get("excerpt") or ""))
    return f"{url}|{family}|{stamp}"


def annotate_evidence(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload["source_quality"] = source_quality_for(payload)
    payload["independence_key"] = independence_key_for(payload)
    return payload


def _overlap(evidence: dict[str, Any], assumption: dict[str, Any]) -> int:
    return len(_tokens(str(evidence.get("fact") or "")) & _tokens(str(assumption.get("statement") or "")))


def _pack(direction: str, strength: str, relevance: str, reason: str) -> dict[str, str]:
    return {
        "direction": direction,
        "strength": strength,
        "relevance": relevance,
        "reason": reason,
    }


def judge_link(evidence: dict[str, Any] | None, assumption: dict[str, Any] | None) -> dict[str, str] | None:
    """Return a link judgment or None when the fact does not bear on this claim."""
    ev = evidence or {}
    asm = assumption or {}
    fact = str(ev.get("fact") or "")
    if not fact or not str(asm.get("statement") or asm.get("id") or ""):
        return None
    kind = evidence_kind(fact)
    target = assumption_kind(asm)
    overlap = _overlap(ev, asm)

    if kind == "price_reaction":
        if target == "valuation":
            return _pack(
                "contextual",
                "moderate",
                "direct",
                "price and multiple changes speak to valuation context, not to whether the fundamental claim is true",
            )
        return _pack(
            "contextual",
            "weak",
            "background",
            "earnings-window price action is market context and is not a test of this fundamental assumption",
        )

    if kind == "hard_counter":
        if target in {"execution", "demand_visibility", "growth_persist", "guidance", "supply"}:
            return _pack(
                "oppose",
                "strong" if overlap >= 2 else "moderate",
                "direct",
                "source language describes delay, cancellation, a miss, or a cut that bears on this claim",
            )
        return _pack(
            "oppose",
            "weak",
            "indirect",
            "a delivery setback is only indirectly related to this assumption",
        )

    if kind == "contract":
        if target == "demand_visibility":
            return _pack("support", "strong", "direct", "a multi-year or customer contract is direct evidence that demand has some visibility")
        if target == "execution":
            strength = "strong" if overlap >= 3 else "moderate"
            return _pack("support", strength, "direct", "contract or lease language is a source-backed delivery claim, not proof it will be fulfilled")
        if target == "growth_persist":
            return _pack("support", "weak", "indirect", "one contract raises some revenue visibility but does not prove total growth persists")
        if target == "guidance":
            return _pack("contextual", "weak", "background", "a long-term contract does not by itself prove the next guidance print")
        return None

    if kind == "customer_demand":
        if target == "demand_visibility":
            return _pack("support", "moderate", "direct", "customer-side demand language is direct but still not an independent capex check")
        if target == "growth_persist":
            return _pack("support", "weak", "indirect", "customer demand language is only an indirect input to two-year total growth")
        if target == "execution":
            return _pack("support", "moderate" if overlap else "weak", "indirect", "customer demand language is related to delivery but is not a fulfillment proof")
        return None

    if kind == "customer_capex":
        if target in {"demand_visibility", "execution"}:
            return _pack("support", "moderate", "direct", "customer or industry capex language is a direct input to deployment and demand")
        if target == "growth_persist":
            return _pack("support", "weak", "indirect", "capex plans can support growth but do not prove the two-year revenue path")
        if target == "guidance":
            return _pack("contextual", "weak", "background", "capex commentary is background for near-term guidance delivery")
        return None

    if kind == "supply":
        if target in {"execution", "supply"}:
            return _pack("support", "moderate", "direct", "capacity or supply language directly bears on whether the plan can be produced")
        if target in {"demand_visibility", "growth_persist"}:
            return _pack("contextual", "weak", "background", "supply facts are background for demand claims, not proof of demand")
        return None

    if kind == "power_infra":
        if "constrain" in _hay(fact) or "short" in _hay(fact):
            if target in {"execution", "demand_visibility"}:
                return _pack("oppose", "moderate", "direct", "power or site constraints directly challenge deployment timing")
        if target == "execution":
            return _pack("contextual", "weak", "indirect", "infrastructure language is related to deployment but is not a demand proof")
        return None

    if kind == "guidance":
        if target == "guidance":
            return _pack("support", "moderate", "direct", "stated outlook language is direct evidence for the guidance-delivery claim")
        if target == "growth_persist":
            return _pack("support", "weak", "indirect", "an outlook is only an indirect input to multi-year growth persistence")
        if target == "execution":
            return _pack("contextual", "weak", "background", "guidance language is background for a longer-dated commitment")
        return None

    if kind == "growth_print":
        if target == "growth_persist":
            return _pack("support", "weak", "indirect", "a recent print shows growth happened; it does not prove the growth persists")
        if target == "demand_visibility":
            return _pack("support", "weak", "indirect", "reported growth is an indirect signal of demand, not customer confirmation")
        if target == "guidance":
            return _pack("contextual", "weak", "background", "a historical beat is background for whether the next outlook is delivered")
        return None

    if kind == "margin":
        pressured = bool(re.search(r"compress|press|decline|erosion|mix", _hay(fact)))
        if target == "margin":
            return _pack("oppose" if pressured else "support", "moderate", "direct", "margin language directly bears on the margin assumption")
        if target == "growth_persist" and pressured:
            return _pack("oppose", "weak", "indirect", "mix or margin pressure can offset volume and only indirectly challenges growth persistence")
        if pressured:
            return _pack("contextual", "weak", "background", "margin mix is background unless the assumption is about margins or durable growth")
        return None

    if kind == "concentration":
        if target in {"execution", "growth_persist"}:
            return _pack("oppose", "weak", "indirect", "customer concentration is a risk to durability, not a hard miss by itself")
        if target == "demand_visibility":
            return _pack("contextual", "weak", "background", "concentration is background for whether demand is real")
        return None

    if kind == "competition":
        if target == "competition":
            return _pack("contextual", "moderate", "direct", "competitive language belongs on the competition assumption")
        return None

    if overlap >= 4:
        return _pack("contextual", "weak", "indirect", "shared language is not enough to treat this as causal support or opposition")
    return None


def link_weight(evidence: dict[str, Any] | None, judgment: dict[str, Any] | None) -> float:
    row = judgment or {}
    return (
        QUALITY_WEIGHT.get(source_quality_for(evidence), 0.45)
        * RELEVANCE_WEIGHT.get(str(row.get("relevance") or "indirect"), 0.12)
        * STRENGTH_WEIGHT.get(str(row.get("strength") or "moderate"), 0.28)
    )


def cluster_family_weights(
    items: list[tuple[dict[str, Any], dict[str, Any], float]],
) -> list[dict[str, Any]]:
    """Collapse same-source, same-claim excerpts into one independent family."""
    families: dict[str, dict[str, Any]] = {}
    for evidence, judgment, weight in items:
        key = independence_key_for(evidence)
        current = families.get(key)
        if current is None or weight > current["weight"]:
            families[key] = {
                "independence_key": key,
                "weight": weight,
                "direction": judgment.get("direction"),
                "strength": judgment.get("strength"),
                "relevance": judgment.get("relevance"),
                "reason": judgment.get("reason"),
                "fact": str((evidence or {}).get("fact") or "")[:240],
                "source_quality": source_quality_for(evidence),
                "members": (current or {}).get("members", 0) + 1 if current else 1,
            }
        elif current is not None:
            current["members"] = int(current.get("members") or 1) + 1
    return sorted(families.values(), key=lambda row: row["weight"], reverse=True)


def judged_links(
    evidence_items: list[dict[str, Any]],
    assumption: dict[str, Any],
    *,
    allow_support: bool = True,
    allow_oppose: bool = True,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in evidence_items:
        judgment = judge_link(item, assumption)
        if judgment is None:
            continue
        if judgment["direction"] == "support" and not allow_support:
            continue
        if judgment["direction"] == "oppose" and not allow_oppose:
            if judgment["relevance"] == "direct":
                continue
            judgment = {**judgment, "direction": "contextual", "reason": judgment["reason"] + "; recorded as context rather than opposition"}
        weight = link_weight(item, judgment)
        payload = {
            "evidence_key": item.get("_key"),
            "evidence_id": item.get("id"),
            "assumption_id": assumption.get("id"),
            "statement": assumption.get("statement"),
            **judgment,
        }
        ranked.append((weight, payload))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _weight, item in ranked[:limit]]


def hard_opposing_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in links
        if item.get("direction") == "oppose" and item.get("relevance") == "direct" and item.get("strength") in {"strong", "moderate"}
    ]
