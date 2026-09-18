"""Ordinary events cannot rewrite large parts of the Brain in one pass."""

from __future__ import annotations

from typing import Any

from .types import CHANGE_BUDGET


def _is_base(proposal: dict[str, Any]) -> bool:
    target = str(proposal.get("object_type") or "")
    payload = proposal.get("to_payload") if isinstance(proposal.get("to_payload"), dict) else {}
    return target == "scenario" and (
        payload.get("base_case_change") is True or str(payload.get("scope") or "") == "base"
    )


def change_scope(proposals: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [row for row in (proposals or []) if isinstance(row, dict)]
    claims = [row for row in rows if str(row.get("object_type") or "") in {"claim", "core_claim"}]
    drivers = [row for row in rows if str(row.get("object_type") or "") in {"driver", "value_driver"}]
    edges = [row for row in rows if str(row.get("object_type") or "") in {"causal_edge", "causal_relationship"}]
    bases = [row for row in rows if _is_base(row)]
    over = (
        len(claims) > CHANGE_BUDGET["max_auto_claims"]
        or len(drivers) > CHANGE_BUDGET["max_auto_drivers"]
        or len(bases) > CHANGE_BUDGET["max_auto_base"]
        or len(edges) > CHANGE_BUDGET["max_auto_causal_edges"]
    )
    return {
        "claim_count": len(claims),
        "driver_count": len(drivers),
        "base_count": len(bases),
        "causal_edge_count": len(edges),
        "abnormal_change_scope": over,
        "requires_review": over,
        "auto_commit_allowed": not over,
    }
