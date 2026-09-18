"""FULL REVIEW vs INCREMENTAL UPDATE scoping."""

from __future__ import annotations

from typing import Any

FULL_TRIGGERS = ("earnings", "guidance", "structural", "first_run", "periodic")


def should_full_review(
    *,
    prior_drivers: list[dict[str, Any]] | None,
    prior_claims: list[dict[str, Any]] | None,
    trigger: str | None = None,
    mode: str | None = None,
) -> bool:
    if str(mode or "").lower() == "full":
        return True
    if str(mode or "").lower() == "incremental":
        return False
    if not prior_drivers or not prior_claims:
        return True
    if str(trigger or "").lower() in FULL_TRIGGERS:
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
