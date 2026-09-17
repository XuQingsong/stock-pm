"""Generic extractors for growth, guidance, and management commitments.

Patterns are about document language, never a specific issuer.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from typing import Any


COMMITMENT_PATTERNS = (
    re.compile(
        r"(long[- ]term|multi-year|by\s+FY?\s*20\d{2}|over the next \d+ years).{0,160}"
        r"(target|goal|committed|capacity|revenue|customer|pipeline|design[- ]win)",
        re.I | re.S,
    ),
    re.compile(
        r"(capacity|output|production|throughput).{0,80}"
        r"(\d[\d,\.]*)\s*(gw|gigawatt|mw|units|wafers?)",
        re.I | re.S,
    ),
    re.compile(
        r"(\bai\b|asic|custom silicon|accelerat\w*|data[- ]center|optical|hyperscaler).{0,100}"
        r"(growth|demand|revenue|capacity|ramp)",
        re.I | re.S,
    ),
    re.compile(
        r"(we (?:are|remain) (?:on track|committed)|our (?:target|goal|commitment)).{0,180}"
        r"(revenue|capacity|customer|production|capex|growth)",
        re.I | re.S,
    ),
    re.compile(
        r"(production|capex|oil|gas|barrel|volume).{0,100}"
        r"(guidance|target|outlook|plan|commit)",
        re.I | re.S,
    ),
)

GUIDANCE_PATTERNS = (
    re.compile(r"(raise[sd]?|increas(?:e|ed)|lifted|upward).{0,48}guidance", re.I | re.S),
    re.compile(r"(lower(?:ed)?|cut|reduc(?:e|ed)|downward).{0,48}guidance", re.I | re.S),
    re.compile(r"guidance.{0,48}(raise[sd]?|lower(?:ed)?|unchanged|maintain|reaffirm)", re.I | re.S),
    re.compile(
        r"(full[- ]year|next quarter|outlook|expect(?:s|ed)?).{0,80}(revenue|eps|margin).{0,40}(\$|\d)",
        re.I | re.S,
    ),
    re.compile(
        r"(?:the company|we|management)\s+expects?\s+[^\n.]{10,240}",
        re.I,
    ),
    re.compile(
        r"(?:revenue|net revenue|sales)\s+(?:is|are)\s+expected\s+to\s+(?:be|range)[^\n.]{5,180}",
        re.I,
    ),
    re.compile(
        r"(?:expects?|guides?|guided|outlook)\s+[^\n.]{0,80}(?:revenue|margin|eps)[^\n.]{0,140}",
        re.I,
    ),
    re.compile(
        r"adjusted\s+(?:ebitda|gross|operating)?\s*margin[^\n.]{0,140}",
        re.I,
    ),
)

COMMITMENT_PATTERNS = COMMITMENT_PATTERNS + (
    re.compile(
        r"(?:over the next|in the next|during the next)\s+\d+\s+years?[^\n.]{0,220}",
        re.I,
    ),
    re.compile(
        r"(?:customer|hyperscal\w*|client)\s+[^\n.]{0,80}(?:deploy|ramp|capacity|demand|scale)[^\n.]{0,120}",
        re.I,
    ),
    re.compile(
        r"(?:on track|remain committed|targeting)\s+[^\n.]{0,160}(?:revenue|capacity|customer|growth|deploy|margin|production)",
        re.I,
    ),
)

TASK_SOURCE_TYPES = (
    "template_seed",
    "evidence_discovered",
    "assumption_gap",
    "agent_followup",
    "pm_request",
)

OFFICIAL_SOURCE_TYPES = (
    "earnings_release",
    "sec_filing",
    "transcript",
    "investor_presentation",
    "conference_remarks",
    "press_release",
    "official_document",
)

NEWS_SOURCE_TYPES = ("news", "headline", "news_discovery")

BOILERPLATE_SKIP = re.compile(
    r"(forward[- ]looking|could cause actual|no assurance|"
    r"slow or unsuccessful return|expansion of our business strategy|"
    r"incorporated by reference|furnished pursuant|"
    r"long[- ]term debt|other long[- ]term liabilities|total liabilities|"
    r"accelerated filer|emerging growth|stockholders.? equity|"
    r"check the appropriate box|not indicative of revenue|"
    r"account for a contract with a customer|"
    r"revenue from contracts with customers|"
    r"both parties have approved the contract)",
    re.I,
)

RISK_FACTOR_LANGUAGE = re.compile(
    r"(risk factors?|cautionary statement|forward[- ]looking statements?|"
    r"could cause actual results|these trends to intensify|"
    r"may (?:materially )?(?:adversely|negatively) (?:impact|affect)|"
    r"materially negatively impact|no assurance that|"
    r"uncertaint(?:y|ies) inherent|cannot be predicted|"
    r"deferred revenue|unearned revenue|contract liabilit)",
    re.I,
)

OPERATING_GUIDANCE_MARKERS = re.compile(
    r"\b(guidance|outlook|guide[ds]?|guided|"
    r"(?:net )?revenue.{0,40}(?:range|between|to be)|"
    r"eps|gross margin|operating margin|operating income|"
    r"opex|operating expense|tax rate|capex|capital expend|"
    r"product.{0,20}outlook|segment.{0,20}outlook)\b",
    re.I,
)

GUIDANCE_SOURCE_PRIORITY = (
    "earnings_release",
    "exhibit",
    "transcript",
    "investor_presentation",
    "press_release",
    "8-k",
    "8k",
)

CONCLUSION_MARKERS = re.compile(
    r"\b(buy|sell|overweight|underweight|price target|fair value|undervalued|overvalued|accumulate|priced[_\s-]*in)\b",
    re.I,
)

PRICED_IN_MARKERS = re.compile(r"priced[_\s-]*in", re.I)

INDUSTRY_PATTERNS = (
    re.compile(
        r"(customer|client|hyperscal\w*).{0,120}(capex|capital expend|capital spend|deploy|demand|forecast|commit)",
        re.I | re.S,
    ),
    re.compile(
        r"(capex|capital expend|capital spend).{0,140}(data[- ]center|customer|ai|demand|increase|raise|plan)",
        re.I | re.S,
    ),
    re.compile(r"(market share|share of (?:the )?market).{0,100}(\d|percent|%|leader|compet)", re.I | re.S),
    re.compile(
        r"(competitor|competition|competitive).{0,140}(share|price|product|customer|response|displace)",
        re.I | re.S,
    ),
    re.compile(
        r"(supply|foundry|packag\w*|capacity|wafer|production).{0,140}"
        r"(support|constrain|ramp|online|agreement|lock|enough|insufficient)",
        re.I | re.S,
    ),
    re.compile(
        r"(data[- ]center|power|electricit\w*|grid).{0,120}(capacity|constrain|deploy|build|available)",
        re.I | re.S,
    ),
    re.compile(
        r"(long[- ]term|multi-year|supply).{0,80}(agreement|contract|commit|purchase)",
        re.I | re.S,
    ),
    re.compile(
        r"(custom silicon|asic|tpu|accelerat\w*|xpu).{0,160}"
        r"(deploy|capex|cluster|rack|capacity|purchase|order|guidance)",
        re.I | re.S,
    ),
    re.compile(
        r"(capital expenditure|capex).{0,100}(guidance|outlook|increase|decrease|expect|plan)",
        re.I | re.S,
    ),
)

RISK_PATTERNS = (
    re.compile(
        r"(largest|single|one|top)\s+customer.{0,100}(\d[\d\.]*)\s*(%|percent)",
        re.I | re.S,
    ),
    re.compile(r"(customer concentration|concentrated (?:customer|revenue)).{0,120}", re.I | re.S),
    re.compile(
        r"(pull[- ]in|inventory build|channel fill|one[- ]off|temporary).{0,100}(demand|revenue|growth)",
        re.I | re.S,
    ),
    re.compile(
        r"\b(delay(?:ed|s)?|miss(?:ed|es)?|shortfall|push[- ]out|slip(?:ped|page)?)\b.{0,90}"
        r"(deploy|ramp|revenue|guidanc|production|project)",
        re.I | re.S,
    ),
    re.compile(r"(margin|gross margin).{0,80}(compress|decline|pressure|mix|erosion)", re.I | re.S),
    re.compile(r"(execution).{0,80}(risk|depend|delay|ramp|uncertain)", re.I | re.S),
    re.compile(r"(commodity|price) (?:cycle|volatility|decline).{0,80}(demand|cash|margin|volume)", re.I | re.S),
)


def to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round(100.0 * (new / old - 1.0), 2)


def yoy_from_quarters(rows: list[dict[str, Any]], field: str) -> float | None:
    latest = next((row for row in rows if to_number(row.get(field)) is not None), None)
    if not latest:
        return None
    latest_end = str(latest.get("period_end") or "")[:10]
    try:
        latest_day = date_cls.fromisoformat(latest_end) if latest_end else None
    except ValueError:
        latest_day = None
    if latest_day:
        for row in rows:
            if row is latest:
                continue
            end = str(row.get("period_end") or "")[:10]
            try:
                other = date_cls.fromisoformat(end) if end else None
            except ValueError:
                other = None
            if other and 340 <= (latest_day - other).days <= 390:
                yoy = pct_change(to_number(latest.get(field)), to_number(row.get(field)))
                if yoy is not None:
                    return yoy
    fy = latest.get("fiscal_year")
    fp = str(latest.get("fiscal_period") or "")
    if fy and fp:
        for row in rows:
            if row is latest:
                continue
            if row.get("fiscal_year") == fy - 1 and str(row.get("fiscal_period") or "") == fp:
                yoy = pct_change(to_number(latest.get(field)), to_number(row.get(field)))
                if yoy is not None:
                    return yoy
    return None


def beat_label(actual: float | None, estimate: float | None) -> str | None:
    if actual is None or estimate is None:
        return None
    if actual > estimate:
        return "beat"
    if actual < estimate:
        return "miss"
    return "inline"


def _clean_span(text: str, limit: int = 280) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:limit]


def _scan(patterns: tuple[re.Pattern[str], ...], text: str, *, kind: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            quote = _clean_span(match.group(0))
            key = quote.lower()
            if len(quote) < 28 or key in seen:
                continue
            if BOILERPLATE_SKIP.search(quote):
                continue
            seen.add(key)
            found.append({"kind": kind, "quote": quote})
    return found


def extract_commitments(text: str) -> list[dict[str, str]]:
    return _scan(COMMITMENT_PATTERNS, text, kind="management_commitment")


def is_operating_guidance(text: str, *, source_type: str | None = None) -> bool:
    quote = str(text or "").strip()
    if len(quote) < 28:
        return False
    if RISK_FACTOR_LANGUAGE.search(quote) or BOILERPLATE_SKIP.search(quote):
        return False
    if not OPERATING_GUIDANCE_MARKERS.search(quote):
        return False
    blob = f"{source_type or ''} {quote}".lower()
    if "risk factor" in blob:
        return False
    return True


def extract_guidance_mentions(text: str) -> list[dict[str, str]]:
    items = _scan(GUIDANCE_PATTERNS, text, kind="guidance")
    kept: list[dict[str, str]] = []
    for item in items:
        quote = item["quote"]
        if not is_operating_guidance(quote):
            continue
        lowered = quote.lower()
        if re.search(r"raise|increas|lifted|upward", lowered):
            item["move"] = "raised"
        elif re.search(r"lower|cut|reduc|downward", lowered):
            item["move"] = "lowered"
        elif re.search(r"unchanged|maintain|reaffirm", lowered):
            item["move"] = "maintained"
        else:
            item["move"] = "stated"
        kept.append(item)
    return kept


def extract_guidance_from_official_text(text: str) -> list[dict[str, str]]:
    """Guidance language from earnings releases and filings, not only transcripts."""
    return extract_guidance_mentions(text)


def extract_commitments_from_official_text(text: str) -> list[dict[str, str]]:
    return extract_commitments(text)


def followups_from_claim(quote: str) -> list[dict[str, str]]:
    """Dynamic follow-ups from a specific claim. Generic questions, claim-triggered."""
    hay = str(quote or "").lower()
    items: list[dict[str, str]] = []

    def add(title: str, required: str) -> None:
        key = title.lower()
        if any(item["title"].lower() == key for item in items):
            return
        items.append({"title": title, "required_data": required, "quote": _clean_span(quote, 240)})

    if any(token in hay for token in ("customer", "hyperscal", "client", "deploy")):
        add("Which customers are included in the stated deployment or demand claim?", "customers")
        add("Is the stated customer activity contracted, or still a plan?", "contract_vs_plan")
        add("What is the stated timing, and is related infrastructure already under construction?", "deployment_timing")
        if any(token in hay for token in ("data center", "deploy", "capacity", "power", "electric")):
            add("Is power or site capacity a constraint on the stated deployment?", "power_capacity")
    if any(token in hay for token in ("capacity", "wafer", "foundry", "packag", "supply", "production")):
        add("Is the supply needed for the stated plan already locked in with producers?", "supply_lock_in")
        add("What capacity additions are required, and when do they come online?", "capacity_timing")
    if any(token in hay for token in ("guid", "expect", "outlook")) and any(
        token in hay for token in ("revenue", "margin", "eps", "sales")
    ):
        add("What demand and mix assumptions sit underneath the stated outlook?", "guidance_assumptions")
        add("What would cause the stated outlook to be missed?", "guidance_miss_risk")
    if any(token in hay for token in ("ai", "accelerat", "data center", "semiconductor")) and any(
        token in hay for token in ("growth", "demand", "revenue", "ramp")
    ):
        add("Which end markets and customers drive the stated growth claim?", "end_markets")
        add("Is the stated demand confirmed by customer public commentary?", "customer_confirmation")
    if any(token in hay for token in ("margin", "ebitda")):
        add("What mix and cost items have to hold for the stated margin to be delivered?", "margin_drivers")
    return items[:8]


def guidance_move_from_history(rows: list[dict[str, Any]]) -> str | None:
    moves = [str(row.get("move") or "").lower() for row in rows if row.get("move")]
    if not moves:
        return None
    return moves[0]


def net_margin(revenue: float | None, earnings: float | None) -> float | None:
    if revenue in (None, 0) or earnings is None:
        return None
    return round(100.0 * (earnings / revenue), 2)


def nested_get(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_present(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if payload.get(name) not in (None, "", []):
            return payload.get(name)
    return None


def transcript_materials(pack: dict[str, Any]) -> str:
    chunks: list[str] = []
    profile = pack.get("company_profile") or {}
    for item in profile.get("transcripts") or []:
        chunks.append(str(item.get("text") or ""))
        for excerpt in item.get("excerpts") or []:
            if isinstance(excerpt, dict):
                chunks.append(str(excerpt.get("text") or excerpt.get("excerpt") or excerpt.get("content") or ""))
            else:
                chunks.append(str(excerpt))
    for row in pack.get("earnings_history") or []:
        chunks.append(str(row.get("transcript_text") or ""))
        for excerpt in row.get("transcript_excerpts") or []:
            if isinstance(excerpt, dict):
                chunks.append(str(excerpt.get("text") or excerpt.get("excerpt") or excerpt.get("content") or ""))
            else:
                chunks.append(str(excerpt))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def has_transcript_source(pack: dict[str, Any]) -> bool:
    return bool(transcript_materials(pack).strip())


def official_documents(pack: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in pack.get("official_documents") or []:
        if isinstance(item, dict):
            rows.append(item)
    profile = pack.get("company_profile") or {}
    for item in profile.get("official_documents") or []:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def official_materials(pack: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in official_documents(pack):
        chunks.append(str(item.get("text") or item.get("body") or item.get("excerpt") or ""))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def has_official_source(pack: dict[str, Any]) -> bool:
    return bool(official_materials(pack).strip())


def materials_text(pack: dict[str, Any]) -> str:
    """Transcripts + official documents + stored guidance quotes. News titles are excluded."""
    chunks: list[str] = [transcript_materials(pack), official_materials(pack)]
    for row in pack.get("guidance_history") or []:
        chunks.append(" ".join(str(row.get(key) or "") for key in ("text", "quote", "summary")))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def source_type_for_document(row: dict[str, Any] | None) -> str:
    payload = row or {}
    explicit = str(payload.get("source_type") or payload.get("doc_type") or "").strip()
    mapping = {
        "earnings_release": "earnings_release",
        "exhibit": "earnings_release",
        "filing": "sec_filing",
        "sec_filing": "sec_filing",
        "transcript": "transcript",
        "investor_presentation": "investor_presentation",
        "prepared_remarks": "conference_remarks",
        "conference_remarks": "conference_remarks",
        "press_release": "press_release",
        "guidance": "earnings_release",
        "web_search": "web_search",
    }
    if explicit in mapping:
        return mapping[explicit]
    source = str(payload.get("source") or payload.get("source_provider") or "").lower()
    if "transcript" in source:
        return "transcript"
    if "sec" in source or "8-k" in source or "10-q" in source or "10-k" in source:
        return "sec_filing"
    if "press" in source:
        return "press_release"
    return "official_document"


def has_conclusion_language(text: str) -> bool:
    return bool(CONCLUSION_MARKERS.search(text or ""))


def has_priced_in_language(text: str) -> bool:
    return bool(PRICED_IN_MARKERS.search(text or ""))


def extract_industry_mentions(text: str) -> list[dict[str, str]]:
    return _scan(INDUSTRY_PATTERNS, text, kind="industry")


def extract_risk_mentions(text: str) -> list[dict[str, str]]:
    return _scan(RISK_PATTERNS, text, kind="risk")
