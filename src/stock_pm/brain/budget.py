"""Ordinary events cannot rewrite large parts of the Brain in one pass."""

from __future__ import annotations

from typing import Any

from .layers import object_layer
from .snapshot import driver_family
from .types import CHANGE_BUDGET, FAST_LAYERS

_REWRITE_FIELDS = ("statement", "status", "current_state", "direction", "name", "title")


def _is_evidence_only(row: dict[str, Any]) -> bool:
    nxt = row.get("to_payload") if isinstance(row.get("to_payload"), dict) else row.get("to")
    nxt = dict(nxt) if isinstance(nxt, dict) else {}
    now = row.get("from_payload") if isinstance(row.get("from_payload"), dict) else row.get("from")
    now = dict(now) if isinstance(now, dict) else {}
    if any(field in nxt and str(nxt.get(field) or "") != str(now.get(field) or "") for field in _REWRITE_FIELDS):
        return False
    return any(
        key in nxt
        for key in (
            "evidence_ids",
            "supporting_evidence_ids",
            "support_strength",
            "counter_strength",
            "uncertainty",
            "confidence",
        )
    )


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("to_payload") if isinstance(row.get("to_payload"), dict) else row.get("to")
    return dict(raw) if isinstance(raw, dict) else {}


def _is_base(proposal: dict[str, Any]) -> bool:
    target = str(proposal.get("object_type") or "")
    payload = _payload(proposal)
    return target == "scenario" and (
        payload.get("base_case_change") is True or str(payload.get("scope") or "") == "base"
    )


def _lookup(brain: dict[str, Any] | None, object_id: str) -> dict[str, Any]:
    context = brain or {}
    for group in ("drivers", "claims", "states"):
        for row in context.get(group) or []:
            if not isinstance(row, dict):
                continue
            ids = {
                str(row.get("driver_id") or ""),
                str(row.get("canonical_key") or ""),
                str(row.get("claim_id") or ""),
                str(row.get("state_id") or ""),
            }
            if object_id and object_id in ids:
                return row
    return {}


def _driver_row(proposal: dict[str, Any], brain: dict[str, Any] | None) -> dict[str, Any]:
    payload = _payload(proposal)
    found = _lookup(brain, str(proposal.get("object_id") or ""))
    return {**found, **payload, **({k: proposal.get(k) for k in ("canonical_key", "category") if proposal.get(k)})}


def _drivers_related(rows: list[dict[str, Any]], *, brain: dict[str, Any] | None) -> bool:
    if len(rows) <= 1:
        return True
    families = {driver_family(_driver_row(row, brain)) for row in rows}
    if len(families) == 1:
        return True
    ids: list[set[str]] = []
    for row in rows:
        payload = _payload(row)
        found = _lookup(brain, str(row.get("object_id") or ""))
        related = {str(item) for item in (found.get("related_claim_ids") or payload.get("related_claim_ids") or []) if str(item)}
        related.add(str(row.get("object_id") or ""))
        ids.append(related)
    for left in ids:
        for right in ids:
            if left is right:
                continue
            if left & right:
                return True
    return False


def change_scope(proposals: list[dict[str, Any]] | None, *, brain: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = [row for row in (proposals or []) if isinstance(row, dict)]
    claims = [row for row in rows if str(row.get("object_type") or "") in {"claim", "core_claim"} and not _is_evidence_only(row)]
    drivers = [row for row in rows if str(row.get("object_type") or "") in {"driver", "value_driver"} and not _is_evidence_only(row)]
    states = [row for row in rows if str(row.get("object_type") or "") in {"state", "company_state", "industry_state", "macro_state"} and not _is_evidence_only(row)]
    edges = [row for row in rows if str(row.get("object_type") or "") in {"causal_edge", "causal_relationship"}]
    bases = [row for row in rows if _is_base(row)]
    slow_layers = {
        object_layer(str(row.get("object_type") or ""))
        for row in rows
        if object_layer(str(row.get("object_type") or "")) not in FAST_LAYERS
        and object_layer(str(row.get("object_type") or "")) != "observation"
    }
    related_drivers = _drivers_related(drivers, brain=brain)
    driver_cap = CHANGE_BUDGET["max_related_drivers"] if related_drivers else CHANGE_BUDGET["max_unrelated_drivers"]
    over = (
        len(claims) > CHANGE_BUDGET["max_auto_claims"]
        or len(drivers) > driver_cap
        or len(states) > CHANGE_BUDGET["max_auto_states"]
        or len(bases) > CHANGE_BUDGET["max_auto_base"]
        or len(edges) > CHANGE_BUDGET["max_auto_causal_edges"]
        or len(slow_layers) > CHANGE_BUDGET["max_slow_layers"]
    )
    return {
        "claim_count": len(claims),
        "driver_count": len(drivers),
        "state_count": len(states),
        "base_count": len(bases),
        "causal_edge_count": len(edges),
        "slow_layer_count": len(slow_layers),
        "drivers_related": related_drivers,
        "abnormal_change_scope": over,
        "requires_review": over,
        "auto_commit_allowed": not over,
    }
