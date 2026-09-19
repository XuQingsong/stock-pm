"""Causal edges are a relationship layer over existing Brain objects.

Candidate / challenged / deprecated edges cannot transmit impact downward.
New edges start as candidate. Established is never a first write.
"""

from __future__ import annotations

import json
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


def _edge_as_dict(raw: Any) -> dict[str, Any] | None:
    """Accept a CausalEdge object, dict, or serialized JSON object. Reject bare ids / junk."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump") and callable(raw.model_dump):
        dumped = raw.model_dump()
        return dumped if isinstance(dumped, dict) else None
    if hasattr(raw, "dict") and callable(raw.dict):
        dumped = raw.dict()
        return dumped if isinstance(dumped, dict) else None
    if hasattr(raw, "__dict__") and not isinstance(raw, type):
        public = {key: value for key, value in vars(raw).items() if not str(key).startswith("_")}
        if public.get("from_node") or public.get("to_node") or public.get("source") or public.get("target"):
            return public
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            return parsed if isinstance(parsed, dict) else None
        return None
    return None


def coerce_causal_edge(raw: Any, *, ticker: str) -> dict[str, Any] | None:
    payload = _edge_as_dict(raw)
    if payload is None:
        return None
    return normalize_causal_edge(payload, ticker=ticker)


def coerce_causal_edges(raw: Any, *, ticker: str = "") -> list[dict[str, Any]]:
    """Normalize a mixed edge list. Illegal items are rejected, not crashed on."""
    if raw is None:
        return []
    rows = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    symbol = str(ticker or "").upper()
    for item in rows:
        edge = coerce_causal_edge(item, ticker=symbol or str((item or {}).get("ticker") if isinstance(item, dict) else "") or "UNK")
        if edge is None:
            continue
        token = str(edge.get("edge_id") or f"{edge.get('from_node')}->{edge.get('to_node')}")
        if token in seen:
            continue
        seen.add(token)
        out.append(edge)
    return out


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


def edge_can_transmit(edge: Any) -> bool:
    row = coerce_causal_edge(edge, ticker=str((edge or {}).get("ticker") if isinstance(edge, dict) else "") or "")
    if row is None:
        return False
    return str(row.get("status") or "candidate") in TRANSMITTABLE_EDGE_STATUSES


def transmission_stop_reason(edges: list[Any] | None) -> str | None:
    for raw in edges or []:
        edge = coerce_causal_edge(raw, ticker=str((raw or {}).get("ticker") if isinstance(raw, dict) else "") or "")
        if edge is None:
            label = compact_text(str(raw), 40) or "invalid"
            return f"unsupported_causal_edge:rejected:{label}"
        if not edge_can_transmit(edge):
            return f"unsupported_causal_edge:{edge.get('edge_id') or edge.get('from_node')}:{edge.get('status') or 'candidate'}"
    return None


def transmit_path(edges: list[Any] | None) -> dict[str, Any]:
    """Walk a causal path. Candidate / challenged / deprecated edges stop transmission."""
    transmitted: list[dict[str, Any]] = []
    for raw in coerce_causal_edges(edges):
        edge = raw
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


def _adjacency(edges: list[Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in coerce_causal_edges(edges):
        src = str(edge.get("from_node") or "")
        if src:
            out[src].append(edge)
    return out


def shortest_path(
    edges: list[Any] | None,
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
    adj = _adjacency(coerce_causal_edges(edges))
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


_ANCHOR_TOPIC = (
    ("customer", ("customer", "google", "alphabet", "meta", "openai", "anthropic", "hyperscaler", "asic", "tpu", "xpu")),
    ("competition", ("marvell", "competitor", "competitive", "design win", "socket")),
    ("earnings", ("earnings", "eps", "guidance", "10-q", "10-k", "quarterly", "print", "revenue")),
    ("demand", ("ai semiconductor", "ai revenue", "xpu", "asic", "accelerator", "custom silicon")),
)


def event_anchor_ids(
    *,
    event: dict[str, Any] | None,
    exposures: list[dict[str, Any]] | None = None,
    states: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
) -> set[str]:
    item = event or {}
    anchors: set[str] = set()
    for key in ("event_id", "subject", "event_key"):
        if item.get(key):
            anchors.add(str(item.get(key)))
    entities = [str(value).strip().lower() for value in (item.get("entities") or []) if str(value).strip()]
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {' '.join(entities)} {item.get('event_type') or ''}".lower()
    topics = {name for name, needles in _ANCHOR_TOPIC if any(token in blob for token in needles)}
    rows = list(exposures or []) + list(states or []) + list(drivers or [])
    for row in rows:
        text = " ".join(
            str(row.get(key) or "")
            for key in ("name", "object_name", "subject", "statement", "reason", "exposure_type", "canonical_key", "category", "current_state")
        ).lower()
        ids = _ids_of(row)
        if any(ent and ent in text for ent in entities if len(ent) > 3):
            anchors |= ids
            continue
        if "customer" in topics and any(token in text for token in ("customer", "hyperscaler", "google", "asic", "xpu")):
            anchors |= ids
            continue
        if "competition" in topics and any(token in text for token in ("competition", "competitive", "marvell", "market_share")):
            anchors |= ids
            continue
        if "earnings" in topics and any(token in text for token in ("q3", "q2", "q4", "eps", "guidance", "results", "earnings")):
            if row.get("state_id") or str(row.get("category") or "") in {"demand", "customer_concentration"}:
                anchors |= ids
                continue
        if "demand" in topics and any(token in text for token in ("demand", "ai semiconductor", "xpu", "asic", "accelerator")):
            if str(row.get("category") or "") in {"demand", "customer_concentration", "competition"} or row.get("state_id") or str(row.get("exposure_type") or "") in {"customer", "competitive", "product"}:
                anchors |= ids
                continue
        if any(token in text for token in ("customer", "hyperscaler", "asic", "exposure") if token in blob):
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
    graph = coerce_causal_edges(edges)
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
        if walked.get("found") and not walked.get("stopped"):
            continue
        label = compact_text(row.get("title") or row.get("name") or goal, 60)
        entity = _event_entity(event)
        exposure = _event_exposure_label(event, exposures)
        question = structured_gap_question(entity=entity, exposure=exposure, target=label, kind="causal_gap")
        gaps.append(
            {
                "from_node": next(iter(anchors)),
                "to_node": goal,
                "kind": "causal_gap",
                "reason": walked.get("reason") or "causal_gap",
                "question": question,
                "related_objects": [goal, entity or exposure],
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
    drivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    graph = coerce_causal_edges(edges)
    item = event or {}
    event_nodes = {str(item.get(key) or "") for key in ("event_id", "subject", "event_key") if item.get(key)}
    event_nodes.discard("")
    related = event_anchor_ids(event=event, exposures=exposures, states=states)
    anchors = set(event_nodes) | related
    anchors.discard("")
    successful: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in claims or []:
        goal = str(row.get("claim_id") or "")
        if not goal:
            continue
        walked = shortest_path(graph, start_ids=event_nodes or anchors, goal_ids={goal})
        if not walked.get("found") and not walked.get("stopped") and related - event_nodes:
            walked = shortest_path(graph, start_ids=related - event_nodes, goal_ids={goal})
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


def _event_entity(event: dict[str, Any] | None) -> str:
    item = event or {}
    for value in item.get("entities") or []:
        token = compact_text(str(value), 40)
        if token and token.lower() not in {"avgo", "broadcom"}:
            return token
    blob = f"{item.get('title') or ''} {item.get('fact') or ''}".lower()
    for name in ("Google", "Meta", "OpenAI", "Anthropic", "Marvell", "NVIDIA"):
        if name.lower() in blob:
            return name
    return compact_text(item.get("subject") or item.get("event_type") or "issuer", 40)


def _event_exposure_label(event: dict[str, Any] | None, exposures: list[dict[str, Any]] | None = None) -> str:
    for row in exposures or []:
        label = compact_text(row.get("object_name") or row.get("exposure_type") or "", 40)
        if label:
            return label
    item = event or {}
    et = str(item.get("event_type") or "").lower()
    if et in {"customer", "demand", "capex"}:
        return "customer exposure"
    if et in {"competition"}:
        return "competitive exposure"
    if et in {"earnings", "guidance"}:
        return "earnings exposure"
    return "named exposure"


def structured_gap_question(*, entity: str, exposure: str, target: str, kind: str = "causal_gap") -> str:
    who = compact_text(entity or "the issuer", 40)
    via = compact_text(exposure or "a named exposure", 40)
    to = compact_text(target or "the affected object", 60)
    if kind == "expectation_gap":
        return f"What expectation pair is missing for {who} on {to}?"
    if kind == "hypothesis_uncertainty":
        return f"What evidence would resolve the {who} {via} hypothesis?"
    return f"What {via} links {who} to {to}?"


def research_question_ok(question: str | None) -> bool:
    text = compact_text(question or "", 240)
    if not text:
        return False
    low = text.lower()
    if "how exposed is the issuer to" in low:
        return False
    words = [part for part in low.replace("?", " ").split() if part]
    if len(words) < 5 or len(words) > 28:
        return False
    specific = any(
        token in low
        for token in (
            "google",
            "meta",
            "marvell",
            "openai",
            "anthropic",
            "exposure",
            "causal",
            "expectation",
            "hypothesis",
            "eps",
            "xpu",
            "asic",
            "customer",
            "guidance",
            "driver",
            "claim",
            "pricing",
            "unexplained",
            "confirm",
        )
    )
    if not specific:
        return False
    if any(token in low for token in ("what will happen", "is avgo a buy", "thoughts on")):
        return False
    return True


def _pair_key(src: str, dst: str) -> str:
    return f"{src}->{dst}"


def _recovered_status(shared: list[str]) -> str:
    if len(shared) >= 2:
        return "supported"
    if len(shared) == 1:
        return "observed"
    return "candidate"


def recover_material_paths(
    *,
    ticker: str,
    states: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover bounded State→Exposure→Driver→Claim paths from existing Brain links.

    New edges stay candidate unless shared evidence already supports them.
    Established is never written here.
    """
    symbol = str(ticker).upper()
    existing = coerce_causal_edges(edges, ticker=symbol)
    seen = {_pair_key(str(row.get("from_node") or ""), str(row.get("to_node") or "")) for row in existing}
    recovered: list[dict[str, Any]] = []
    recovered_exposures: list[dict[str, Any]] = []

    def _add(payload: dict[str, Any]) -> None:
        if len(recovered) >= 16:
            return
        edge = normalize_causal_edge(payload, ticker=symbol)
        if edge is None:
            return
        token = _pair_key(edge["from_node"], edge["to_node"])
        if token in seen:
            return
        seen.add(token)
        recovered.append(edge)

    driver_rows = list(drivers or [])
    claim_rows = list(claims or [])
    state_rows = list(states or [])
    exposure_rows = list(exposures or [])
    claim_ids = {str(row.get("claim_id") or "") for row in claim_rows}
    claim_ids.discard("")

    for driver in driver_rows:
        driver_id = str(driver.get("driver_id") or "")
        if not driver_id:
            continue
        evidence = [str(item) for item in (driver.get("evidence_ids") or []) if str(item)]
        for cid in driver.get("related_claim_ids") or []:
            if str(cid) not in claim_ids:
                continue
            _add(
                {
                    "from_node": driver_id,
                    "to_node": str(cid),
                    "from_type": "value_driver",
                    "to_type": "core_claim",
                    "relationship_type": "driver_to_claim",
                    "status": _recovered_status(evidence),
                    "evidence_ids": evidence,
                    "mechanism": f"{driver.get('name') or driver_id} informs {cid}.",
                }
            )
        category = str(driver.get("category") or driver.get("canonical_key") or "").lower()
        exposure_type = ""
        if "customer" in category or "demand" in category:
            exposure_type = "customer"
        elif "competition" in category:
            exposure_type = "competitive"
        if not exposure_type:
            continue
        existing_exp = next(
            (
                row
                for row in exposure_rows
                if str(row.get("related_driver_id") or "") == driver_id
                or (str(row.get("exposure_type") or "") == exposure_type and driver_id in str(row.get("related_driver_id") or row.get("reason") or ""))
            ),
            None,
        )
        invented = existing_exp is None
        if existing_exp is None:
            exp_id = f"bexp_rec_{driver_id[-12:]}"
            existing_exp = {
                "exposure_id": exp_id,
                "ticker": symbol,
                "subject": symbol,
                "object_name": driver.get("name") or category,
                "exposure_type": exposure_type,
                "related_driver_id": driver_id,
                "related_claim_id": (driver.get("related_claim_ids") or [None])[0],
                "can_affect_claim": True,
                "direct_or_indirect": "direct",
                "evidence_ids": evidence,
                "reason": f"Recovered {exposure_type} exposure from {driver.get('name') or driver_id}.",
                "mechanism": driver.get("why_it_matters") or driver.get("current_state") or "",
            }
            recovered_exposures.append(existing_exp)
            exposure_rows.append(existing_exp)
        exp_id = str(existing_exp.get("exposure_id") or "")
        if exp_id:
            shared = sorted({str(item) for item in (existing_exp.get("evidence_ids") or []) if str(item)} & set(evidence))
            _add(
                {
                    "from_node": exp_id,
                    "to_node": driver_id,
                    "from_type": "exposure",
                    "to_type": "value_driver",
                    "relationship_type": "exposure_to_driver",
                    "status": "candidate" if invented or not shared else _recovered_status(shared),
                    "evidence_ids": shared,
                    "mechanism": f"{existing_exp.get('object_name') or exp_id} feeds {driver.get('name') or driver_id}.",
                }
            )

    for state in state_rows:
        state_id = str(state.get("state_id") or "")
        if not state_id:
            continue
        state_ev = {str(item) for item in (state.get("evidence_ids") or []) if str(item)}
        for driver in driver_rows:
            driver_id = str(driver.get("driver_id") or "")
            if not driver_id:
                continue
            driver_ev = {str(item) for item in (driver.get("evidence_ids") or []) if str(item)}
            shared = sorted(state_ev & driver_ev)
            if not shared and not _topic_overlap(state, driver):
                continue
            status = _recovered_status(shared)
            if status == "candidate" and not shared:
                continue
            matched_exp = next(
                (
                    row
                    for row in exposure_rows
                    if str(row.get("related_driver_id") or "") == driver_id
                ),
                None,
            )
            if matched_exp and matched_exp.get("exposure_id"):
                _add(
                    {
                        "from_node": state_id,
                        "to_node": str(matched_exp.get("exposure_id")),
                        "from_type": "company_state",
                        "to_type": "exposure",
                        "relationship_type": "state_to_exposure",
                        "status": status,
                        "evidence_ids": shared,
                        "mechanism": f"{state.get('name') or state_id} reaches {matched_exp.get('object_name')}.",
                    }
                )
            else:
                _add(
                    {
                        "from_node": state_id,
                        "to_node": driver_id,
                        "from_type": "company_state",
                        "to_type": "value_driver",
                        "relationship_type": "state_to_exposure",
                        "status": status,
                        "evidence_ids": shared,
                        "mechanism": f"{state.get('name') or state_id} shares evidence with {driver.get('name') or driver_id}.",
                    }
                )

    return {"edges": recovered, "exposures": recovered_exposures}


def _topic_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_text = " ".join(str(left.get(key) or "") for key in ("name", "subject", "canonical_key", "category", "statement")).lower()
    right_text = " ".join(str(right.get(key) or "") for key in ("name", "canonical_key", "category", "current_state")).lower()
    pairs = (
        ("q3", "demand"),
        ("q4", "demand"),
        ("guidance", "demand"),
        ("eps", "demand"),
        ("customer", "customer"),
        ("hyperscaler", "customer"),
        ("ai", "demand"),
    )
    return any(a in left_text and b in right_text for a, b in pairs)
