"""Lightweight runtime trace for run_brain_update. JSON, no UI."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text


def _ids(rows: list[dict[str, Any]] | None, *keys: str) -> list[str]:
    out: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = row.get(key)
            if value:
                token = str(value)
                if token not in out:
                    out.append(token)
                break
    return out


def _usage(llm_calls: list[dict[str, Any]] | None) -> dict[str, Any]:
    calls = list(llm_calls or [])
    inp = sum(int(row.get("input_tokens") or 0) for row in calls)
    out = sum(int(row.get("output_tokens") or 0) for row in calls)
    latency = sum(int(row.get("latency_ms") or 0) for row in calls)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "latency_ms": latency,
        "calls": [
            {
                "step": row.get("step"),
                "role": row.get("role"),
                "model": row.get("model"),
                "llm_called": row.get("llm_called"),
                "llm_status": row.get("llm_status"),
                "input_tokens": row.get("input_tokens"),
                "output_tokens": row.get("output_tokens"),
                "latency_ms": row.get("latency_ms"),
                "error": compact_text(str(row.get("error") or ""), 160) or None,
            }
            for row in calls
        ],
    }


def _decisions(gate: dict[str, Any] | None) -> dict[str, Any]:
    payload = gate or {}
    approved = list(payload.get("approved") or [])
    rejected = list(payload.get("rejected") or [])
    review = list(payload.get("requires_review") or [])
    return {
        "approve": len(approved),
        "reject": len(rejected),
        "requires_review": len(review),
        "items": [
            {
                "proposal_id": row.get("proposal_id"),
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "decision": row.get("decision"),
                "reason_code": row.get("reason_code") or ((row.get("rules") or [{}])[0].get("rule") if row.get("rules") else ""),
                "reason": compact_text(row.get("reason") or "", 200),
            }
            for row in approved + rejected + review
        ],
    }


def build_runtime_trace(
    *,
    result: dict[str, Any],
    item: dict[str, Any] | None = None,
    elapsed_ms: int | None = None,
    full_brain_size: int | None = None,
) -> dict[str, Any]:
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    extract = result.get("extract") if isinstance(result.get("extract"), dict) else {}
    l0 = result.get("l0") if isinstance(result.get("l0"), dict) else {}
    materiality = result.get("materiality") if isinstance(result.get("materiality"), dict) else {}
    affected = result.get("affected") if isinstance(result.get("affected"), dict) else {}
    critic = result.get("critic") if isinstance(result.get("critic"), dict) else {}
    usage = _usage(result.get("llm_calls"))
    decisions = _decisions(gate)
    snap_objects = {
        "states": _ids(snapshot.get("states"), "state_id", "name"),
        "drivers": _ids(snapshot.get("drivers"), "driver_id", "canonical_key", "name"),
        "claims": _ids(snapshot.get("claims"), "claim_id", "title"),
        "exposures": _ids(snapshot.get("exposures"), "exposure_id", "exposure_type"),
        "shadows": _ids(snapshot.get("shadows"), "shadow_id", "name"),
        "causal_edges": _ids(snapshot.get("causal_edges"), "edge_id", "from_node"),
    }
    snap_size = (
        len(snapshot.get("states") or [])
        + len(snapshot.get("drivers") or [])
        + len(snapshot.get("claims") or [])
        + len(snapshot.get("evidence") or [])
        + len(snapshot.get("counter_evidence") or [])
        + len(snapshot.get("history") or [])
        + len(snapshot.get("causal_edges") or [])
    )
    changed = []
    for row in gate.get("approved") or []:
        if gate.get("auto_commit_allowed"):
            changed.append(f"{row.get('object_type')}:{row.get('object_id') or row.get('object_type')}")
    for row in result.get("gate", {}).get("committed") or [] if isinstance(result.get("gate"), dict) else []:
        if row.get("kind") in {"shadow", "question"}:
            changed.append(f"{row.get('kind')}:{row.get('shadow_id') or row.get('question_id') or row.get('name')}")
    for row in result.get("committed") if isinstance(result.get("committed"), list) else []:
        pass
    if isinstance(gate, dict):
        for row in gate.get("committed") or []:
            kind = row.get("kind")
            if kind in {"shadow", "question"}:
                token = f"{kind}:{row.get('shadow_id') or row.get('question_id') or row.get('name')}"
                if token not in changed:
                    changed.append(token)
    reduction = None
    if full_brain_size and snap_size is not None:
        reduction = round(1 - (snap_size / max(full_brain_size, 1)), 4)
    event_id = str((item or {}).get("event_id") or l0.get("item", {}).get("event_id") or result.get("event_id") or new_id("bev"))
    latency = elapsed_ms if elapsed_ms is not None else usage["latency_ms"]
    return {
        "event_id": event_id,
        "ticker": result.get("ticker"),
        "path": result.get("path"),
        "l0": {
            "duplicate": bool(result.get("duplicate") or l0.get("duplicate")),
            "stop": bool(result.get("stopped") and result.get("path") == "l0_stop"),
            "stop_reason": result.get("stop_reason") or l0.get("stop_reason"),
            "fingerprint": l0.get("fingerprint") or l0.get("event_hash"),
            "source_tier": l0.get("source_tier"),
            "event_type": l0.get("event_type"),
        },
        "duplicate": bool(result.get("duplicate") or l0.get("duplicate")),
        "l1_event_type": extract.get("event_type") or l0.get("event_type") or (item or {}).get("event_type"),
        "novelty": extract.get("novelty") or (item or {}).get("novelty"),
        "materiality": bool(result.get("material")),
        "materiality_reason": materiality.get("reason") or result.get("stop_reason") or result.get("full_review_reason"),
        "affected_objects": affected,
        "snapshot_objects": snap_objects,
        "snapshot_evidence_count": len(snapshot.get("evidence") or []),
        "snapshot_counter_evidence_count": len(snapshot.get("counter_evidence") or []),
        "snapshot_history_count": len(snapshot.get("history") or []),
        "snapshot_size": snap_size,
        "full_brain_size": full_brain_size,
        "snapshot_reduction": reduction,
        "glm53_called": bool(result.get("glm53_called")),
        "glm52_called": bool(result.get("glm52_called")),
        "proposal_count": len(result.get("proposals") or []),
        "proposal_decisions": decisions,
        "changed_objects": changed,
        "critic_scope": critic.get("scope") or ("skipped" if not result.get("critic_called") else "unknown"),
        "full_review_triggered": bool(result.get("full_review")),
        "full_review_reason": result.get("full_review_reason"),
        "token_usage": usage,
        "latency_ms": latency,
        "current_state_unchanged": result.get("current_state_unchanged"),
        "core_claims_unchanged": result.get("core_claims_unchanged"),
        "extract_fact": compact_text(extract.get("fact") or "", 240),
        "extract_entities": list(extract.get("entities") or [])[:8],
    }
