"""Deterministic Brain Integrity: evidence binding, status, identity, PM checks.

Does not call LLMs. External Intelligence is consumed, not rewritten.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from stock_pm.external.quality import TIER2_HOSTS, TIER4_HOSTS, TIER5_HOSTS, host_of, source_tier
from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import (
    CLAIM_DIMENSIONS,
    CLAIM_STATUSES,
    CLAIM_SUBJECTS,
    CONFIDENCE,
    EXTERNAL_VALIDATION_RELATIONSHIPS,
    HORIZONS,
    LIFECYCLES,
    MATCH_ACTIONS,
    SOURCE_RELATIONSHIPS,
    STRONG_LINK_QUALITY,
    WEAK_RELATIONSHIPS,
)


ISSUER_DOMAINS: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple.com",),
    "AVGO": ("broadcom.com",),
    "LITE": ("lumentum.com",),
    "ZZZT": ("example.com",),
}

RELATED_PRIMARY_DOMAINS: dict[str, tuple[str, ...]] = {
    "AAPL": ("tsmc.com", "foxconn.com", "honhai.com"),
    "AVGO": (
        "meta.com",
        "facebook.com",
        "google.com",
        "abc.xyz",
        "microsoft.com",
        "amazon.com",
        "nvidia.com",
        "openai.com",
    ),
    "LITE": ("coherent.com", "fabrinet.com", "ii-vi.com", "coherentcorp.com", "innolight.com", "nvidia.com"),
}

INDUSTRY_PEER_DOMAINS: dict[str, tuple[str, ...]] = {
    "AAPL": ("samsung.com", "google.com"),
    "AVGO": ("marvell.com", "qorvo.com", "skyworksinc.com"),
    "LITE": ("coherent.com", "fabrinet.com", "ii-vi.com", "coherentcorp.com"),
}

AGGREGATOR_HOSTS = TIER4_HOSTS + (
    "stockanalysis.com",
    "247wallst.com",
    "sagenoodle.com",
    "frontier.eninvs.com",
    "intickers.com",
    "everyticker.com",
    "kobaran.com",
    "macobserver.com",
    "trefis.com",
    "beancount.io",
    "financialmodelingprep.com",
    "alphavantage.co",
    "fmpcloud.io",
)

INDEPENDENT_HOSTS = TIER2_HOSTS

FACT_RESTATEMENT = re.compile(
    r"("
    r"\b(revenue|eps|earnings|sales|profit)\b.{0,40}\b(is|are|was|were|grew|rose|fell|increased|decreased)\b.{0,24}"
    r"(\d|\$|percent|%|growing|up|down|strong|higher|lower)"
    r"|"
    r"\b(gross|operating)\s+margin\b.{0,32}\b(expanded|improved|rose|fell|went)\b"
    r"|"
    r"\bpe ttm is\b|\bttm revenue of\b|\bsequential(?:ly)? revenue\b"
    r")",
    re.I,
)

NUMBER_TOKEN = re.compile(
    r"\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:%|b|bn|billion|million|m)\b|\b\d+\.\d+\b",
    re.I,
)

COUNTER_MARKERS = re.compile(
    r"\b(slowdown|cut|delay|shortage|miss|cancel|headwind|lawsuit|downgrade|"
    r"inventory|pricing pressure|share loss|displacement|push.?out|weak(er|ness)?|"
    r"constraint|tariff|ban|dilution|concentration)\b",
    re.I,
)

DEFAULT_COUNTER_QUERIES = {
    "revenue": [
        "{ticker} hyperscaler capex slowdown OR order pushout",
        "{ticker} customer concentration OR share loss OR custom silicon",
    ],
    "margin": [
        "{ticker} margin dilution OR mix pressure OR cost inflation",
        "{ticker} pricing pressure OR gross margin cut",
    ],
    "services": [
        "{ticker} App Store regulation OR DMA OR services growth slowdown",
        "{ticker} services margin compression",
    ],
    "optical": [
        "{ticker} optical inventory build OR pricing pressure",
        "{ticker} peer capacity expansion OR CPO displacement OR Coherent OR Fabrinet",
    ],
    "valuation": [
        "{ticker} valuation multiple compression OR growth deceleration",
        "{ticker} forward earnings miss OR guidance cut",
    ],
    "demand": [
        "{ticker} demand slowdown OR deployment delay OR power constraint",
        "{ticker} customer capex cut OR inventory digestion",
    ],
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _host(url: str | None) -> str:
    return host_of(url)


def _endswith_any(host: str, names: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith("." + item) for item in names)


def _norm_token(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "unspecified"


def make_claim_key(
    ticker: str,
    *,
    claim_subject: str | None,
    financial_driver: str | None,
    claim_dimension: str | None,
    time_horizon: str | None,
) -> str:
    blob = "|".join(
        [
            str(ticker or "").upper(),
            _norm_token(claim_subject),
            _norm_token(financial_driver),
            _norm_token(claim_dimension),
            _norm_token(time_horizon or "medium"),
        ]
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
    return f"bck_{digest}"


def derive_claim_identity(raw: dict[str, Any], *, ticker: str) -> dict[str, str]:
    subject = compact_text(raw.get("claim_subject") or "", 80)
    dimension = compact_text(raw.get("claim_dimension") or "", 80)
    driver = compact_text(raw.get("financial_driver") or "", 80)
    blob = f"{raw.get('title') or ''} {raw.get('statement') or ''} {driver} {subject} {dimension}".lower()
    generic_subjects = {
        "",
        "unspecified",
        _norm_token(ticker),
        "apple",
        "apple_inc",
        "broadcom",
        "lumentum",
        "company",
        "operating",
        "margin_profile",
        "lumentum_margin_quality",
        "lumentum_earnings_sensitivity",
    }
    allowed_subjects = set(CLAIM_SUBJECTS)
    if _norm_token(subject) not in allowed_subjects or _norm_token(subject) in generic_subjects:
        subject = ""
    if _norm_token(dimension) not in set(CLAIM_DIMENSIONS):
        dimension = ""
    if not subject:
        if any(token in blob for token in ("service", "app store", "installed base")):
            subject = "services_mix"
        elif any(token in blob for token in ("custom silicon", "xpu", "asic", "ai semiconductor", "ai compute")):
            subject = "ai_custom_silicon"
        elif any(token in blob for token in ("optical", "datacom", "transceiver", "cpo")):
            subject = "optical_demand"
        elif any(token in blob for token in ("iphone", "hardware", "product cycle", "foldable")):
            subject = "hardware_demand"
        elif any(token in blob for token in ("valuation", "pe ", "multiple", "forward")):
            subject = "valuation"
        elif "margin" in blob:
            subject = "margin_quality"
        elif any(token in blob for token in ("demand", "growth")):
            subject = "demand_duration"
        else:
            subject = _norm_token(raw.get("title") or "operating")[:40]
    if not dimension:
        if any(token in blob for token in ("durab", "sustain", "duration", "continue", "persist")):
            dimension = "growth_duration"
        elif any(token in blob for token in ("structural", "cyclical", "mix shift")):
            dimension = "structural_vs_cyclical"
        elif "concentration" in blob or "customer" in blob:
            dimension = "customer_concentration"
        elif "valuation" in blob or "multiple" in blob:
            dimension = "valuation_sensitivity"
        elif "margin" in blob:
            dimension = "margin_quality"
        else:
            dimension = "decision_variable"
    if "margin" in blob:
        driver = "margin"
    elif any(token in blob for token in ("valuation", "multiple", " pe", "pe ")):
        driver = "valuation"
    elif any(token in blob for token in ("demand", "unit", "volume")):
        driver = "demand"
    else:
        driver = "revenue"
    horizon = raw.get("time_horizon") if raw.get("time_horizon") in HORIZONS else "medium"
    return {
        "claim_subject": _norm_token(subject),
        "claim_dimension": _norm_token(dimension),
        "financial_driver": compact_text(driver, 80) or "revenue",
        "time_horizon": str(horizon),
        "claim_key": make_claim_key(
            ticker,
            claim_subject=subject,
            financial_driver=driver,
            claim_dimension=dimension,
            time_horizon=horizon,
        ),
    }


def classify_source_relationship(
    ev: dict[str, Any] | None,
    *,
    ticker: str,
    related_entities: list[dict[str, Any]] | None = None,
) -> str:
    row = ev or {}
    raw = row.get("raw_reference") if isinstance(row.get("raw_reference"), dict) else {}
    stored = str(row.get("source_relationship") or raw.get("source_relationship") or "")
    if stored in SOURCE_RELATIONSHIPS:
        return stored
    url = str(row.get("source_url") or row.get("url") or "")
    host = _host(url)
    source = str(row.get("source") or raw.get("source_family") or "")
    source_type = str(row.get("source_type") or "")
    query_type = str(raw.get("query_type") or row.get("query_type") or "")
    entity = str(raw.get("entity") or "")
    blob = f"{url} {source} {source_type} {row.get('fact') or ''} {row.get('title') or ''}".lower()
    symbol = str(ticker or "").upper()
    issuer_hosts = ISSUER_DOMAINS.get(symbol, ())
    related_hosts = RELATED_PRIMARY_DOMAINS.get(symbol, ())
    peer_hosts = INDUSTRY_PEER_DOMAINS.get(symbol, ())
    extra_related: list[str] = []
    for item in related_entities or []:
        if isinstance(item, dict):
            extra_related.append(str(item.get("name") or "").lower())
            extra_related.append(str(item.get("domain") or "").lower())
    official_type = source_type in {"sec_filing", "filing", "earnings_release", "official_document", "exhibit", "official"}
    issuer_source = any(
        token in source.lower()
        for token in ("sec.companyfacts", "sec.exhibit", "sec.submissions", "sec.gov", "earnings_history", "issuer")
    )
    if _endswith_any(host, TIER5_HOSTS) or "reddit" in blob:
        return "community"
    if _endswith_any(host, AGGREGATOR_HOSTS) or any(
        token in source.lower() for token in ("alpha_vantage", "fmp", "fool", "zacks", "stockanalysis", "seekingalpha")
    ):
        if "sec.companyfacts" in source.lower() or (official_type and not host):
            return "issuer_primary"
        return "aggregator"
    if _endswith_any(host, independent_hosts()) or any(token in host for token in ("reuters.com", "bloomberg.com", "ft.com", "wsj.com")):
        return "independent_media"
    if _endswith_any(host, issuer_hosts) or host == "sec.gov" or host.endswith(".sec.gov"):
        related_hit = any(name and name in blob for name in extra_related if name and name not in {symbol.lower(), "apple", "broadcom", "lumentum"})
        if related_hit and not _endswith_any(host, issuer_hosts) and host not in {"sec.gov"} and not host.endswith(".sec.gov"):
            return "related_entity_primary"
        return "issuer_primary"
    if issuer_source or (official_type and not host):
        return "issuer_primary"
    if _endswith_any(host, related_hosts) or query_type in {"related_entity", "customer", "supplier"}:
        if official_type or _endswith_any(host, related_hosts) or "10-q" in blob or "10-k" in blob or "8-k" in blob:
            return "related_entity_primary"
        return "industry_peer"
    if _endswith_any(host, peer_hosts) or (entity and any(entity.lower() in name for name in extra_related if name)):
        return "industry_peer" if not official_type else "related_entity_primary"
    if query_type in {"industry_news"} or source_type in {"industry"}:
        return "industry_peer"
    if not host and int(row.get("source_tier") or source_tier(url, source=source) or 9) >= 4:
        return "aggregator"
    return "unknown"


def independent_hosts() -> tuple[str, ...]:
    return INDEPENDENT_HOSTS


def evidence_in_set_row(row: dict[str, Any], store_row: dict[str, Any]) -> bool:
    url = str(row.get("source_url") or row.get("url") or "")
    other = str(store_row.get("source_url") or "")
    if url and other and url.rstrip("/") == other.rstrip("/"):
        return True
    fact = str(row.get("fact") or "").strip().lower()
    other_fact = str(store_row.get("fact") or "").strip().lower()
    if fact and other_fact and (fact[:160] == other_fact[:160] or fact[:80] in other_fact):
        return True
    eid = str(row.get("id") or row.get("evidence_id") or "")
    return bool(eid and eid == str(store_row.get("id") or ""))


def _collect_set_facts(intel: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = (intel or {}).get("evidence_set") or (intel or {}).get("reasoning_context") or {}
    ctx = payload.get("brain_context") or {}
    rows: list[dict[str, Any]] = []
    for key in (
        "selected_facts",
        "top_facts",
        "top_10_facts",
        "top_primary_facts",
        "top_independent_evidence",
        "top_industry_evidence",
        "top_counter_evidence",
        "top_community_signals",
        "historical_facts",
    ):
        for row in payload.get(key) or []:
            if isinstance(row, dict):
                rows.append(row)
    for key in (
        "current_operating_facts",
        "independent_confirmation",
        "industry_related",
        "counter_evidence",
        "community_signals",
        "historical_trend_facts",
    ):
        for row in ctx.get(key) or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def freeze_evidence_set(
    *,
    ticker: str,
    intel: dict[str, Any] | None,
    store_evidence: list[dict[str, Any]],
    related_entities: list[dict[str, Any]] | None = None,
    research_leads: list[dict[str, Any]] | None = None,
    extra_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    set_id = new_id("bes")
    intel_facts = _collect_set_facts(intel)
    store_rows = list(store_evidence or [])
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(row: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
        eid = str(row.get("id") or "")
        if not eid:
            return None
        if eid in seen:
            return None
        rel = classify_source_relationship(row, ticker=symbol, related_entities=related_entities)
        annotated = dict(row)
        annotated["source_relationship"] = rel
        annotated["source_tier"] = row.get("source_tier") or source_tier(row.get("source_url"), source=row.get("source"))
        seen.add(eid)
        selected.append(annotated)
        return annotated

    matched_store: list[dict[str, Any]] = []
    if intel_facts:
        for fact in intel_facts:
            hit = next((row for row in store_rows if evidence_in_set_row(fact, row)), None)
            if hit:
                matched_store.append(hit)
    if not matched_store:
        for row in store_rows:
            rel = classify_source_relationship(row, ticker=symbol, related_entities=related_entities)
            if rel in {"issuer_primary", "related_entity_primary", "independent_media", "industry_peer"}:
                matched_store.append(row)
    for row in extra_rows or []:
        if isinstance(row, dict) and row.get("id"):
            matched_store.append(row)
    for row in matched_store:
        _take(row)

    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in (
        "current_operating",
        "historical",
        "issuer_primary",
        "related_entity_primary",
        "independent_media",
        "industry_peer",
        "counter_evidence",
        "community_signal",
        "research_lead",
        "aggregator",
        "unknown",
    )}
    for row in selected:
        rel = row.get("source_relationship") or "unknown"
        blob = f"{row.get('fact') or ''} {row.get('excerpt') or ''}"
        if COUNTER_MARKERS.search(blob):
            buckets["counter_evidence"].append(row)
        if rel == "issuer_primary":
            buckets["issuer_primary"].append(row)
            buckets["current_operating"].append(row)
        elif rel == "related_entity_primary":
            buckets["related_entity_primary"].append(row)
        elif rel == "independent_media":
            buckets["independent_media"].append(row)
        elif rel == "industry_peer":
            buckets["industry_peer"].append(row)
        elif rel == "community":
            buckets["community_signal"].append(row)
        elif rel == "aggregator":
            buckets["aggregator"].append(row)
            buckets["community_signal"].append(row)
        else:
            buckets["unknown"].append(row)
        stamp = str(row.get("source_time") or "")[:10]
        if stamp and stamp < "2025-10-01":
            buckets["historical"].append(row)

    leads = list(research_leads or ((intel or {}).get("evidence_set") or {}).get("research_leads") or [])
    for lead in leads:
        if isinstance(lead, dict):
            buckets["research_lead"].append(lead)

    reasoning_rows = [
        row
        for row in selected
        if row.get("source_relationship") != "research_lead"
    ]
    allowed = {str(row.get("id")) for row in reasoning_rows if row.get("id")}
    return {
        "evidence_set_id": set_id,
        "ticker": symbol,
        "buckets": {key: [str(row.get("id") or row.get("url") or "") for row in rows] for key, rows in buckets.items()},
        "rows": selected,
        "reasoning_rows": reasoning_rows,
        "reasoning_allowed_ids": sorted(allowed),
        "research_leads": leads,
        "related_entities": related_entities or [],
        "created_at": _now().isoformat(),
    }


def reject_unknown_ids(values: Any, allowed: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    rejected: list[str] = []
    for item in values or []:
        key = str(item or "").strip()
        if not key:
            continue
        if key in allowed:
            if key not in kept:
                kept.append(key)
        else:
            if key not in rejected:
                rejected.append(key)
    return kept, rejected


def is_fact_restatement(statement: str) -> bool:
    text = str(statement or "").strip()
    if not text:
        return True
    return bool(FACT_RESTATEMENT.search(text))


def extract_factual_tokens(statement: str) -> list[str]:
    out: list[str] = []
    for match in NUMBER_TOKEN.finditer(str(statement or "")):
        token = re.sub(r"[,\s]", "", match.group(0).lower())
        token = token.replace("billion", "b").replace("million", "m")
        if token and token not in out:
            out.append(token)
    return out


def token_supported(token: str, evidence_blob: str) -> bool:
    compact = re.sub(r"[,\s]", "", evidence_blob.lower())
    core = re.sub(r"[^0-9.]", "", token)
    if core and len(core) >= 3 and core in compact:
        return True
    if token.rstrip("%") in compact:
        return True
    return token in compact


def strip_unbound_facts(statement: str, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    blob = " ".join(str(row.get("fact") or row.get("excerpt") or "") for row in evidence_rows)
    unsupported: list[str] = []
    revised = statement
    for token in extract_factual_tokens(statement):
        if not token_supported(token, blob):
            unsupported.append(token)
            revised = re.sub(re.escape(token), "", revised, flags=re.I)
    revised = re.sub(r"\s{2,}", " ", revised)
    revised = re.sub(r"\s+([,.;])", r"\1", revised).strip(" ,;.")
    if unsupported and len(revised) < 24:
        revised = compact_text(statement, 400)
    return {
        "statement": revised or statement,
        "unverified_detail": "; ".join(f"{item} could not be verified" for item in unsupported[:8]),
        "unsupported_tokens": unsupported,
        "stripped": bool(unsupported),
    }


def link_is_complete(link: dict[str, Any]) -> bool:
    return bool(compact_text(link.get("proves") or "", 20) and compact_text(link.get("does_not_prove") or "", 20))


def link_quality_ok(link: dict[str, Any], evidence: dict[str, Any] | None) -> bool:
    rel = str(link.get("source_relationship") or (evidence or {}).get("source_relationship") or "")
    if rel in WEAK_RELATIONSHIPS:
        return False
    if str(link.get("strength") or "") == "weak":
        return False
    if str(link.get("relevance") or "") == "background":
        return False
    return True


def needs_external_validation(claim: dict[str, Any]) -> bool:
    blob = f"{claim.get('title') or ''} {claim.get('statement') or ''} {claim.get('claim_dimension') or ''}".lower()
    if any(token in blob for token in ("guid", "outlook", "management said", "management guided")):
        return False
    return any(
        token in blob
        for token in (
            "durab",
            "sustain",
            "demand",
            "share",
            "concentration",
            "cycle",
            "structural",
            "customer",
            "valuation",
        )
    )


def reconcile_status(
    *,
    claim: dict[str, Any],
    links: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    unsupported_tokens: list[str] | None = None,
    counter_search: dict[str, Any] | None = None,
    reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposed = str(claim.get("proposed_status") or claim.get("status") or "unverified")
    support = [row for row in links if row.get("direction") == "support"]
    oppose = [row for row in links if row.get("direction") == "oppose"]
    complete_support = [row for row in support if link_is_complete(row)]
    quality_support = [
        row
        for row in complete_support
        if link_quality_ok(row, evidence_by_id.get(str(row.get("evidence_id"))))
        and str(row.get("relevance") or "direct") == "direct"
        and str(row.get("strength") or "") in STRONG_LINK_QUALITY
    ]
    rels = {
        str(row.get("source_relationship") or (evidence_by_id.get(str(row.get("evidence_id"))) or {}).get("source_relationship") or "")
        for row in support
    }
    has_external = bool(rels & set(EXTERNAL_VALIDATION_RELATIONSHIPS))
    strong_oppose = [
        row
        for row in oppose
        if str(row.get("strength") or "") in STRONG_LINK_QUALITY
        and str(row.get("relevance") or "") == "direct"
        and link_quality_ok(row, evidence_by_id.get(str(row.get("evidence_id"))))
    ]
    only_weak = bool(support) and not quality_support
    only_issuer = rels <= {"issuer_primary", "unknown", "aggregator", "community", ""}
    reasoning = reasoning or {}
    conclusion = str(reasoning.get("current_conclusion") or "").lower()
    reasoning_unsupported = any(
        token in conclusion
        for token in ("not verifiable", "not directly", "unsubstantiated", "are not present", "cannot be verified", "not justified")
    )
    unsupported = list(unsupported_tokens or [])
    if str(reasoning.get("undermines_claim") or "").lower() in {"true", "yes"}:
        strong_oppose = strong_oppose or oppose

    final = "unverified"
    reason = "no complete supporting evidence"
    if strong_oppose and quality_support:
        final = "challenged"
        reason = "support and counter evidence conflict"
    elif strong_oppose and not quality_support:
        final = "contradicted" if any(str(row.get("source_relationship")) in EXTERNAL_VALIDATION_RELATIONSHIPS or str(row.get("source_relationship")) == "issuer_primary" for row in strong_oppose) else "challenged"
        reason = "high-quality counter evidence without matching support"
    elif not support:
        final = "unverified"
        reason = "no supporting evidence in the current evidence set"
    elif unsupported or reasoning_unsupported or only_weak:
        final = "unverified"
        reason = "core assertion or number is not bound to evidence"
    elif only_issuer or not complete_support:
        final = "partially_supported"
        reason = "direction is evidenced but links are incomplete or issuer-only"
    elif quality_support and (not needs_external_validation(claim) or has_external) and not unsupported:
        final = "strongly_supported"
        reason = "direct complete support with required source relationship"
        if needs_external_validation(claim) and not has_external:
            final = "partially_supported"
            reason = "issuer-supported but independently unconfirmed"
    else:
        final = "partially_supported"
        reason = "direction evidenced; duration/magnitude/causal link incomplete"

    if proposed in {"background", "closed"}:
        final = proposed
        reason = "lifecycle status from selection"
    confidence = "low"
    if final == "strongly_supported":
        confidence = "high" if has_external else "medium"
    elif final == "partially_supported":
        confidence = "medium" if quality_support or complete_support else "low"
    elif final in {"challenged", "contradicted"}:
        confidence = "medium"
    counter = dict(counter_search or claim.get("counter_search") or {})
    if not counter.get("counter_search_performed"):
        # still allow status; caller must set the flag
        pass
    return {
        "proposed_status": proposed if proposed in CLAIM_STATUSES else "unverified",
        "final_status": final,
        "status": final,
        "confidence": confidence if confidence in CONFIDENCE else "low",
        "reconciliation_reason": reason,
        "has_external_validation": has_external,
        "complete_support_count": len(complete_support),
        "quality_support_count": len(quality_support),
        "oppose_count": len(oppose),
    }


def default_counter_queries(claim: dict[str, Any], ticker: str) -> list[str]:
    blob = f"{claim.get('claim_subject') or ''} {claim.get('financial_driver') or ''} {claim.get('statement') or ''}".lower()
    key = "demand"
    if "service" in blob:
        key = "services"
    elif any(token in blob for token in ("optical", "datacom", "cpo")):
        key = "optical"
    elif "margin" in blob:
        key = "margin"
    elif any(token in blob for token in ("valuation", "multiple", "pe")):
        key = "valuation"
    elif "revenue" in blob or "growth" in blob:
        key = "revenue"
    templates = DEFAULT_COUNTER_QUERIES.get(key) or DEFAULT_COUNTER_QUERIES["demand"]
    out = [item.format(ticker=ticker) for item in templates]
    for item in claim.get("counter_research_questions") or []:
        text = compact_text(item, 160)
        if text and text not in out:
            out.append(text)
    return out[:4]


def score_candidate(row: dict[str, Any]) -> float:
    rank = {"high": 3.0, "medium": 2.0, "low": 1.0}
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    def _v(name: str) -> float:
        return rank.get(str(scores.get(name) or row.get(name) or "medium"), 2.0)
    return _v("value_impact") * _v("uncertainty") * _v("valuation_relevance") * _v("persistence") * _v("testability")


def token_overlap(left: str, right: str) -> float:
    a = {part for part in re.split(r"[^a-z0-9]+", left.lower()) if len(part) > 3}
    b = {part for part in re.split(r"[^a-z0-9]+", right.lower()) if len(part) > 3}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def match_existing_claim(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any]:
    key = str(candidate.get("claim_key") or "")
    active = [row for row in existing if str(row.get("lifecycle") or "core") not in {"closed"}]
    for row in active:
        if key and row.get("claim_key") == key:
            return {"action": "update_existing", "claim": row, "reason": "claim_key exact match"}
    best = None
    best_score = 0.0
    for row in active:
        score = max(
            token_overlap(str(candidate.get("title") or ""), str(row.get("title") or "")),
            token_overlap(str(candidate.get("statement") or ""), str(row.get("statement") or "")),
        )
        same_axis = (
            _norm_token(candidate.get("claim_subject")) == _norm_token(row.get("claim_subject"))
            and _norm_token(candidate.get("financial_driver")) == _norm_token(row.get("financial_driver"))
            and _norm_token(candidate.get("claim_dimension")) == _norm_token(row.get("claim_dimension"))
        )
        if same_axis:
            score = max(score, 0.7)
        if score > best_score:
            best_score = score
            best = row
    if best and best_score >= 0.72:
        return {"action": "update_existing", "claim": best, "reason": f"semantic similarity {best_score:.2f}"}
    if best and best_score >= 0.55:
        return {"action": "merge_into_existing", "claim": best, "reason": f"subject/driver overlap {best_score:.2f}"}
    return {"action": "create_new", "claim": None, "reason": "no active claim matched"}


def statements_materially_different(old: str, new: str) -> bool:
    if extract_factual_tokens(old) != extract_factual_tokens(new):
        return True
    return token_overlap(old, new) < 0.82


def is_material_change(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if not old:
        return {"material": True, "reason": "new claim"}
    reasons: list[str] = []
    if str(old.get("status") or "") != str(new.get("status") or ""):
        reasons.append("status changed")
    if str(old.get("confidence") or "") != str(new.get("confidence") or ""):
        reasons.append("confidence changed")
    if statements_materially_different(str(old.get("statement") or ""), str(new.get("statement") or "")):
        reasons.append("statement materially changed")
    old_e = set(old.get("supporting_evidence_ids") or [])
    new_e = set(new.get("supporting_evidence_ids") or [])
    old_c = set(old.get("opposing_evidence_ids") or old.get("counter_evidence_ids") or [])
    new_c = set(new.get("opposing_evidence_ids") or new.get("counter_evidence_ids") or [])
    if old_e != new_e:
        reasons.append("decisive evidence changed")
    if old_c != new_c:
        reasons.append("counter evidence changed")
    return {"material": bool(reasons), "reason": "; ".join(reasons) if reasons else "no material change"}


def news_is_duplicate(hit: dict[str, Any], existing_facts: list[str]) -> bool:
    blob = f"{hit.get('title') or ''} {hit.get('snippet') or hit.get('new_fact') or ''}".lower()
    for fact in existing_facts:
        if token_overlap(blob, str(fact or "")) >= 0.72:
            return True
        if str(fact or "").lower()[:80] and str(fact or "").lower()[:80] in blob:
            return True
    return False


def build_link(
    *,
    claim_id: str,
    claim_version_id: str | None,
    evidence_id: str,
    direction: str,
    evidence: dict[str, Any] | None,
    ticker: str,
    related_entities: list[dict[str, Any]] | None = None,
    strength: str = "medium",
    relevance: str = "direct",
    reason: str = "",
    proves: str = "",
    does_not_prove: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    rel = classify_source_relationship(evidence, ticker=ticker, related_entities=related_entities)
    incomplete = not (compact_text(proves, 8) and compact_text(does_not_prove, 8))
    if incomplete:
        strength = "weak" if strength == "strong" else strength
    return {
        "claim_id": claim_id,
        "claim_version_id": claim_version_id,
        "evidence_id": evidence_id,
        "direction": direction,
        "strength": strength,
        "relevance": relevance,
        "source_relationship": rel,
        "reason": compact_text(reason, 400),
        "proves": compact_text(proves, 400),
        "does_not_prove": compact_text(does_not_prove, 400),
        "incomplete": incomplete,
        "run_id": run_id,
    }


def links_from_reasoning(
    reasoning: dict[str, Any] | None,
    *,
    claim: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    allowed: set[str],
    ticker: str,
    related_entities: list[dict[str, Any]] | None,
    run_id: str | None,
    claim_version_id: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rejected: list[str] = []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    payload = reasoning or {}
    rows = list(payload.get("evidence_links") or [])
    if not rows:
        boundary = payload.get("evidence_boundary") if isinstance(payload.get("evidence_boundary"), dict) else {}
        proves = str(boundary.get("proves") or "")
        does_not = str(boundary.get("does_not_prove") or "")
        for eid in claim.get("supporting_evidence_ids") or payload.get("strongest_support_evidence_ids") or []:
            rows.append(
                {
                    "evidence_id": eid,
                    "direction": "support",
                    "strength": "medium",
                    "relevance": "direct",
                    "reason": "",
                    "proves": proves,
                    "does_not_prove": does_not,
                }
            )
        for eid in claim.get("opposing_evidence_ids") or payload.get("strongest_opposing_evidence_ids") or []:
            rows.append(
                {
                    "evidence_id": eid,
                    "direction": "oppose",
                    "strength": "medium",
                    "relevance": "direct",
                    "reason": "",
                    "proves": "",
                    "does_not_prove": "",
                }
            )
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid:
            continue
        if eid not in allowed:
            rejected.append(eid)
            continue
        if eid in seen:
            continue
        seen.add(eid)
        direction = str(raw.get("direction") or "support")
        if direction not in {"support", "oppose", "contextual"}:
            direction = "contextual"
        out.append(
            build_link(
                claim_id=str(claim.get("claim_id") or ""),
                claim_version_id=claim_version_id,
                evidence_id=eid,
                direction=direction,
                evidence=evidence_by_id.get(eid),
                ticker=ticker,
                related_entities=related_entities,
                strength=str(raw.get("strength") or "medium"),
                relevance=str(raw.get("relevance") or "direct"),
                reason=str(raw.get("reason") or ""),
                proves=str(raw.get("proves") or ""),
                does_not_prove=str(raw.get("does_not_prove") or ""),
                run_id=run_id,
            )
        )
    return out, rejected


def check_pm_consistency(
    synthesis: dict[str, Any] | None,
    claims: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = dict(synthesis or {})
    by_id = {str(row.get("claim_id")): row for row in claims if row.get("claim_id")}
    reasons: list[str] = []
    strongest_id = str(payload.get("strongest_claim_id") or "")
    weakest_id = str(payload.get("weakest_claim_id") or "")
    if not strongest_id or strongest_id not in by_id:
        reasons.append("strongest_claim_id is missing or unknown")
    if not weakest_id or weakest_id not in by_id:
        reasons.append("weakest_claim_id is missing or unknown")
    strongest = by_id.get(strongest_id) or {}
    allowed_strong = {"strongly_supported", "partially_supported", "challenged"}
    if strongest and str(strongest.get("status") or strongest.get("final_status") or "") not in allowed_strong:
        reasons.append("strongest claim final_status is not allowed")
    conclusion = str((strongest.get("reasoning") or {}).get("current_conclusion") or "").lower()
    if strongest and any(token in conclusion for token in ("not verifiable", "unsubstantiated", "are not present", "cannot be verified")):
        reasons.append("PM selected a claim that reasoning already marked unsupported")
    view = " ".join(
        [
            str(payload.get("current_view") or ""),
            str(payload.get("short_view") or ""),
            str(payload.get("mid_view") or ""),
            str(payload.get("long_view") or ""),
        ]
    )
    blob = " ".join(str((row.get("fact") or row.get("excerpt") or "")) for row in (evidence_by_id or {}).values())
    blob += " " + " ".join(str(row.get("statement") or "") for row in claims)
    for token in extract_factual_tokens(view):
        if not token_supported(token, blob):
            reasons.append(f"PM cited unbound number {token}")
            break
    passed = not reasons
    return {
        "passed": passed,
        "status": "passed" if passed else "inconsistent",
        "reasons": reasons,
    }
