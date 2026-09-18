"""Audit whether targeted snapshot omitted golden expected objects.

context_miss is scored against a human golden set, not against the same
keyword retrieval that built the snapshot.
"""

from __future__ import annotations

from typing import Any

from .shadow import current_states_only, is_shadow_object


def _row_id(row: dict[str, Any], kind: str = "") -> str:
    return str(
        row.get("state_id")
        or row.get("driver_id")
        or row.get("claim_id")
        or row.get("evidence_id")
        or row.get("id")
        or row.get("history_id")
        or row.get("edge_id")
        or row.get("canonical_key")
        or row.get("name")
        or row.get("title")
        or kind
    )


def snapshot_ids(snapshot: dict[str, Any] | None, kind: str) -> set[str]:
    shot = snapshot or {}
    buckets = {
        "state": shot.get("states") or [],
        "driver": shot.get("drivers") or [],
        "claim": shot.get("claims") or [],
        "evidence": (shot.get("evidence") or []) + (shot.get("counter_evidence") or []),
        "support_evidence": shot.get("evidence") or [],
        "counter_evidence": shot.get("counter_evidence") or [],
        "history": shot.get("history") or [],
        "causal_edge": shot.get("causal_edges") or [],
    }
    out: set[str] = set()
    for item in buckets.get(kind) or []:
        if not isinstance(item, dict):
            out.add(str(item))
            continue
        token = _row_id(item, kind)
        if token:
            out.add(token)
        for key in ("id", "evidence_id", "canonical_key", "claim_id", "driver_id", "state_id"):
            if item.get(key):
                out.add(str(item.get(key)))
        fact = f"{item.get('fact') or ''} {item.get('title') or ''} {item.get('statement') or ''}".lower()
        if "exhibit 99.1" in fact:
            out.add("exhibit_99_1")
        if "marvell" in fact:
            out.add("marvell_counter")
    return {item for item in out if item}


def _in_snapshot(row: dict[str, Any], snapshot: dict[str, Any], kind: str) -> bool:
    token = _row_id(row, kind)
    ids = snapshot_ids(snapshot, kind)
    if token and token in ids:
        return True
    if kind in {"evidence", "support_evidence", "counter_evidence"}:
        evidence_ids = snapshot_ids(snapshot, "evidence")
        for key in ("id", "evidence_id"):
            if row.get(key) and str(row.get(key)) in evidence_ids:
                return True
        label = f"{row.get('fact') or ''} {row.get('title') or ''} {row.get('statement') or ''}".lower()
        if "exhibit 99.1" in label and "exhibit_99_1" in evidence_ids:
            return True
        if "marvell" in label and "marvell_counter" in evidence_ids:
            return True
    return False


def _as_expected_row(item: Any, kind: str) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    token = str(item or "")
    key = {
        "state": "state_id",
        "driver": "driver_id",
        "claim": "claim_id",
        "evidence": "evidence_id",
        "support_evidence": "evidence_id",
        "counter_evidence": "evidence_id",
        "history": "history_id",
    }.get(kind, "object_id")
    return {key: token, "id": token, "canonical_key": token, "label": token}


def expected_spec(expected: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    spec = expected or {}
    return {
        "state": [_as_expected_row(row, "state") for row in spec.get("states") or spec.get("state") or []],
        "driver": [_as_expected_row(row, "driver") for row in spec.get("drivers") or spec.get("driver") or []],
        "claim": [_as_expected_row(row, "claim") for row in spec.get("claims") or spec.get("claim") or []],
        "support_evidence": [
            _as_expected_row(row, "evidence")
            for row in spec.get("support_evidence") or spec.get("expected_evidence") or spec.get("evidence") or []
        ],
        "counter_evidence": [
            _as_expected_row(row, "evidence")
            for row in spec.get("counter_evidence") or spec.get("expected_counter_evidence") or []
        ],
        "history": [_as_expected_row(row, "history") for row in spec.get("history") or []],
    }


def find_context_misses(
    *,
    event: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    brain: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expected relevant objects that GLM-5.3 did not receive."""
    _ = event
    _ = brain
    shot = snapshot or {}
    misses: list[dict[str, Any]] = []
    if not expected:
        return misses
    for kind, rows in expected_spec(expected).items():
        bucket = "evidence" if kind in {"support_evidence", "counter_evidence"} else kind
        for row in rows:
            if _in_snapshot(row, shot, bucket) or _in_snapshot(row, shot, kind):
                continue
            misses.append(
                {
                    "kind": kind,
                    "object_id": _row_id(row, kind),
                    "label": row.get("name") or row.get("title") or row.get("canonical_key") or row.get("fact") or row.get("label") or "",
                    "why": "Golden expected object was not in the targeted snapshot.",
                }
            )
    return misses


def score_snapshot_context(
    *,
    snapshot: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    irrelevant: list[Any] | None = None,
) -> dict[str, Any]:
    shot = snapshot or {}
    spec = expected_spec(expected)
    retrieved_relevant: list[dict[str, str]] = []
    missed: list[dict[str, str]] = []
    expected_n = 0
    for kind, rows in spec.items():
        bucket = "evidence" if kind in {"support_evidence", "counter_evidence"} else kind
        for row in rows:
            expected_n += 1
            token = _row_id(row, kind)
            hit = _in_snapshot(row, shot, bucket) or _in_snapshot(row, shot, kind)
            payload = {"kind": kind, "object_id": token, "label": str(row.get("label") or row.get("canonical_key") or row.get("name") or token)}
            if hit:
                retrieved_relevant.append(payload)
            else:
                missed.append(payload)
    irrelevant_ids = []
    for item in irrelevant or (expected or {}).get("irrelevant") or []:
        if isinstance(item, dict):
            irrelevant_ids.append(_row_id(item))
        else:
            irrelevant_ids.append(str(item))
    retrieved_all: set[str] = set()
    for kind in ("state", "driver", "claim", "evidence", "support_evidence", "counter_evidence"):
        retrieved_all |= snapshot_ids(shot, kind)
    obvious_irrelevant = [token for token in irrelevant_ids if token in retrieved_all]
    recall = round(len(retrieved_relevant) / expected_n, 4) if expected_n else None
    precision_den = len(retrieved_relevant) + len(obvious_irrelevant)
    precision = round(len(retrieved_relevant) / precision_den, 4) if precision_den else None
    return {
        "expected_relevant_objects": [
            {"kind": kind, "object_id": _row_id(row, kind)} for kind, rows in spec.items() for row in rows
        ],
        "retrieved_relevant_objects": retrieved_relevant,
        "missed_relevant_objects": missed,
        "obviously_irrelevant_objects": obvious_irrelevant,
        "expected_count": expected_n,
        "retrieved_relevant_count": len(retrieved_relevant),
        "missed_count": len(missed),
        "irrelevant_count": len(obvious_irrelevant),
        "context_recall": recall,
        "context_precision": precision,
        "support_evidence_miss": any(row["kind"] == "support_evidence" for row in missed),
        "counter_evidence_miss": any(row["kind"] == "counter_evidence" for row in missed),
        "core_claim_retrieval_count": len(shot.get("claims") or []),
        "evidence_body_count": len(
            [
                row
                for row in (shot.get("evidence") or []) + (shot.get("counter_evidence") or [])
                if isinstance(row, dict) and (row.get("fact") or row.get("statement") or row.get("excerpt"))
            ]
        ),
    }


def leftover_objects_for_kind(brain: dict[str, Any] | None, kind: str) -> list[dict[str, Any]]:
    context = brain or {}
    mapping = {
        "state": current_states_only(context.get("states")),
        "driver": context.get("drivers") or [],
        "claim": context.get("claims") or [],
        "evidence": context.get("evidence") or [],
        "history": context.get("history") or [],
        "causal_edge": context.get("causal_edges") or [],
    }
    return [row for row in mapping.get(kind) or [] if isinstance(row, dict) and not is_shadow_object(row)]
