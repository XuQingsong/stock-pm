"""Honest research quality vs workflow execution status."""

from __future__ import annotations

from typing import Any

from .extract import has_official_source, has_transcript_source, to_number
from .types import QUALITY_AXES


def _level(*, sufficient: bool, partial: bool) -> str:
    if sufficient:
        return "sufficient"
    if partial:
        return "partial"
    return "insufficient"


def assess_research_quality_axes(
    pack: dict[str, Any] | None,
    *,
    evidence: list[dict[str, Any]] | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    valuation: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = pack or {}
    earnings = list(payload.get("earnings_history") or [])
    guidance = list(payload.get("guidance_history") or [])
    prices = list(payload.get("price_reaction_history") or [])
    profile = payload.get("company_profile") or {}
    official = has_official_source(payload)
    transcripts = has_transcript_source(payload)
    evidence_rows = list(evidence or [])
    assumptions = list(assumptions or [])
    ruled = [row for row in assumptions if str(row.get("status") or "unverified") != "unverified"]
    has_print = bool(earnings)
    has_text = official or transcripts or bool(guidance)
    eps = to_number(profile.get("eps_ttm"))
    fcf = to_number(profile.get("fcf"))
    last_close = to_number(profile.get("last_close"))
    net_margin = to_number(profile.get("net_margin_pct") or profile.get("operating_margin_pct") or profile.get("gross_margin_pct"))
    if net_margin is None:
        for row in earnings:
            value = to_number(row.get("margin_pct"))
            if value is not None:
                net_margin = value
                break
    missing = {str(item) for item in (payload.get("missing_fields") or [])}
    template_id = str(payload.get("template_id") or "")
    has_segments = any(isinstance(row, dict) and row.get("segments") for row in earnings)
    has_series = len(earnings) >= 4
    has_driver_claims = any(
        str(row.get("status") or "") == "strengthened"
        or str(row.get("final_status") or "") == "strengthened"
        for row in assumptions
    )
    target = None
    valuation_status = None
    used_fallback = False
    if valuation:
        base = valuation.get("base_case") or {}
        target = to_number(base.get("target_value"))
        calibration = valuation.get("calibration_json") or valuation
        valuation_status = calibration.get("valuation_status") or valuation.get("valuation_status")
        used_fallback = bool(calibration.get("used_template_fallback") or valuation.get("used_template_fallback"))
    discovery = _level(
        sufficient=has_print or official or bool(evidence_rows),
        partial=transcripts or bool(guidance) or bool(prices),
    )
    fundamental = _level(
        sufficient=has_print and has_text,
        partial=has_print or has_text,
    )
    has_baseline = bool(last_close) and (eps not in (None, 0) or fcf not in (None, 0))
    has_margin = net_margin is not None
    has_growth_drivers = has_segments or has_series or has_driver_claims
    has_multiple_anchor = to_number(profile.get("pe_ttm")) is not None or has_margin
    material_gap = bool(missing & {"segment_growth", "fcf", "forward_margin", "commodity_price"})
    if template_id == "energy":
        energy_ready = (fcf not in (None, 0) or has_series) and bool(guidance) and has_baseline
        valuation_sufficient = energy_ready and has_margin and not used_fallback and "commodity_price" not in missing
        valuation_partial = has_baseline or has_print or last_close is not None
    else:
        valuation_sufficient = (
            has_baseline
            and bool(guidance)
            and has_margin
            and has_growth_drivers
            and has_multiple_anchor
            and not used_fallback
            and (has_segments or "segment_growth" not in missing)
        )
        valuation_partial = has_print or last_close is not None or has_baseline
    if valuation_status == "insufficient":
        valuation_sufficient = False
        valuation_partial = False
    elif valuation_status == "provisional":
        valuation_sufficient = False
        valuation_partial = True
    if material_gap and valuation_sufficient:
        valuation_sufficient = False
        valuation_partial = True
    valuation_quality = _level(sufficient=valuation_sufficient, partial=valuation_partial)
    if not transcripts and fundamental == "sufficient" and valuation_quality == "sufficient":
        thesis_partial_ok = True
    else:
        thesis_partial_ok = False
    thesis = _level(
        sufficient=fundamental == "sufficient" and valuation_quality == "sufficient" and (bool(ruled) or target is not None) and transcripts,
        partial=fundamental != "insufficient" or valuation_quality != "insufficient" or bool(assumptions) or thesis_partial_ok,
    )
    if not transcripts and fundamental == "sufficient":
        if thesis == "sufficient":
            thesis = "partial"
    return {
        "quality_for_discovery": discovery,
        "quality_for_fundamental_analysis": fundamental,
        "quality_for_valuation": valuation_quality,
        "quality_for_final_thesis": thesis,
    }


def assess_research_quality(pack: dict[str, Any] | None, *, evidence: list[dict[str, Any]] | None = None) -> str:
    del evidence
    payload = pack or {}
    earnings = list(payload.get("earnings_history") or [])
    guidance = list(payload.get("guidance_history") or [])
    prices = list(payload.get("price_reaction_history") or [])
    official = has_official_source(payload)
    transcripts = has_transcript_source(payload)
    has_core_text = official or transcripts or bool(guidance)
    if earnings and has_core_text and guidance and prices:
        return "sufficient"
    if earnings or official or transcripts or guidance or prices:
        return "partial"
    return "insufficient"


def apply_quality_to_status(status: str, quality: str) -> str:
    current = str(status or "success")
    if current == "failed":
        return "failed"
    if quality == "sufficient":
        return current
    if current == "success":
        return "partial"
    return current


def worst_quality(axes: dict[str, str] | None) -> str:
    payload = axes or {}
    order = {"insufficient": 0, "partial": 1, "sufficient": 2}
    levels = [str(payload.get(key) or "insufficient") for key in QUALITY_AXES]
    return min(levels, key=lambda item: order.get(item, 0))
