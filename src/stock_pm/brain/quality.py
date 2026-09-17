"""Brain quality bands. Fail loudly; never dress missing data as complete analysis."""

from __future__ import annotations

from typing import Any

from .news import classify_news_hits, source_family
from .types import QUALITY_BANDS


def _band(score: str) -> str:
    return score if score in QUALITY_BANDS else "Poor"


def _warning(code: str, reason: str) -> dict[str, str]:
    return {"code": "BRAIN QUALITY WARNING", "axis": code, "reason": reason}


def assess_brain_quality(
    *,
    header: dict[str, Any],
    evidence: list[dict[str, Any]],
    news: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    pack: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    profile = (pack or {}).get("company_profile") or {}
    missing = [str(item) for item in ((pack or {}).get("missing_fields") or [])]
    growth = header.get("growth") or {}
    latest = header.get("latest_quarter") or {}
    price = (header.get("price") or {}).get("value")
    has_rev = (growth.get("revenue_ttm") or {}).get("value") is not None
    has_eps = (growth.get("eps_ttm") or {}).get("value") is not None
    has_print = (latest.get("revenue") or {}).get("value") is not None
    if has_rev and has_eps and price is not None and has_print:
        data = "Good"
    elif has_rev or has_eps or price is not None:
        data = "Partial"
        warnings.append(_warning("Data Coverage", "Price, TTM, or latest-quarter fields are incomplete."))
    else:
        data = "Poor"
        warnings.append(_warning("Data Coverage", "Company fundamentals are missing; Brain cannot form a financial view."))
    if integrity and integrity.get("inconsistent"):
        data = "Poor"
        warnings.append(_warning("Data Coverage", "financial_input_inconsistent: companyfacts and earnings-release numbers disagree beyond tolerance."))
    if integrity and integrity.get("data_poor"):
        data = "Poor"
        warnings.append(_warning("Data Coverage", integrity.get("reason") or "financial_input_incomplete"))
    if "fcf" in missing or (latest.get("fcf") or {}).get("value") is None:
        if data == "Good":
            data = "Partial"
        warnings.append(_warning("Data Coverage", "FCF is unavailable."))
    if "segment_growth" in missing or not any(isinstance(row, dict) and row.get("segments") for row in ((pack or {}).get("earnings_history") or [])):
        if data == "Good":
            data = "Partial"
        warnings.append(_warning("Data Coverage", "Official segment mix is missing."))
    if (header.get("forward") or {}).get("consensus", {}).get("origin") == "unavailable":
        warnings.append(_warning("Data Coverage", "No trusted consensus source is wired; consensus stays unavailable."))

    stats = classify_news_hits(news)
    independent_news = [
        row
        for row in news
        if source_family(row.get("url"), row.get("source")) in {"high_quality_news", "issuer_ir"}
        and (row.get("published_at") or row.get("source_time"))
    ]
    bodies = [
        row
        for row in news
        if str(row.get("snippet") or row.get("new_fact") or row.get("excerpt") or row.get("fact") or "").strip()
        and str(row.get("title") or "").strip() not in {"8-K", "10-Q", "10-K", "6-K", "20-F"}
        and (row.get("published_at") or row.get("source_time"))
    ]
    if stats["in_window"] >= 3 and stats["high_quality_independent"] >= 1 and stats["full_text_available"] >= 1:
        news_band = "Good"
    elif stats["in_window"] or independent_news or bodies:
        news_band = "Partial"
        if stats["high_quality_independent"] < 1:
            warnings.append(
                _warning(
                    "News Coverage",
                    "No Reuters / Bloomberg / FT / WSJ / IR items with a real last-7-day date.",
                )
            )
        if stats["undated"]:
            warnings.append(_warning("News Coverage", "Undated search hits are not counted as last-7-day news."))
        if stats["full_text_available"] < 1:
            warnings.append(_warning("News Coverage", "Last-7-day items lack parseable body text."))
    else:
        news_band = "Poor"
        warnings.append(_warning("News Coverage", "No last-7-day dated news or filings were retrieved."))

    sourced = [row for row in evidence if row.get("source") and (row.get("source_url") or row.get("excerpt") or row.get("fact"))]
    if len(sourced) >= 8:
        evidence_band = "Good"
    elif sourced:
        evidence_band = "Partial"
        warnings.append(_warning("Evidence Quality", "Evidence count is thin or some rows lack source/excerpt."))
    else:
        evidence_band = "Poor"
        warnings.append(_warning("Evidence Quality", "No evidence with provenance is available."))

    independent = [
        row
        for row in evidence
        if source_family(row.get("source_url"), row.get("source")) in {"high_quality_news", "sec", "official"}
        or str(row.get("independence_key") or "").startswith(("customer", "industry", "sec"))
        or str((row.get("raw_reference") or {}).get("evidence_side") or "") in {"independent_customer", "industry_third_party"}
    ]
    if len(independent) >= 3:
        independent_band = "Good"
    elif independent:
        independent_band = "Partial"
    else:
        independent_band = "Poor"
        warnings.append(_warning("Independent Evidence", "No independent (non-issuer) evidence family is present."))

    ok_calls = [row for row in llm_calls if row.get("llm_status") == "ok" and row.get("llm_called")]
    required = {"company_understanding", "core_claims", "news_interpretation", "claim_reasoning", "pm_synthesis"}
    ok_steps = {str(row.get("step")) for row in ok_calls}
    if required <= ok_steps and claims:
        llm_band = "Good"
    elif ok_calls:
        llm_band = "Partial"
        missing_steps = sorted(required - ok_steps)
        warnings.append(_warning("LLM Reasoning", "LLM did not complete every reasoning step: " + ", ".join(missing_steps) + "."))
    else:
        llm_band = "Poor"
        warnings.append(_warning("LLM Reasoning", "LLM was not invoked or failed; Core Claims were not generated. This is not a template fallback."))

    price_ts = str(header.get("price_timestamp") or "")
    pack_ts = str(header.get("pack_updated_at") or "")
    if price_ts or pack_ts:
        freshness = "Good" if "2026-09" in (price_ts + pack_ts) or price_ts >= "2026-09-10" else "Partial"
        if freshness != "Good":
            warnings.append(_warning("Freshness", f"Price/pack timestamp may be stale: {price_ts or pack_ts}."))
    else:
        freshness = "Poor"
        warnings.append(_warning("Freshness", "No price timestamp on the pack."))

    core = [row for row in claims if row.get("is_core")]
    if llm_band != "Poor" and not core:
        llm_band = "Poor"
        warnings.append(_warning("LLM Reasoning", "No Core Claims survived evidence grounding."))

    axes = {
        "data_coverage": _band(data),
        "news_coverage": _band(news_band),
        "evidence_quality": _band(evidence_band),
        "independent_evidence": _band(independent_band),
        "llm_reasoning": _band(llm_band),
        "freshness": _band(freshness),
    }
    poor = [key for key, value in axes.items() if value == "Poor"]
    return {
        "axes": axes,
        "warnings": warnings,
        "poor_axes": poor,
        "headline": "BRAIN QUALITY WARNING" if poor or any(item["axis"] for item in warnings if axes.get(_axis_key(item["axis"])) == "Poor") else "Brain quality",
    }


def _axis_key(label: str) -> str:
    mapping = {
        "Data Coverage": "data_coverage",
        "News Coverage": "news_coverage",
        "Evidence Quality": "evidence_quality",
        "Independent Evidence": "independent_evidence",
        "LLM Reasoning": "llm_reasoning",
        "Freshness": "freshness",
    }
    return mapping.get(label, "")
