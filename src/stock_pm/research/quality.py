"""Honest research quality vs workflow execution status."""

from __future__ import annotations

from typing import Any

from .extract import has_official_source, has_transcript_source


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
