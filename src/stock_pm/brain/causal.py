"""Causal edges are a relationship layer over existing Brain objects.

Candidate / challenged / deprecated edges cannot transmit impact downward.
New edges start as candidate. Established is never a first write.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import (
    CAUSAL_EDGE_STATUS_RANK,
    CAUSAL_EDGE_STATUSES,
    CAUSAL_RELATIONSHIP_TYPES,
    CONFIDENCE,
    HORIZONS,
    LINK_STRENGTHS,
    TRANSMISSION_MAX_STEPS,
    TRANSMITTABLE_EDGE_STATUSES,
)

_NODE_KEYS = (
    "state_id",
    "driver_id",
    "claim_id",
    "exposure_id",
    "event_id",
    "canonical_key",
    "object_id",
    "edge_id",
)


def _ids_of(row: dict[str, Any] | None) -> set[str]:
    item = row or {}
    out = {str(item.get(key) or "") for key in _NODE_KEYS}
    if item.get("name"):
        out.add(str(item.get("name")))
    if item.get("from_node"):
        out.add(str(item.get("from_node")))
    if item.get("to_node"):
        out.add(str(item.get("to_node")))
    out.discard("")
    return out


def _status(value: Any) -> str:
    text = str(value or "candidate")
    return text if text in CAUSAL_EDGE_STATUSES else "candidate"


def normalize_causal_edge(raw: dict[str, Any], *, ticker: str) -> dict[str, Any] | None:
    source = compact_text(raw.get("from_node") or raw.get("source") or "", 80)
    target = compact_text(raw.get("to_node") or raw.get("target") or "", 80)
    if not source or not target:
        return None
    rel = str(raw.get("relationship_type") or raw.get("relationship") or "other")
    if rel not in CAUSAL_RELATIONSHIP_TYPES:
        rel = "other"
    status = _status(raw.get("status"))
    strength = str(raw.get("strength") or "medium")
    if strength not in LINK_STRENGTHS:
        strength = "medium"
    confidence = str(raw.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    horizon = str(raw.get("time_horizon") or "medium")
    if horizon not in HORIZONS:
        horizon = "medium"
    support = [str(item) for item in (raw.get("support_evidence_ids") or raw.get("evidence_ids") or []) if str(item).strip()]
    counter = [str(item) for item in (raw.get("counter_evidence_ids") or []) if str(item).strip()]
    return {
        "edge_id": raw.get("edge_id") or new_id("bced"),
        "ticker": str(ticker).upper(),
        "from_node": source,
        "to_node": target,
        "from_type": compact_text(raw.get("from_type") or raw.get("source_type") or "", 40),
        "to_type": compact_text(raw.get("to_type") or raw.get("target_type") or "", 40),
        "relationship_type": rel,
        "mechanism": compact_text(raw.get("mechanism") or raw.get("statement") or f"{source} -> {target}", 400),
        "statement": compact_text(raw.get("statement") or raw.get("mechanism") or f"{source} -> {target}", 200),
        "direction": compact_text(raw.get("direction") or "positive", 20) or "positive",
        "strength": strength,
        "confidence": confidence,
        "time_horizon": horizon,
        "lag": compact_text(raw.get("lag") or "unknown", 40) or "unknown",
        "conditions": compact_text(raw.get("conditions") or "", 240),
        "support_evidence_ids": support,
        "counter_evidence_ids": counter,
        "evidence_ids": support,
        "status": status,
        "support_strength": int(raw.get("support_strength") or len(support)),
        "counter_strength": int(raw.get("counter_strength") or len(counter)),
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
    reached = any(
        str(edge.get("to_type") or edge.get("to_node") or "").lower() in {"claim", "core_claim", "eps"}
        or "bclm_" in str(edge.get("to_node") or "")
        for edge in transmitted
    )
    return {"transmitted": transmitted, "stopped": False, "stopped_at": None, "reached_claim": reached, "reason": None}


def accumulate_edge_evidence(edge: dict[str, Any] | None, *, direction: str, strength: str = "medium") -> dict[str, Any]:
    row = dict(edge or {})
    bump = 2 if strength == "strong" else 1 if strength == "medium" else 0
    if direction == "oppose":
        row["counter_strength"] = int(row.get("counter_strength") or 0) + bump
        row["counter_trend"] = "up"
    else:
        row["support_strength"] = int(row.get("support_strength") or 0) + bump
        row["support_trend"] = "up"
    return row


def next_edge_status(
    current: dict[str, Any] | None,
    proposed_status: str | None,
    *,
    independent_support_count: int = 0,
    independent_counter_count: int = 0,
    source_kind: str | None = None,
    is_new: bool = False,
) -> dict[str, Any]:
    now = _status((current or {}).get("status") if current else "candidate")
    want = _status(proposed_status or now)
    if is_new:
        return {"status": "candidate", "changed": True, "reason": "new_causal_edge_starts_candidate"}
    if now == "established" and (want == "challenged" or independent_counter_count >= 1):
        return {"status": "challenged", "changed": now != "challenged", "reason": "counter_evidence_challenges_edge"}
    current_rank = CAUSAL_EDGE_STATUS_RANK.get(now, 2)
    want_rank = CAUSAL_EDGE_STATUS_RANK.get(want, 2)
    delta = want_rank - current_rank
    news_like = str(source_kind or "") in {"news", "event", "price", "signal", "rumor"}
    if news_like and want_rank >= CAUSAL_EDGE_STATUS_RANK["supported"] and independent_support_count < 2:
        stepped = "observed" if now == "candidate" else now
        return {"status": stepped, "changed": stepped != now, "reason": "edge_hysteresis_single_item"}
    if abs(delta) > 1:
        stepped_rank = current_rank + (1 if delta > 0 else -1)
        status = next((key for key, rank in CAUSAL_EDGE_STATUS_RANK.items() if rank == stepped_rank), now)
        return {"status": status, "changed": status != now, "reason": "edge_hysteresis_one_step"}
    return {"status": want, "changed": want != now, "reason": "edge_status_allowed"}


def _adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges or []:
        src = str(edge.get("from_node") or "")
        if src:
            out[src].append(edge)
    return out


def shortest_path(
    edges: list[dict[str, Any]] | None,
    *,
    start_ids: set[str],
    goal_ids: set[str],
    transmittable_only: bool = False,
) -> dict[str, Any]:
    starts = {str(item) for item in start_ids if str(item)}
    goals = {str(item) for item in goal_ids if str(item)}
    if not starts or not goals:
        return {"found": False, "nodes": [], "edges": [], "stopped": False, "stopped_at": None, "reason": "missing_endpoints"}
    if starts & goals:
        return {"found": True, "nodes": [next(iter(starts & goals))], "edges": [], "stopped": False, "stopped_at": None, "reason": None}
    adj = _adjacency(list(edges or []))
    queue: deque[str] = deque(starts)
    prev: dict[str, tuple[str, dict[str, Any]]] = {}
    seen = set(starts)
    blocked_at: dict[str, Any] | None = None
    while queue:
        node = queue.popleft()
        for edge in adj.get(node) or []:
            nxt = str(edge.get("to_node") or "")
            if not nxt or nxt in seen:
                continue
            if transmittable_only and not edge_can_transmit(edge):
                blocked_at = edge
                continue
            if not transmittable_only and not edge_can_transmit(edge):
                blocked_at = edge
                seen.add(nxt)
                prev[nxt] = (node, edge)
                if nxt in goals:
                    nodes, path_edges = _reconstruct(prev, nxt, starts)
                    walked = transmit_path(path_edges)
                    return {
                        "found": False,
                        "nodes": nodes,
                        "edges": path_edges,
                        "stopped": True,
                        "stopped_at": walked.get("stopped_at") or edge,
                        "reason": walked.get("reason") or transmission_stop_reason([edge]),
                    }
                continue
            seen.add(nxt)
            prev[nxt] = (node, edge)
            if nxt in goals:
                nodes, path_edges = _reconstruct(prev, nxt, starts)
                walked = transmit_path(path_edges)
                return {
                    "found": not walked["stopped"],
                    "nodes": nodes,
                    "edges": path_edges,
                    "stopped": walked["stopped"],
                    "stopped_at": walked.get("stopped_at"),
                    "reason": walked.get("reason"),
                    "reached_claim": any(item in goals and ("bclm_" in item or item in goals) for item in nodes),
                }
            if len(seen) > 80:
                break
            queue.append(nxt)
    reason = "transmission_stop" if blocked_at else "causal_gap"
    return {
        "found": False,
        "nodes": [],
        "edges": [],
        "stopped": bool(blocked_at),
        "stopped_at": blocked_at,
        "reason": transmission_stop_reason([blocked_at]) if blocked_at else reason,
    }


def _reconstruct(prev: dict[str, tuple[str, dict[str, Any]]], goal: str, starts: set[str]) -> tuple[list[str], list[dict[str, Any]]]:
    nodes = [goal]
    edges: list[dict[str, Any]] = []
    cur = goal
    guard = 0
    while cur not in starts and cur in prev and guard < TRANSMISSION_MAX_STEPS + 2:
        parent, edge = prev[cur]
        edges.append(edge)
        nodes.append(parent)
        cur = parent
        guard += 1
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def event_anchor_ids(
    *,
    event: dict[str, Any] | None,
    exposures: list[dict[str, Any]] | None = None,
    states: list[dict[str, Any]] | None = None,
) -> set[str]:
    item = event or {}
    anchors: set[str] = set()
    for key in ("event_id", "subject", "event_key"):
        if item.get(key):
            anchors.add(str(item.get(key)))
    entities = [str(value).strip().lower() for value in (item.get("entities") or []) if str(value).strip()]
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {' '.join(entities)}".lower()
    for row in list(exposures or []) + list(states or []):
        text = " ".join(str(row.get(key) or "") for key in ("name", "object_name", "subject", "statement", "reason", "exposure_type")).lower()
        ids = _ids_of(row)
        if any(ent and ent in text for ent in entities if len(ent) > 3):
            anchors |= ids
        elif any(token in text for token in ("customer", "hyperscaler", "asic", "exposure") if token in blob):
            if str(row.get("exposure_type") or "") in {"customer", "competitive", "product"} or row.get("state_id"):
                anchors |= ids
    return {item for item in anchors if item}


def relevant_causal_subgraph(
    *,
    edges: list[dict[str, Any]] | None,
    object_ids: set[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    wanted = {str(item) for item in object_ids if str(item)}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges or []:
        ends = {str(edge.get("from_node") or ""), str(edge.get("to_node") or "")}
        token = str(edge.get("edge_id") or f"{edge.get('from_node')}->{edge.get('to_node')}")
        if ends & wanted and token not in seen:
            seen.add(token)
            out.append(edge)
        if len(out) >= limit:
            break
    return out


def claim_causal_paths(
    *,
    claim_id: str,
    edges: list[dict[str, Any]] | None,
    start_ids: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    rows = list(edges or [])
    reverse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in rows:
        reverse[str(edge.get("to_node") or "")].append(edge)
    paths: list[dict[str, Any]] = []
    starts = {str(item) for item in (start_ids or set()) if str(item)}
    queue: deque[tuple[str, list[str], list[dict[str, Any]]]] = deque([(claim_id, [claim_id], [])])
    seen_nodes = {claim_id}
    while queue and len(paths) < limit:
        node, nodes, path_edges = queue.popleft()
        parents = reverse.get(node) or []
        if not parents:
            if len(nodes) > 1:
                walked = transmit_path(list(reversed(path_edges)))
                paths.append(
                    {
                        "nodes": list(reversed(nodes)),
                        "edges": list(reversed(path_edges)),
                        "stopped": walked["stopped"],
                        "reason": walked.get("reason"),
                        "claim_id": claim_id,
                    }
                )
            continue
        for edge in parents:
            src = str(edge.get("from_node") or "")
            if not src or src in nodes:
                continue
            nxt_nodes = nodes + [src]
            nxt_edges = path_edges + [edge]
            if src in starts or len(nxt_nodes) >= TRANSMISSION_MAX_STEPS:
                walked = transmit_path(list(reversed(nxt_edges)))
                paths.append(
                    {
                        "nodes": list(reversed(nxt_nodes)),
                        "edges": list(reversed(nxt_edges)),
                        "stopped": walked["stopped"],
                        "reason": walked.get("reason"),
                        "claim_id": claim_id,
                    }
                )
                if len(paths) >= limit:
                    break
                continue
            if src not in seen_nodes:
                seen_nodes.add(src)
                queue.append((src, nxt_nodes, nxt_edges))
    return paths[:limit]


def detect_causal_gaps(
    *,
    event: dict[str, Any] | None,
    edges: list[dict[str, Any]] | None,
    related_claims: list[dict[str, Any]] | None,
    related_drivers: list[dict[str, Any]] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    states: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    graph = list(edges or [])
    if not graph:
        return []
    anchors = event_anchor_ids(event=event, exposures=exposures, states=states)
    if not anchors:
        title = compact_text((event or {}).get("title") or (event or {}).get("fact") or "this event", 80)
        anchors = {title}
    gaps: list[dict[str, Any]] = []
    targets = list(related_claims or []) + list(related_drivers or [])
    for row in targets[:6]:
        goal = str(row.get("claim_id") or row.get("driver_id") or row.get("canonical_key") or "")
        if not goal:
            continue
        walked = shortest_path(graph, start_ids=anchors, goal_ids={goal})
        if walked.get("found"):
            continue
        if walked.get("stopped"):
            continue
        label = row.get("title") or row.get("name") or goal
        event_label = compact_text((event or {}).get("title") or (event or {}).get("fact") or "the event", 80)
        gaps.append(
            {
                "from_node": next(iter(anchors)),
                "to_node": goal,
                "kind": "causal_gap",
                "reason": walked.get("reason") or "causal_gap",
                "question": f"How exposed is the issuer to {event_label}, such that it would move {label}?",
                "related_objects": [goal, event_label],
            }
        )
        if len(gaps) >= 2:
            break
    return gaps


def compact_path(path: dict[str, Any] | None) -> dict[str, Any]:
    row = path or {}
    return {
        "nodes": list(row.get("nodes") or [])[:8],
        "edge_ids": [str(edge.get("edge_id") or f"{edge.get('from_node')}->{edge.get('to_node')}") for edge in (row.get("edges") or [])][:8],
        "statuses": [str(edge.get("status") or "") for edge in (row.get("edges") or [])][:8],
        "stopped": bool(row.get("stopped")),
        "reason": row.get("reason"),
        "claim_id": row.get("claim_id"),
    }


def financial_edges_from_drivers(drivers: list[dict[str, Any]] | None, *, ticker: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in drivers or []:
        metric = str(row.get("financial_link") or "").strip()
        driver_id = str(row.get("driver_id") or row.get("canonical_key") or "")
        if not metric or not driver_id:
            continue
        edge = normalize_causal_edge(
            {
                "from_node": driver_id,
                "to_node": metric,
                "from_type": "value_driver",
                "to_type": "financial_metric",
                "relationship_type": "driver_to_financial",
                "mechanism": row.get("why_it_matters") or f"{driver_id} theoretically affects {metric}.",
                "direction": row.get("direction") or "positive",
                "status": "supported" if row.get("evidence_ids") else "candidate",
                "evidence_ids": list(row.get("evidence_ids") or []),
            },
            ticker=ticker,
        )
        if edge:
            out.append(edge)
    return out


def assess_event_transmissions(
    *,
    event: dict[str, Any] | None,
    edges: list[dict[str, Any]] | None,
    claims: list[dict[str, Any]] | None,
    exposures: list[dict[str, Any]] | None = None,
    states: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    graph = list(edges or [])
    anchors = event_anchor_ids(event=event, exposures=exposures, states=states)
    successful: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in claims or []:
        goal = str(row.get("claim_id") or "")
        if not goal:
            continue
        walked = shortest_path(graph, start_ids=anchors, goal_ids={goal})
        compact = compact_path({**walked, "claim_id": goal})
        if walked.get("found") and not walked.get("stopped"):
            successful.append(compact)
        elif walked.get("stopped"):
            blocked.append(compact)
    gaps = detect_causal_gaps(
        event=event,
        edges=graph,
        related_claims=claims,
        exposures=exposures,
        states=states,
    )
    return {
        "successful": successful,
        "blocked": blocked,
        "blocked_reasons": [str(row.get("reason") or "") for row in blocked],
        "gaps": gaps,
        "anchors": sorted(anchors),
        "successful_count": len(successful),
        "blocked_count": len(blocked),
    }
