"""Targeted Brain Snapshot for GLM-5.3. Not the whole company Brain."""

from __future__ import annotations

from typing import Any

from .claim_integrity import token_overlap
from .shadow import current_states_only


def _hay(row: dict[str, Any] | None) -> str:
    item = row or {}
    return " ".join(
        str(item.get(key) or "")
        for key in ("name", "title", "statement", "canonical_key", "subject", "claim_subject", "current_state")
    ).lower()


def _match(row: dict[str, Any], needles: list[str]) -> bool:
    text = _hay(row)
    if not text:
        return False
    for needle in needles:
        token = str(needle or "").strip().lower()
        if not token:
            continue
        if token in {str(row.get("state_id") or ""), str(row.get("driver_id") or ""), str(row.get("claim_id") or ""), str(row.get("exposure_id") or "")}:
            return True
        if token in text or token_overlap(token.replace("_", " "), text) >= 0.4:
            return True
    return False


def locate_affected_objects(
    *,
    extract: dict[str, Any] | None,
    event: dict[str, Any] | None,
    states: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    exposures: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    payload = dict(extract or {})
    item = dict(event or {})
    needles = [str(value) for value in (payload.get("possible_affected") or payload.get("affected_objects") or []) if str(value).strip()]
    needles.extend(str(value) for value in (item.get("entities") or payload.get("entities") or []) if str(value).strip())
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {payload.get('fact') or ''} {payload.get('event_type') or item.get('event_type') or ''}"
    needles.extend(part for part in blob.lower().replace("-", " ").split() if len(part) > 3)
    current = current_states_only(states)
    hit_states = [row for row in current if _match(row, needles)]
    hit_drivers = [row for row in (drivers or []) if _match(row, needles)]
    hit_claims = [row for row in (claims or []) if _match(row, needles)]
    hit_exposures = [row for row in (exposures or []) if _match(row, needles)]
    return {
        "states": hit_states,
        "drivers": hit_drivers,
        "claims": hit_claims,
        "exposures": hit_exposures,
    }


def build_snapshot(
    *,
    event: dict[str, Any],
    affected: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
    causal_edges: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    shadows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    claim_ids = {str(row.get("claim_id")) for row in affected.get("claims") or [] if row.get("claim_id")}
    driver_ids = {str(row.get("driver_id")) for row in affected.get("drivers") or [] if row.get("driver_id")}
    state_ids = {str(row.get("state_id")) for row in affected.get("states") or [] if row.get("state_id")}
    object_ids = claim_ids | driver_ids | state_ids
    evidence_ids = set()
    for row in (affected.get("states") or []) + (affected.get("drivers") or []) + (affected.get("claims") or []):
        for eid in row.get("evidence_ids") or row.get("supporting_evidence_ids") or []:
            evidence_ids.add(str(eid))
        for eid in row.get("opposing_evidence_ids") or []:
            evidence_ids.add(str(eid))
    relevant_evidence = [row for row in (evidence or []) if str(row.get("id") or row.get("evidence_id") or "") in evidence_ids]
    counter = [
        row
        for row in (links or [])
        if str(row.get("direction") or "") == "oppose" and str(row.get("claim_id") or "") in claim_ids
    ]
    relevant_edges = [
        row
        for row in (causal_edges or [])
        if any(token in f"{row.get('from_node') or ''} {row.get('to_node') or ''}".lower() for token in object_ids)
        or not object_ids
    ][:8]
    relevant_history = [
        row
        for row in (history or [])
        if str(row.get("object_id") or "") in object_ids or str(row.get("object_type") or "") in {"event", "event_impact"}
    ][-8:]
    return {
        "event": event,
        "states": current_states_only(affected.get("states")),
        "drivers": list(affected.get("drivers") or []),
        "claims": list(affected.get("claims") or []),
        "exposures": list(affected.get("exposures") or []),
        "evidence": relevant_evidence[:16],
        "counter_evidence": counter[:12],
        "causal_edges": relevant_edges,
        "history": relevant_history,
        "shadows": list(shadows or []),
        "targeted": True,
        "full_brain": False,
    }
