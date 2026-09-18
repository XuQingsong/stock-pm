"""Audit whether targeted snapshot omitted highly related Brain objects.

Records context_miss. Does not widen the snapshot.
"""

from __future__ import annotations

from typing import Any

from .claim_integrity import token_overlap
from .shadow import current_states_only, is_shadow_object


def _blob(row: dict[str, Any] | None) -> str:
    item = row or {}
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "fact",
            "statement",
            "name",
            "canonical_key",
            "subject",
            "claim_subject",
            "current_state",
            "from_node",
            "to_node",
            "reason",
            "new_fact",
        )
    ).lower()


def _event_blob(event: dict[str, Any] | None) -> str:
    item = event or {}
    return f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''} {' '.join(str(x) for x in (item.get('entities') or []))}".lower()


def _row_id(row: dict[str, Any], kind: str) -> str:
    return str(
        row.get("state_id")
        or row.get("driver_id")
        or row.get("claim_id")
        or row.get("evidence_id")
        or row.get("id")
        or row.get("history_id")
        or row.get("edge_id")
        or row.get("name")
        or row.get("title")
        or kind
    )


def _in_snapshot(row: dict[str, Any], snapshot: dict[str, Any], kind: str) -> bool:
    token = _row_id(row, kind)
    buckets = {
        "state": snapshot.get("states") or [],
        "driver": snapshot.get("drivers") or [],
        "claim": snapshot.get("claims") or [],
        "evidence": (snapshot.get("evidence") or []) + (snapshot.get("counter_evidence") or []),
        "history": snapshot.get("history") or [],
        "causal_edge": snapshot.get("causal_edges") or [],
    }
    for item in buckets.get(kind) or []:
        if _row_id(item, kind) == token:
            return True
        if kind == "evidence" and str(item.get("id") or item.get("evidence_id") or "") in {
            str(row.get("id") or ""),
            str(row.get("evidence_id") or ""),
        }:
            return True
    return False


def _related(event_blob: str, row: dict[str, Any]) -> dict[str, Any] | None:
    text = _blob(row)
    if not text or not event_blob:
        return None
    score = token_overlap(event_blob, text)
    keywords = [part for part in event_blob.replace("-", " ").split() if len(part) > 4]
    hits = [word for word in keywords if word in text]
    important = (
        "customer",
        "hyperscaler",
        "google",
        "openai",
        "anthropic",
        "meta",
        "marvell",
        "demand",
        "durability",
        "concentration",
        "order",
        "asic",
        "accelerator",
        "guidance",
        "margin",
        "earnings",
    )
    important_hits = [word for word in important if word in event_blob and word in text]
    if score >= 0.22 or len(important_hits) >= 1 or len(hits) >= 3:
        return {"score": round(score, 3), "keyword_hits": important_hits or hits[:6]}
    return None


def find_context_misses(
    *,
    event: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    brain: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Highly related Brain objects that GLM-5.3 did not receive."""
    shot = snapshot or {}
    context = brain or {}
    event_blob = _event_blob(event)
    misses: list[dict[str, Any]] = []
    checks = (
        ("state", current_states_only(context.get("states"))),
        ("driver", context.get("drivers") or []),
        ("claim", context.get("claims") or []),
        ("evidence", context.get("evidence") or []),
        ("history", context.get("history") or []),
        ("causal_edge", context.get("causal_edges") or []),
    )
    for kind, rows in checks:
        for row in rows:
            if not isinstance(row, dict) or is_shadow_object(row):
                continue
            if _in_snapshot(row, shot, kind):
                continue
            related = _related(event_blob, row)
            if not related:
                continue
            misses.append(
                {
                    "kind": kind,
                    "object_id": _row_id(row, kind),
                    "label": row.get("name") or row.get("title") or row.get("canonical_key") or row.get("fact") or row.get("statement") or "",
                    "why": "Related Brain object was not in the targeted snapshot.",
                    "score": related["score"],
                    "keyword_hits": related["keyword_hits"],
                }
            )
    return misses
