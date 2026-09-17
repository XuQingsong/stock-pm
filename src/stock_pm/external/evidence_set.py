"""Build a balanced, fresh Evidence Set for Brain. Quality filter stays; ranking is not tier-only."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from stock_pm.research.llm_reason import compact_text

from .quality import source_tier
from .select import slim_fact


COUNTER_MARKERS = re.compile(
    r"\b(risk|delay|shortage|cut|slowdown|weak|decline|miss|cancel|constraint|"
    r"headwind|tariff|ban|lawsuit|downgrade|warning|investigation)\b",
    re.I,
)
LEAD_MARKERS = re.compile(
    r"\b(customer|supplier|order|contract|award|design.?win|delay|shortage|"
    r"lawsuit|recall|ban|tariff|guidance cut|downgrade|1\.6t|800g|cpo|"
    r"new product|cancellation|push.?out)\b",
    re.I,
)
_QWORD = {
    "first": 1,
    "1st": 1,
    "q1": 1,
    "1q": 1,
    "second": 2,
    "2nd": 2,
    "q2": 2,
    "2q": 2,
    "third": 3,
    "3rd": 3,
    "q3": 3,
    "3q": 3,
    "fourth": 4,
    "4th": 4,
    "q4": 4,
    "4q": 4,
}
_METRIC_PATTERNS = (
    ("guidance", re.compile(r"\b(guid(ed|ance)|outlook|forecast)\b", re.I)),
    ("revenue", re.compile(r"\b(revenue|net sales|net revenue)\b", re.I)),
    ("eps", re.compile(r"\b(eps|earnings per share|diluted net income per share)\b", re.I)),
    ("margin", re.compile(r"\b(gross margin|operating margin|gaap operating)\b", re.I)),
    ("cash_flow", re.compile(r"\b(free cash flow|operating cash flow|cash from operations)\b", re.I)),
    ("dividend", re.compile(r"\bdividend\b", re.I)),
    ("product", re.compile(r"\b(iphone|mac|watch|airpods|asic|tpu|800g|1\.6t|cpo|transceiver)\b", re.I)),
    ("demand", re.compile(r"\b(demand|capex|hyperscaler|customer|order)\b", re.I)),
)
_MONTH_QUARTER = re.compile(r"\b(march|june|september|december)\s+quarter\b", re.I)
_MONTH_TO_Q = {"march": 2, "june": 3, "september": 4, "december": 1}
_PERIOD = re.compile(
    r"(?:(?:fiscal\s+)?q([1-4])\s*(?:fy)?\s*((?:20)?\d{2}))|"
    r"(?:q([1-4])\s*fy\s*((?:20)?\d{2}))|"
    r"(?:([1-4])q\s*((?:20)?\d{2}))|"
    r"(?:fiscal(?:\s+year)?\s*((?:20)?\d{2})\s+(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter)|"
    r"((?:first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+of)?(?:\s+fiscal(?:\s+year)?)?\s*((?:20)?\d{2}))",
    re.I,
)


def _tier(row: dict[str, Any]) -> int:
    return int(row.get("source_tier") or source_tier(row.get("source_url") or row.get("url")) or 5)


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    value = int(raw)
    if value < 100:
        return 2000 + value
    return value


def parse_fiscal_period(text: Any, *, source_time: Any = None) -> str | None:
    blob = str(text or "")
    match = _PERIOD.search(blob)
    if not match:
        month = _MONTH_QUARTER.search(blob)
        if not month:
            return None
        quarter = _MONTH_TO_Q[month.group(1).lower()]
        year = None
        year_match = re.search(r"\b(20\d{2})\b", blob)
        if year_match:
            year = int(year_match.group(1))
        elif str(source_time or "")[:4].isdigit():
            year = int(str(source_time)[:4])
        if not year:
            return None
        if quarter == 1:
            year += 1
        return f"{year}Q{quarter}"
    groups = match.groups()
    if groups[0] and groups[1]:
        return f"{_year(groups[1])}Q{int(groups[0])}"
    if groups[2] and groups[3]:
        return f"{_year(groups[3])}Q{int(groups[2])}"
    if groups[4] and groups[5]:
        return f"{_year(groups[5])}Q{int(groups[4])}"
    if groups[6] and groups[7]:
        return f"{_year(groups[6])}Q{_QWORD.get(groups[7].lower())}"
    if groups[8] and groups[9]:
        word = groups[8].split()[0].lower()
        return f"{_year(groups[9])}Q{_QWORD.get(word)}"
    return None


def parse_metric(text: Any) -> str:
    blob = str(text or "")
    for name, pattern in _METRIC_PATTERNS:
        if pattern.search(blob):
            return name
    return "other"


def _ordinal(period: str | None) -> int:
    if not period or len(period) < 6:
        return 0
    try:
        return int(period[:4]) * 10 + int(period[-1])
    except ValueError:
        return 0


def _date_ordinal(value: Any) -> int:
    text = str(value or "")[:10]
    if not text:
        return 0
    try:
        return datetime.strptime(text, "%Y-%m-%d").toordinal()
    except ValueError:
        return 0


def _class_for(row: dict[str, Any], doc: dict[str, Any] | None) -> str:
    tier = _tier(row)
    qtype = str((doc or {}).get("query_type") or row.get("query_type") or "")
    entity = str(((doc or {}).get("metadata") or {}).get("entity") or row.get("entity") or "")
    if tier >= 5:
        return "community"
    if qtype in {"related_entity", "customer", "supplier", "industry_news"} or entity:
        return "industry"
    if tier == 2:
        return "independent"
    if tier <= 1 or str(row.get("source_type") or "") in {"sec_filing", "official"}:
        return "primary"
    if tier == 3 or str((doc or {}).get("source_type") or "") == "industry":
        return "industry"
    return "community"


def annotate_fact(row: dict[str, Any], *, docs_by_id: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    item = dict(row)
    doc = (docs_by_id or {}).get(str(row.get("document_id") or ""))
    blob = f"{row.get('fact') or ''} {row.get('excerpt') or ''} {(doc or {}).get('title') or ''}"
    item["metric"] = parse_metric(blob)
    item["fiscal_period"] = parse_fiscal_period(blob, source_time=item.get("effective_date")) or parse_fiscal_period(
        (doc or {}).get("title"), source_time=item.get("effective_date")
    )
    item["evidence_class"] = _class_for(item, doc)
    item["is_counter"] = bool(COUNTER_MARKERS.search(str(row.get("fact") or "")))
    item["effective_date"] = str(row.get("source_time") or (doc or {}).get("published_at") or "")[:10]
    if item["is_counter"]:
        item["bucket"] = "counter"
    else:
        item["bucket"] = item["evidence_class"]
    return item


def _event_key(row: dict[str, Any]) -> str:
    period = row.get("fiscal_period") or (row.get("effective_date") or "")[:7]
    return f"{row.get('metric') or 'other'}|{period}"


def _materiality(row: dict[str, Any]) -> float:
    declared = str(row.get("materiality") or "").lower()
    if declared == "high":
        return 1.0
    if declared == "low":
        return 0.4
    blob = str(row.get("fact") or "")
    if re.search(r"(\$|billion|guidance|outlook)", blob, re.I):
        return 1.0
    if declared == "medium":
        return 0.7
    return 0.7


def _relevance(row: dict[str, Any], claims: list[dict[str, Any]]) -> float:
    if not claims:
        return 0.7
    blob = f"{row.get('fact') or ''} {row.get('claim_title') or ''}".lower()
    best = 0.35
    for claim in claims:
        title = str(claim.get("title") or claim.get("claim_title") or "").lower()
        statement = str(claim.get("statement") or "").lower()
        if title and title[:24] in blob:
            best = max(best, 1.0)
        elif any(token and token in blob for token in title.split()[:4] if len(token) > 3):
            best = max(best, 0.8)
        elif any(token and token in blob for token in statement.split()[:6] if len(token) > 4):
            best = max(best, 0.65)
    return best


def _freshness(row: dict[str, Any], latest_by_metric: dict[str, int]) -> float:
    period = _ordinal(row.get("fiscal_period"))
    latest = latest_by_metric.get(str(row.get("metric") or "other")) or 0
    if period and latest:
        if period >= latest:
            return 1.0
        if period >= latest - 1:
            return 0.45
        return 0.2
    date = _date_ordinal(row.get("effective_date"))
    if not date:
        return 0.3
    # Rough: last ~100 days is current for dated-only facts.
    today = datetime.now(timezone.utc).toordinal()
    age = today - date
    if age <= 100:
        return 0.9
    if age <= 200:
        return 0.5
    return 0.25


def _quality(row: dict[str, Any]) -> float:
    tier = _tier(row)
    if tier <= 1:
        return 1.0
    if tier == 2:
        return 0.9
    if tier == 3:
        return 0.7
    return 0.2


def _grade(count: int, *, good: int = 2, partial: int = 1) -> str:
    if count >= good:
        return "Good"
    if count >= partial:
        return "Partial"
    return "Missing"


def _freshness_grade(rows: list[dict[str, Any]]) -> str:
    if any(row.get("role") == "current" and row.get("fiscal_period") for row in rows):
        return "Good"
    if any(row.get("role") == "current" for row in rows):
        return "Partial"
    if rows:
        return "Poor"
    return "Poor"


def _quality_grade(*, primary: int, independent: int) -> str:
    if primary and independent:
        return "Good"
    if primary:
        return "Partial"
    return "Poor"


def collect_research_leads(
    archived: list[dict[str, Any]],
    *,
    ticker: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for row in archived:
        tier = int(row.get("source_tier") or 9)
        if tier < 4:
            continue
        blob = f"{row.get('title') or ''} {row.get('clean_text') or ''}"[:800]
        if not LEAD_MARKERS.search(blob):
            continue
        snippet = compact_text(blob, 180)
        query = f'{ticker} {compact_text(row.get("title") or snippet, 80)} (8-K OR 10-Q OR "press release" OR investor)'
        leads.append(
            {
                "title": row.get("title"),
                "url": row.get("url"),
                "source_tier": tier,
                "source_domain": row.get("source_domain"),
                "why": "high-novelty/material clue from aggregator or community; not Evidence",
                "snippet": snippet,
                "verification_query": query,
                "status": "pending_verification",
            }
        )
        if len(leads) >= limit:
            break
    return leads


def apply_independence_to_claims(
    claims: list[dict[str, Any]],
    coverage_matrix: list[dict[str, Any]],
    *,
    ticker_independent: str | None = None,
) -> list[dict[str, Any]]:
    by_title = {str(row.get("claim_title") or "").lower(): row for row in coverage_matrix}
    out: list[dict[str, Any]] = []
    for claim in claims:
        item = dict(claim)
        matrix = by_title.get(str(claim.get("title") or "").lower())
        independent = (matrix or {}).get("independent") or ticker_independent or "Missing"
        primary = (matrix or {}).get("primary") or "Missing"
        item["evidence_coverage"] = matrix
        if independent == "Missing" and primary in {"Good", "Partial"}:
            item["evidence_confidence"] = "medium"
            item["independence_gap"] = "issuer-supported but independently unconfirmed"
            item["independent_validation"] = "Missing"
            if item.get("confidence") == "high":
                item["confidence"] = "medium"
            if item.get("status") == "strongly_supported":
                item["status"] = "partially_supported"
        elif independent in {"Good", "Partial"}:
            item["evidence_confidence"] = item.get("confidence") or "medium"
            item["independent_validation"] = independent
            item["independence_gap"] = None
        else:
            item["evidence_confidence"] = "low"
            item["independent_validation"] = independent
            item["independence_gap"] = "independent validation missing"
            if item.get("confidence") == "high":
                item["confidence"] = "medium"
        out.append(item)
    return out


def build_evidence_set(
    retained: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    *,
    archived: list[dict[str, Any]] | None = None,
    ticker: str = "",
    research_leads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    docs_by_id = {str(row.get("document_id") or ""): row for row in retained}
    annotated = [annotate_fact(row, docs_by_id=docs_by_id) for row in facts]
    latest_by_metric: dict[str, int] = {}
    latest_results = 0
    for row in annotated:
        metric = str(row.get("metric") or "other")
        period = _ordinal(row.get("fiscal_period"))
        latest_by_metric[metric] = max(latest_by_metric.get(metric) or 0, period)
        if metric != "guidance":
            latest_results = max(latest_results, period)
    for row in annotated:
        metric = str(row.get("metric") or "other")
        period = _ordinal(row.get("fiscal_period"))
        if period:
            floor = latest_results or latest_by_metric.get(metric) or 0
            row["role"] = "current" if period >= floor else "historical"
        else:
            age = datetime.now(timezone.utc).toordinal() - _date_ordinal(row.get("effective_date"))
            row["role"] = "current" if 0 <= age <= 120 else "historical"
        novelty = 1.0
        row["priority"] = round(
            _materiality(row)
            * _relevance(row, claims)
            * _freshness(row, latest_by_metric)
            * _quality(row)
            * novelty,
            4,
        )
    annotated.sort(key=lambda row: (0 if row.get("role") == "current" else 1, -float(row.get("priority") or 0)))
    seen_events: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in annotated:
        key = _event_key(row)
        if key in seen_events and row.get("role") == "current":
            row["priority"] = round(float(row.get("priority") or 0) * 0.15, 4)
            row["duplicate_event"] = True
            continue
        if row.get("role") == "current":
            seen_events.add(key)
        unique.append(row)

    def _take(rows: list[dict[str, Any]], pred, cap: int) -> list[dict[str, Any]]:
        out = [row for row in rows if pred(row) and row.get("role") == "current"]
        return out[:cap]

    current_operating = _take(
        unique,
        lambda row: row.get("bucket") == "primary" and row.get("metric") in {"revenue", "eps", "margin", "cash_flow", "guidance", "dividend", "product", "other"},
        8,
    )
    independent = _take(unique, lambda row: row.get("bucket") == "independent", 5)
    industry = _take(unique, lambda row: row.get("bucket") == "industry", 6)
    counter = _take(unique, lambda row: row.get("bucket") == "counter" or row.get("is_counter"), 4)
    community = [row for row in unique if row.get("bucket") == "community" and row.get("role") == "current"][:3]
    for row in community:
        row["signal_only"] = True
    historical = [row for row in unique if row.get("role") == "historical"][:8]
    top_facts = current_operating + independent + industry + counter + community
    selected_facts = top_facts + historical[:4]

    claims_unique: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for claim in claims:
        title = str(claim.get("title") or claim.get("claim_title") or "").strip().lower()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        claims_unique.append(claim)
    claims = claims_unique[:5]
    per_claim: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    for claim in claims[:5]:
        title = str(claim.get("title") or claim.get("claim_title") or "")
        related = [row for row in unique if title and title.lower()[:24] in f"{row.get('claim_title') or ''} {row.get('fact') or ''}".lower()]
        if not related:
            related = [row for row in unique if _relevance(row, [claim]) >= 0.65]
        if related:
            primary_rows = [row for row in related if row.get("evidence_class") == "primary" and not row.get("is_counter")]
            independent_rows = [row for row in related if row.get("evidence_class") == "independent"]
            industry_rows = [row for row in related if row.get("evidence_class") == "industry"]
            counter_rows = [row for row in related if row.get("is_counter") or row.get("bucket") == "counter"]
        else:
            primary_rows = list(current_operating)
            independent_rows = list(independent)
            industry_rows = list(industry)
            counter_rows = list(counter)
        missing: list[str] = []
        grades = {
            "primary": _grade(len(primary_rows)),
            "independent": _grade(len(independent_rows)),
            "industry": _grade(len(industry_rows)),
            "counter": _grade(len(counter_rows), good=1, partial=1),
            "freshness": _freshness_grade(related),
            "data_quality": _quality_grade(primary=len(primary_rows), independent=len(independent_rows)),
        }
        for key, label in (
            ("primary", "Primary Evidence"),
            ("independent", "Independent Evidence"),
            ("industry", "Industry / related-entity Evidence"),
            ("counter", "Counter Evidence"),
        ):
            if grades[key] == "Missing":
                missing.append(label)
        evidence_confidence = "high"
        independence_gap = None
        if grades["independent"] == "Missing" and grades["primary"] in {"Good", "Partial"}:
            evidence_confidence = "medium"
            independence_gap = "issuer-supported but independently unconfirmed"
        elif grades["primary"] == "Missing":
            evidence_confidence = "low"
        if grades["freshness"] == "Poor" or grades["data_quality"] == "Poor":
            evidence_confidence = "low" if evidence_confidence != "medium" else "medium"
        per_claim.append(
            {
                "claim_title": title,
                "primary": [slim_fact(row) | {"fiscal_period": row.get("fiscal_period"), "role": row.get("role")} for row in primary_rows[:4]],
                "independent": [slim_fact(row) | {"fiscal_period": row.get("fiscal_period"), "role": row.get("role")} for row in independent_rows[:3]],
                "industry": [slim_fact(row) | {"fiscal_period": row.get("fiscal_period"), "role": row.get("role")} for row in industry_rows[:3]],
                "counter": [slim_fact(row) | {"fiscal_period": row.get("fiscal_period"), "role": row.get("role")} for row in counter_rows[:3]],
                "missing_evidence_class": missing,
                "coverage": grades,
                "evidence_confidence": evidence_confidence,
                "independence_gap": independence_gap,
                "independent_validation": grades["independent"] if grades["independent"] != "Missing" else "Missing",
            }
        )
        matrix.append({"claim_title": title, **grades, "evidence_confidence": evidence_confidence, "independence_gap": independence_gap})

    ticker_independent = _grade(len(independent) + sum(1 for row in unique if row.get("evidence_class") == "independent"))
    if not claims:
        matrix.append(
            {
                "claim_title": ticker or "(ticker)",
                "primary": _grade(len(current_operating)),
                "independent": ticker_independent,
                "industry": _grade(len(industry)),
                "counter": _grade(len(counter), good=1, partial=1),
                "freshness": _freshness_grade(unique),
                "data_quality": _quality_grade(primary=len(current_operating), independent=len([row for row in unique if row.get("evidence_class") == "independent"])),
                "evidence_confidence": "medium" if ticker_independent == "Missing" else "high",
                "independence_gap": "issuer-supported but independently unconfirmed" if ticker_independent == "Missing" else None,
            }
        )

    leads = research_leads if research_leads is not None else collect_research_leads(archived or [], ticker=ticker)
    gaps: list[str] = []
    if ticker_independent == "Missing":
        gaps.append("Independent validation: Missing")
    if not current_operating:
        gaps.append("No current-period operating facts selected.")
    if not industry:
        gaps.append("Industry / related-entity evidence missing.")
    if not counter:
        gaps.append("Counter evidence missing.")

    def _pack(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            item = slim_fact(row)
            item.update(
                {
                    "metric": row.get("metric"),
                    "fiscal_period": row.get("fiscal_period"),
                    "role": row.get("role"),
                    "evidence_class": row.get("evidence_class"),
                    "priority": row.get("priority"),
                    "signal_only": row.get("signal_only"),
                }
            )
            out.append(item)
        return out

    brain_context = {
        "current_operating_facts": _pack(current_operating),
        "independent_confirmation": _pack(independent),
        "industry_related": _pack(industry),
        "counter_evidence": _pack(counter),
        "community_signals": _pack(community),
        "historical_trend_facts": _pack(historical),
        "missing_classes": [
            name
            for name, rows in (("independent", independent), ("industry", industry), ("counter", counter))
            if not rows
        ],
        "independent_validation": "Missing" if ticker_independent == "Missing" else ticker_independent,
    }
    return {
        "top_primary_facts": _pack(current_operating),
        "top_independent_evidence": _pack(independent),
        "top_industry_evidence": _pack(industry),
        "top_counter_evidence": _pack(counter),
        "top_community_signals": _pack(community),
        "historical_facts": _pack(historical),
        "top_10_facts": _pack(top_facts[:12]),
        "top_facts": _pack(top_facts),
        "open_gaps": gaps,
        "per_claim": per_claim,
        "coverage_matrix": matrix,
        "current_vs_historical": {
            "current": _pack(current_operating + independent + industry),
            "historical": _pack(historical),
        },
        "research_leads": leads,
        "verification_searches": [row for row in leads if row.get("verification_ran")],
        "tier45_leads_triggered": sum(1 for row in leads if row.get("verification_ran")),
        "brain_context": brain_context,
        "independent_validation": brain_context["independent_validation"],
        "selected_facts": selected_facts,
        "retained_docs": len(retained),
    }
