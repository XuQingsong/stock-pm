"""Verifiable decision records for the stock-pm decision loop.

The functions in this module are deliberately pure.  They turn already
available observations into auditable records without inventing missing data.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


ATTRIBUTION_TYPES = frozenset(
    {
        "known_but_underweighted",
        "new_information",
        "expectation_error",
        "timing_error",
        "model_error",
        "data_quality_error",
        "noise_unexplained",
    }
)
DIRECTIONS = frozenset({"bullish", "neutral", "bearish"})
EVIDENCE_QUALITY = frozenset({"strong", "medium", "weak"})


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def percent_gap(actual: Any, expected: Any) -> float | None:
    actual_n, expected_n = _number(actual), _number(expected)
    if actual_n is None or expected_n in (None, 0):
        return None
    return round((actual_n - expected_n) / abs(expected_n) * 100, 2)


def build_expectation_gap(
    *,
    actual: Mapping[str, Any] | None,
    latest_consensus: Mapping[str, Any] | None,
    prior_consensus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare actuals with the latest expectation and expose revisions.

    Missing values remain missing; a favorable/unfavorable label is emitted
    only when a numerical gap is available.
    """
    actual, latest_consensus, prior_consensus = actual or {}, latest_consensus or {}, prior_consensus or {}
    fields = sorted(set(actual) | set(latest_consensus) | set(prior_consensus))
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for field in fields:
        value = _number(actual.get(field))
        expected = _number(latest_consensus.get(field))
        prior = _number(prior_consensus.get(field))
        gap = percent_gap(value, expected)
        revision = percent_gap(expected, prior)
        if value is None or expected is None:
            missing.append(field)
        rows.append(
            {
                "field": field,
                "actual": value,
                "latest_consensus": expected,
                "prior_consensus": prior,
                "gap_pct": gap,
                "revision_pct": revision,
                "result": None if gap is None else ("above" if gap > 0 else "below" if gap < 0 else "inline"),
            }
        )
    return {"rows": rows, "missing_fields": missing, "complete": bool(rows) and not missing}


def build_what_changed(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    materiality: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return measurable deltas and rank material changes first."""
    previous, current, materiality = previous or {}, current or {}, materiality or {}
    changes: list[dict[str, Any]] = []
    for field in sorted(set(previous) | set(current)):
        old, new = _number(previous.get(field)), _number(current.get(field))
        if old is None or new is None:
            continue
        delta = new - old
        delta_pct = None if old == 0 else delta / abs(old) * 100
        threshold = float(materiality.get(field, 0))
        score = abs(delta_pct) if delta_pct is not None else abs(delta)
        changes.append(
            {
                "field": field,
                "previous": old,
                "current": new,
                "delta": round(delta, 4),
                "delta_pct": None if delta_pct is None else round(delta_pct, 2),
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
                "material": score >= threshold and delta != 0,
                "materiality_score": round(score, 2),
            }
        )
    changes.sort(key=lambda row: (not row["material"], -row["materiality_score"], row["field"]))
    return {"changes": changes, "material_count": sum(row["material"] for row in changes)}


def build_thesis(
    *,
    direction: str,
    bull_drivers: Iterable[str],
    bear_drivers: Iterable[str],
    key_disagreement: str,
    invalidation: Mapping[str, Any],
    evidence_quality: str,
) -> dict[str, Any]:
    direction, evidence_quality = direction.lower(), evidence_quality.lower()
    if direction not in DIRECTIONS:
        raise ValueError("direction must be bullish, neutral, or bearish")
    if evidence_quality not in EVIDENCE_QUALITY:
        raise ValueError("evidence_quality must be strong, medium, or weak")
    bull, bear = [str(x).strip() for x in bull_drivers if str(x).strip()], [str(x).strip() for x in bear_drivers if str(x).strip()]
    if not bull or not bear or len(bull) > 3 or len(bear) > 3:
        raise ValueError("thesis requires 1-3 bull drivers and 1-3 bear drivers")
    if not key_disagreement.strip() or not invalidation:
        raise ValueError("key disagreement and invalidation are required")
    return {
        "direction": direction,
        "evidence_quality": evidence_quality,
        "bull_drivers": bull,
        "bear_drivers": bear,
        "key_disagreement": key_disagreement.strip(),
        "invalidation": deepcopy(dict(invalidation)),
    }


def freeze_prediction(
    prediction: Mapping[str, Any],
    *,
    generated_at: Any,
    model_version: str,
    data_snapshot_id: Any,
) -> dict[str, Any]:
    """Create a canonical immutable envelope and content checksum."""
    if not model_version or data_snapshot_id is None or generated_at is None:
        raise ValueError("generated_at, model_version and data_snapshot_id are required")
    body = {
        "schema_version": 1,
        "generated_at": _iso(generated_at),
        "model_version": model_version,
        "data_snapshot_id": data_snapshot_id,
        "prediction": deepcopy(dict(prediction)),
    }
    return {**body, "content_hash": sha256(_canonical(body).encode("utf-8")).hexdigest(), "frozen": True}


def verify_frozen_prediction(record: Mapping[str, Any]) -> bool:
    body = {key: deepcopy(record.get(key)) for key in ("schema_version", "generated_at", "model_version", "data_snapshot_id", "prediction")}
    return record.get("frozen") is True and record.get("content_hash") == sha256(_canonical(body).encode("utf-8")).hexdigest()


def review_prediction(
    frozen: Mapping[str, Any],
    *,
    actual_return_pct: Any,
    benchmark_return_pct: Any = None,
    max_drawdown_pct: Any = None,
    invalidated: bool = False,
    attribution: str,
    attribution_evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Score outcome and constrain hindsight attribution to timestamped evidence."""
    if not verify_frozen_prediction(frozen):
        raise ValueError("prediction is not a valid frozen record")
    if attribution not in ATTRIBUTION_TYPES:
        raise ValueError("unsupported attribution")
    actual = _number(actual_return_pct)
    if actual is None:
        return {"outcome": "invalid_data", "attribution": "data_quality_error", "reviewable": False}
    prediction = frozen.get("prediction") or {}
    direction = str(prediction.get("direction") or "").lower()
    direction_hit = (direction == "bullish" and actual > 0) or (direction == "bearish" and actual < 0) or (direction == "neutral" and actual == 0)
    benchmark = _number(benchmark_return_pct)
    evidence = [deepcopy(dict(item)) for item in attribution_evidence]
    cutoff = str(frozen["generated_at"])
    for item in evidence:
        observed = _iso(item.get("observed_at"))
        if attribution == "known_but_underweighted" and (not observed or observed > cutoff):
            raise ValueError("known evidence must be timestamped at or before prediction generation")
        if attribution == "new_information" and (not observed or observed <= cutoff):
            raise ValueError("new information must be timestamped after prediction generation")
    outcome = "miss" if invalidated or not direction_hit else "hit"
    return {
        "outcome": outcome,
        "reviewable": True,
        "direction_hit": direction_hit,
        "actual_return_pct": actual,
        "benchmark_return_pct": benchmark,
        "excess_return_pct": None if benchmark is None else round(actual - benchmark, 2),
        "max_drawdown_pct": _number(max_drawdown_pct),
        "invalidated_first": bool(invalidated),
        "attribution": attribution,
        "attribution_evidence": evidence,
        "prediction_hash": frozen["content_hash"],
    }
