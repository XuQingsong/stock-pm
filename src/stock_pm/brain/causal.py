"""Causal edges are slow. Candidate edges cannot transmit impact downward."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import CAUSAL_EDGE_STATUSES, TRANSMITTABLE_EDGE_STATUSES


def normalize_causal_edge(raw: dict[str, Any], *, ticker: str) -> dict[str, Any] | None:
    source = compact_text(raw.get("from_node") or raw.get("source") or "", 80)
    target = compact_text(raw.get("to_node") or raw.get("target") or "", 80)
    if not source or not target:
        return None
    status = str(raw.get("status") or "candidate")
    if status not in CAUSAL_EDGE_STATUSES:
        status = "candidate"
    return {
        "edge_id": raw.get("edge_id") or new_id("bced"),
        "ticker": str(ticker).upper(),
        "from_node": source,
        "to_node": target,
        "statement": compact_text(raw.get("statement") or f"{source} -> {target}", 200),
        "status": status,
        "evidence_ids": [str(item) for item in (raw.get("evidence_ids") or []) if str(item).strip()],
    }


def edge_can_transmit(edge: dict[str, Any] | None) -> bool:
    return str((edge or {}).get("status") or "candidate") in TRANSMITTABLE_EDGE_STATUSES


def transmission_stop_reason(edges: list[dict[str, Any]] | None) -> str | None:
    for edge in edges or []:
        if not edge_can_transmit(edge):
            return f"unsupported_causal_edge:{edge.get('edge_id') or edge.get('from_node')}:{edge.get('status') or 'candidate'}"
    return None


def transmit_path(edges: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Walk a causal path. Candidate / challenged / deprecated edges stop transmission."""
    transmitted: list[dict[str, Any]] = []
    for edge in edges or []:
        if not edge_can_transmit(edge):
            return {
                "transmitted": transmitted,
                "stopped": True,
                "stopped_at": edge,
                "reached_claim": False,
                "reason": transmission_stop_reason([edge]),
            }
        transmitted.append(edge)
    reached = any(str(edge.get("to_node") or "").lower() in {"claim", "core_claim", "eps"} for edge in transmitted)
    return {"transmitted": transmitted, "stopped": False, "stopped_at": None, "reached_claim": reached, "reason": None}
