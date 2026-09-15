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
    target = None
    if valuation:
        base = valuation.get("base_case") or {}
        target = to_number(base.get("target_value"))
    discovery = _level(
        sufficient=has_print or official or bool(evidence_rows),
        partial=transcripts or bool(guidance) or bool(prices),
    )
    fundamental = _level(
        sufficient=has_print and has_text,
        partial=has_print or has_text,
    )
    valuation_quality = _level(
        sufficient=bool(last_close) and (eps not in (None, 0) or fcf not in (None, 0)) and has_print,
        partial=has_print or last_close is not None,
    )
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
