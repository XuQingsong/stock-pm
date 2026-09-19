"""Expectation State: market's prior vs what actually printed.

Fast market-layer object. Below-expectation does not rewrite Fundamental State or Core Claim.
"""

from __future__ import annotations

import re
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import CONFIDENCE, EXPECTATION_COMPARISONS, EXPECTATION_TRENDS, LOW_RELIABILITY

_PCT = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")


def normalize_expectation(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or raw.get("ticker") or "").upper()
    name = compact_text(raw.get("name") or raw.get("subject") or "expectation", 80) or "expectation"
    actual = raw.get("actual")
    expected = raw.get("expected")
    comparison = str(raw.get("comparison") or "")
    if actual is None or expected is None:
        comparison = "unknown"
    elif comparison not in EXPECTATION_COMPARISONS or comparison in {"", "in_line"} and (actual is None or expected is None):
        comparison = "unknown"
    if comparison not in EXPECTATION_COMPARISONS:
        comparison = "unknown"
    if comparison in {"above", "in_line", "below"} and (actual is None or expected is None):
        comparison = "unknown"
    trend = str(raw.get("trend") or raw.get("delta") or "unchanged")
    if trend not in EXPECTATION_TRENDS:
        if comparison == "below":
            trend = "falling"
        elif comparison == "above":
            trend = "rising"
        else:
            trend = "unchanged"
    confidence = str(raw.get("confidence") or "medium")
    if confidence not in CONFIDENCE:
        confidence = "medium"
    if str(raw.get("source_kind") or "") in {"rumor", "signal"} or str(raw.get("fact_reliability") or "") in LOW_RELIABILITY:
        confidence = "low"
    return {
        "expectation_id": raw.get("expectation_id") or new_id("bexpc"),
        "ticker": symbol,
        "name": name,
        "subject": compact_text(raw.get("subject") or name, 80),
        "actual": actual,
        "expected": expected,
        "comparison": comparison,
        "trend": trend,
        "confidence": confidence,
        "supporting_evidence_ids": [str(item) for item in (raw.get("supporting_evidence_ids") or raw.get("evidence_ids") or []) if str(item).strip()],
        "last_material_change": compact_text(raw.get("last_material_change") or raw.get("reason") or "", 200),
        "reason": compact_text(raw.get("reason") or f"{name}: actual {actual} vs expected {expected} ({comparison})", 240),
        "source_kind": str(raw.get("source_kind") or "news"),
    }


def parse_actual_expected(event: dict[str, Any] | None) -> dict[str, Any] | None:
    item = event or {}
    if item.get("actual") is not None and item.get("expected") is not None:
        try:
            return {"actual": float(item.get("actual")), "expected": float(item.get("expected")), "name": compact_text(item.get("expectation_name") or item.get("subject") or "print", 80)}
        except (TypeError, ValueError):
            return None
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}"
    found = [float(match) for match in _PCT.findall(blob)]
    if "expected" in blob.lower() and len(found) >= 2:
        return {"actual": found[0], "expected": found[1], "name": compact_text(item.get("expectation_name") or "print", 80)}
    return None


def compare_actual_to_expectation(actual: float, expected: float, *, tolerance: float = 1.0) -> dict[str, str]:
    delta = float(actual) - float(expected)
    if delta > tolerance:
        return {"comparison": "above", "trend": "rising"}
    if delta < -tolerance:
        return {"comparison": "below", "trend": "falling"}
    return {"comparison": "in_line", "trend": "unchanged"}


def expectation_from_event(event: dict[str, Any] | None, *, ticker: str) -> dict[str, Any] | None:
    item = event or {}
    parsed = parse_actual_expected(item)
    if parsed:
        compared = compare_actual_to_expectation(parsed["actual"], parsed["expected"])
        return normalize_expectation(
            {
                "name": parsed["name"] or "print",
                "subject": parsed["name"],
                "actual": parsed["actual"],
                "expected": parsed["expected"],
                "comparison": compared["comparison"],
                "trend": compared["trend"],
                "source_kind": item.get("kind") or item.get("source_kind") or "news",
                "fact_reliability": item.get("fact_reliability"),
                "last_material_change": compact_text(item.get("title") or item.get("fact") or "", 160),
                "reason": f"Actual {parsed['actual']} vs expected {parsed['expected']} ({compared['comparison']}).",
                "evidence_ids": list(item.get("evidence_ids") or []),
            },
            ticker=ticker,
        )
    rumor = str(item.get("kind") or "") == "rumor" or str(item.get("fact_reliability") or "") in LOW_RELIABILITY
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    if not rumor:
        return None
    falling = any(token in blob for token in ("delay", "cancel", "slow", "reduce", "miss", "weaker", "soft"))
    rising = any(token in blob for token in ("accelerate", "stronger", "beat", "upside"))
    if not (falling or rising):
        return None
    trend = "falling" if falling and not rising else ("rising" if rising else "unchanged")
    return normalize_expectation(
        {
            "name": compact_text(item.get("expectation_name") or item.get("subject") or "rumor_expectation", 80),
            "subject": compact_text(item.get("subject") or item.get("title") or "rumor_expectation", 80),
            "comparison": "unknown",
            "actual": None,
            "expected": None,
            "trend": trend,
            "confidence": "low",
            "source_kind": "rumor",
            "fact_reliability": item.get("fact_reliability") or "rumor",
            "last_material_change": compact_text(item.get("title") or item.get("fact") or "", 160),
            "reason": "Low-confidence expectation shift from an unconfirmed report; not a print.",
            "evidence_ids": list(item.get("evidence_ids") or []),
        },
        ticker=ticker,
    )
