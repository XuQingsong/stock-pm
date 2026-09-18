"""Scenario-first updates with hysteresis.

New events enter Scenario first. Base changes only after persistent,
independent, high-quality operating evidence.
"""

from __future__ import annotations

from typing import Any

from .claim_integrity import classify_source_relationship

PERSISTENCE_MARKERS = (
    "guidance",
    "outlook",
    "reported",
    "results",
    "10-q",
    "10-k",
    "8-k",
    "repeat",
    "consecutive",
    "second quarter",
    "followed through",
)


def _blob(rows: list[dict[str, Any]]) -> str:
    return " ".join(str(row.get("fact") or row.get("excerpt") or row.get("title") or "") for row in rows).lower()


def qualifies_for_base(
    *,
    ticker: str,
    event: dict[str, Any] | None,
    transmission: dict[str, Any] | None,
    evidence_rows: list[dict[str, Any]],
    related_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [row for row in evidence_rows or [] if isinstance(row, dict)]
    relationships = [
        classify_source_relationship(row, ticker=ticker, related_entities=related_entities) for row in rows
    ]
    direct = [rel for rel in relationships if rel == "issuer_primary"]
    independent = [rel for rel in relationships if rel in {"independent_media", "industry_peer"}]
    related = [rel for rel in relationships if rel == "related_entity_primary"]
    blob = _blob(rows) + " " + str((event or {}).get("title") or "").lower()
    persistence = any(marker in blob for marker in PERSISTENCE_MARKERS)
    repeated = len(rows) >= 2 and len(set(relationships)) >= 2
    high_quality_direct = bool(direct)
    reasons = []
    if not high_quality_direct:
        reasons.append("missing_direct_high_quality_evidence")
    if not persistence:
        reasons.append("persistence_not_confirmed")
    if not repeated and "guidance" not in blob and "reported" not in blob:
        reasons.append("missing_repeated_or_reported_signal")
    if related and not direct:
        reasons.append("related_entity_only")
    allowed = high_quality_direct and persistence and (repeated or "guidance" in blob or "reported" in blob) and not (related and not direct)
    proposed = bool((transmission or {}).get("base_case_change"))
    return {
        "base_update_allowed": bool(allowed and proposed),
        "scenario_only": not (allowed and proposed),
        "proposed_base_change": proposed,
        "blocked": proposed and not allowed,
        "reasons": reasons,
        "direct_count": len(direct),
        "independent_count": len(independent),
        "persistence_confirmed": persistence,
    }


def apply_scenario_policy(transmission: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    row = dict(transmission or {})
    if decision.get("base_update_allowed"):
        row["scenario_only"] = False
        row["base_case_change"] = True
    else:
        row["scenario_only"] = True
        row["base_case_change"] = False
        if decision.get("blocked"):
            row["base_block_reason"] = decision.get("reasons") or []
    return row
