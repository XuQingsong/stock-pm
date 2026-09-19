"""FULL REVIEW vs INCREMENTAL UPDATE scoping."""

from __future__ import annotations

from typing import Any

FULL_TRIGGERS = (
    "earnings",
    "guidance",
    "mna",
    "regulation",
    "major_customer",
    "base_case",
    "periodic",
    "manual",
    "first_run",
    "structural",
)
FULL_EVENT_TYPES = ("earnings", "guidance", "mna", "regulation")


def should_full_review(
    *,
    prior_drivers: list[dict[str, Any]] | None = None,
    prior_claims: list[dict[str, Any]] | None = None,
    trigger: str | None = None,
    mode: str | None = None,
    event: dict[str, Any] | None = None,
) -> bool:
    if str(mode or "").lower() == "full":
        return True
    if not prior_drivers or not prior_claims:
        return True
    reason = full_review_reason(trigger=trigger, event=event, mode=mode)
    return reason is not None


def full_review_reason(
    *,
    trigger: str | None = None,
    event: dict[str, Any] | None = None,
    mode: str | None = None,
) -> str | None:
    if str(mode or "").lower() == "full":
        return "manual"
    token = str(trigger or "").lower()
    if token == "first_run":
        # first_run is Cold-Start Bootstrap, not a recurring Full Review.
        return None
    if token in FULL_TRIGGERS:
        return token
    item = event or {}
    event_type = str(item.get("event_type") or "").lower()
    if event_type in FULL_EVENT_TYPES:
        return event_type
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    if any(word in blob for word in ("earnings", "10-q", "10-k", "quarterly results")):
        return "earnings"
    if "guidance" in blob:
        return "guidance"
    if any(word in blob for word in ("acquire", "merger", "m&a", "takeover")):
        return "mna"
    if any(word in blob for word in ("regulator", "doj", "antitrust", "ban")):
        return "regulation"
    return None


_CRITIC_HIGH_VALUE = {
    "claim",
    "core_claim",
    "state",
    "company_state",
    "industry_state",
    "macro_state",
    "driver",
    "value_driver",
    "causal_edge",
    "causal_relationship",
    "scenario",
    "financial_impact",
}
_CRITIC_SKIP = {
    "market_attention",
    "price_reaction",
    "expectation",
    "expectation_state",
    "market_driver_hypothesis",
    "market_driver",
    "research_question",
    "causal_gap",
    "price_fundamental_divergence",
    "price_feedback",
    "shadow_state",
    "shadow",
}
_IDENTITY_FIELDS = ("statement", "status", "current_state", "direction", "name", "title")


def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("to_payload") if isinstance(row.get("to_payload"), dict) else row.get("to")
    return dict(raw) if isinstance(raw, dict) else {}


def _from_of(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("from_payload") if isinstance(row.get("from_payload"), dict) else row.get("from")
    return dict(raw) if isinstance(raw, dict) else {}


def _identity_changed(row: dict[str, Any]) -> bool:
    now = _from_of(row)
    nxt = _payload_of(row)
    return any(field in nxt and str(nxt.get(field) or "") != str(now.get(field) or "") for field in _IDENTITY_FIELDS)


def critic_is_needed(
    *,
    proposals: list[dict[str, Any]] | None = None,
    approved: list[dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
) -> bool:
    """Full Critic only for high-value writes. Market / RQ / Divergence skip."""
    if critic_should_expand(proposals=proposals, budget=budget):
        return True
    source = approved if approved is not None else proposals
    rows = [row for row in (source or []) if isinstance(row, dict)]
    for row in rows:
        target = str(row.get("object_type") or "")
        if target in _CRITIC_SKIP:
            continue
        if target not in _CRITIC_HIGH_VALUE:
            continue
        payload = _payload_of(row)
        if target in {"causal_edge", "causal_relationship"} and str(payload.get("status") or "") in {"supported", "established"}:
            return True
        if target == "scenario" and (
            payload.get("base_case_change") is True or str(payload.get("scope") or "") == "base"
        ):
            return True
        if _identity_changed(row):
            return True
        if target in {"claim", "core_claim", "state", "company_state", "driver", "value_driver"} and _identity_changed(row):
            return True
    return False


def critic_should_expand(
    *,
    proposals: list[dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
) -> bool:
    rows = [row for row in (proposals or []) if isinstance(row, dict)]
    claims = [row for row in rows if str(row.get("object_type") or "") in {"claim", "core_claim"}]
    bases = [
        row
        for row in rows
        if str(row.get("object_type") or "") == "scenario"
        and (
            (row.get("to_payload") or {}).get("base_case_change") is True
            or str((row.get("to_payload") or {}).get("scope") or "") == "base"
        )
    ]
    if len(claims) > 1 or bases:
        return True
    if (budget or {}).get("abnormal_change_scope"):
        return True
    return False


def affected_scope(
    *,
    events: list[dict[str, Any]],
    transmissions: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, list[str]]:
    driver_ids: list[str] = []
    claim_ids: list[str] = []
    state_ids: list[str] = []
    for row in transmissions or []:
        for item in row.get("affected_drivers") or []:
            key = str(item)
            if key not in driver_ids:
                driver_ids.append(key)
        for item in row.get("affected_claims") or []:
            key = str(item)
            if key not in claim_ids:
                claim_ids.append(key)
        for item in row.get("affected_states") or []:
            key = str(item)
            if key not in state_ids:
                state_ids.append(key)
    for event in events or []:
        if str(event.get("materiality") or "") != "material":
            continue
        for item in event.get("affected_drivers") or []:
            if str(item) not in driver_ids:
                driver_ids.append(str(item))
        for item in event.get("affected_claims") or []:
            if str(item) not in claim_ids:
                claim_ids.append(str(item))
    if not driver_ids and not claim_ids:
        return {"drivers": [], "claims": [], "states": state_ids, "touched": False}
    return {"drivers": driver_ids, "claims": claim_ids, "states": state_ids, "touched": True}
