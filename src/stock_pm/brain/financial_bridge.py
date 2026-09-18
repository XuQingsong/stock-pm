"""Claim/Driver → Financial Impact Bridge. Direction without a number is allowed."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .limits import limit_words
from .types import FINANCIAL_METRICS, HORIZONS


def _metric(value: Any) -> str | None:
    text = str(value or "").strip()
    aliases = {"asp": "ASP", "fcf": "FCF", "eps": "EPS", "wacc": "WACC", "gm": "gross_margin", "om": "operating_margin"}
    key = aliases.get(text.lower(), text)
    if key in FINANCIAL_METRICS:
        return key
    lower = text.lower().replace(" ", "_")
    for item in FINANCIAL_METRICS:
        if item.lower() == lower:
            return item
    return None


def normalize_financial_impact(
    raw: dict[str, Any],
    *,
    allowed_ids: set[str],
    object_type: str,
    object_id: str,
) -> dict[str, Any] | None:
    metric = _metric(raw.get("metric") or raw.get("financial_link"))
    if not metric:
        return None
    evidence_ids = []
    for item in raw.get("evidence_ids") or []:
        key = str(item or "").strip()
        if key and key in allowed_ids and key not in evidence_ids:
            evidence_ids.append(key)
    magnitude = raw.get("magnitude_range") or raw.get("magnitude")
    if magnitude and not evidence_ids:
        magnitude = None
    horizon = raw.get("time_horizon")
    if horizon not in HORIZONS:
        horizon = "medium"
    return {
        "impact_id": raw.get("impact_id") or new_id("bfi"),
        "object_type": object_type,
        "object_id": object_id,
        "metric": metric,
        "direction": compact_text(raw.get("direction") or "", 20) or None,
        "magnitude_range": magnitude if isinstance(magnitude, (dict, str, int, float)) else None,
        "time_horizon": horizon,
        "confidence": raw.get("confidence") or "low",
        "mechanism": limit_words(compact_text(raw.get("mechanism") or "", 400), 40),
        "evidence_ids": evidence_ids,
        "direction_only": magnitude is None,
    }


def impacts_from_objects(
    *,
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    transmissions: list[dict[str, Any]],
    allowed_ids: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    tx_metrics = []
    for row in transmissions or []:
        tx_metrics.extend(row.get("financial_metrics_affected") or [])
    for driver in drivers or []:
        raw = {
            "metric": driver.get("financial_link"),
            "direction": driver.get("direction"),
            "time_horizon": driver.get("time_horizon"),
            "confidence": driver.get("uncertainty") or "low",
            "mechanism": driver.get("why_it_matters") or driver.get("description"),
            "evidence_ids": driver.get("evidence_ids") or [],
        }
        item = normalize_financial_impact(raw, allowed_ids=allowed_ids, object_type="driver", object_id=str(driver.get("driver_id") or ""))
        if not item:
            continue
        key = (item["object_type"], item["object_id"], item["metric"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    for claim in claims or []:
        raw = {
            "metric": claim.get("financial_driver"),
            "direction": (claim.get("reasoning") or {}).get("direction"),
            "time_horizon": claim.get("time_horizon"),
            "confidence": claim.get("confidence") or "low",
            "mechanism": claim.get("why_it_matters"),
            "evidence_ids": claim.get("supporting_evidence_ids") or [],
        }
        item = normalize_financial_impact(raw, allowed_ids=allowed_ids, object_type="claim", object_id=str(claim.get("claim_id") or ""))
        if not item:
            continue
        key = (item["object_type"], item["object_id"], item["metric"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
