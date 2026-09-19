"""Phase 1 Brain Runtime: incremental update. LLM proposes; Phase 0 decides writes."""

from __future__ import annotations

import time
from typing import Any

from .critic import critic_context, incremental_critic_context, reconcile_critic
from .incremental import critic_should_expand, full_review_reason
from .l0 import process_l0
from .llm_steps import change_proposals, event_extract, independent_critic
from .materiality import materiality_gate
from .phase0 import _observation_identity, evaluate_brain_changes
from .routing import resolve_brain_completers
from .shadow import current_states_only, should_enter_shadow
from .causal import (
    assess_event_transmissions,
    claim_causal_paths,
    coerce_causal_edges,
    compact_path,
    detect_causal_gaps,
    event_anchor_ids,
    financial_edges_from_drivers,
    recover_material_paths,
    relevant_causal_subgraph,
    research_question_ok,
    transmission_stop_reason,
)
from .exposure import relevant_exposures
from .market import relevant_market_attentions
from .market_layer import interpret_market_layer, merge_market_proposals
from .now import build_now_chain
from .store import BrainStore
from .snapshot import build_snapshot, locate_affected_objects
from .trace import build_runtime_trace
from .types import DEFAULT_RUN_MODE, LOW_RELIABILITY
from stock_pm.research.llm_reason import compact_text


def _calls(audit: dict[str, Any] | None, role: str, step: str) -> dict[str, Any]:
    row = dict(audit or {})
    row["role"] = role
    row["step"] = step
    return row


def _identity_like_claim(row: dict[str, Any]) -> bool:
    current = row.get("from_payload") or row.get("from") or {}
    nxt = row.get("to_payload") or row.get("to") or {}
    return any(
        field in nxt and str(nxt.get(field) or "") != str(current.get(field) or "")
        for field in ("statement", "status")
    )


def _evidence_momentum_proposals(
    *,
    event: dict[str, Any] | None,
    affected: dict[str, list[dict[str, Any]]] | None,
    ticker: str,
) -> list[dict[str, Any]]:
    item = event or {}
    if str(item.get("kind") or "") == "price":
        return []
    token = compact_text(item.get("event_key") or item.get("title") or item.get("fact") or "", 80)
    if not token:
        return []
    out: list[dict[str, Any]] = []
    for row in (affected or {}).get("states") or []:
        evidence = list(dict.fromkeys(list(row.get("evidence_ids") or []) + [token]))
        payload = {"evidence_ids": evidence}
        if str(row.get("confidence") or "") == "medium" and len(evidence) > len(row.get("evidence_ids") or []):
            payload["confidence"] = "high"
        out.append(
            {
                "object_type": "company_state",
                "object_id": row.get("state_id"),
                "source_kind": item.get("kind") or "event",
                "fact_reliability": item.get("fact_reliability"),
                "from": {"confidence": row.get("confidence"), "statement": row.get("statement")},
                "to": payload,
                "reason": "Confirmed material evidence accumulates on the matching State.",
                "evidence_ids": evidence,
            }
        )
    for row in (affected or {}).get("drivers") or []:
        evidence = list(dict.fromkeys(list(row.get("evidence_ids") or []) + [token]))
        payload = {"evidence_ids": evidence, "support_strength": int(row.get("support_strength") or 0) + 1}
        if str(row.get("uncertainty") or "") == "high":
            payload["uncertainty"] = "medium"
        out.append(
            {
                "object_type": "value_driver",
                "object_id": row.get("driver_id"),
                "source_kind": item.get("kind") or "event",
                "fact_reliability": item.get("fact_reliability"),
                "from": {"current_state": row.get("current_state"), "uncertainty": row.get("uncertainty")},
                "to": payload,
                "reason": "Confirmed material evidence accumulates on the matching Driver.",
                "evidence_ids": evidence,
            }
        )
    for row in (affected or {}).get("claims") or []:
        out.append(
            {
                "object_type": "core_claim" if row.get("is_core") else "claim",
                "object_id": row.get("claim_id"),
                "source_kind": item.get("kind") or "event",
                "fact_reliability": item.get("fact_reliability"),
                "is_core": bool(row.get("is_core")),
                "from": {"status": row.get("status"), "statement": row.get("statement"), "is_core": row.get("is_core"), "confidence": row.get("confidence")},
                "to": {"evidence_ids": list(dict.fromkeys(list(row.get("evidence_ids") or []) + [token]))},
                "reason": "Confirmed material evidence updates Claim evidence momentum only.",
                "evidence_ids": [token],
            }
        )
    return out[:3]


def _relevant_hypotheses(event: dict[str, Any] | None, rows: list[dict[str, Any]] | None, *, limit: int = 4) -> list[dict[str, Any]]:
    item = event or {}
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {' '.join(str(x) for x in (item.get('entities') or []))}".lower()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows or []:
        if str(row.get("status") or "") in {"closed", "retired"} and "confirm" not in blob and "rumor" not in blob:
            continue
        text = f"{row.get('canonical_key') or ''} {row.get('hypothesis') or ''} {row.get('kind') or ''}".lower()
        score = 2 if any(token and token in text for token in (item.get("entities") or []) if len(str(token)) > 3) else 0
        if any(token in text for token in ("google", "customer", "demand", "marvell", "valuation") if token in blob):
            score += 2
        if str(row.get("status") or "") in {"open", "supported", "candidate", "weakened", "unresolved"}:
            score += 1
        ranked.append((score, row))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    picked = [row for score, row in ranked if score > 0][:limit]
    if len(picked) < limit:
        for _score, row in ranked:
            if row not in picked:
                picked.append(row)
            if len(picked) >= limit:
                break
    return picked[:limit]


def _relevant_expectations(event: dict[str, Any] | None, rows: list[dict[str, Any]] | None, *, limit: int = 3) -> list[dict[str, Any]]:
    item = event or {}
    name = str(item.get("expectation_name") or item.get("subject") or "").lower()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        token = str(row.get("name") or row.get("subject") or "").lower()
        if name and name in token:
            out.append(row)
    if not out:
        out = list(rows or [])
    return out[:limit]


def _token_usage(llm_calls: list[dict[str, Any]] | None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    calls = list(llm_calls or [])
    reasoning = [row for row in calls if str(row.get("role") or "") == "reasoning"]
    critic = [row for row in calls if str(row.get("role") or "") == "critic"]
    mechanical = [row for row in calls if str(row.get("role") or "") == "mechanical"]
    def _sum(rows: list[dict[str, Any]], key: str) -> int:
        return sum(int(row.get(key) or 0) for row in rows)
    input_tokens = _sum(calls, "input_tokens")
    output_tokens = _sum(calls, "output_tokens")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "critic_input": _sum(critic, "input_tokens"),
        "critic_output": _sum(critic, "output_tokens"),
        "reasoning_input": _sum(reasoning, "input_tokens"),
        "reasoning_output": _sum(reasoning, "output_tokens"),
        "mechanical_input": _sum(mechanical, "input_tokens"),
        "mechanical_output": _sum(mechanical, "output_tokens"),
        "total_tokens": input_tokens + output_tokens,
        "context_parts": dict((snapshot or {}).get("context_part_tokens") or {}),
    }


def _store_context(store: Any | None, ticker: str) -> dict[str, Any]:
    if store is None:
        return {
            "states": [],
            "drivers": [],
            "claims": [],
            "exposures": [],
            "evidence": [],
            "links": [],
            "causal_edges": [],
            "history": [],
            "shadows": [],
            "market_attentions": [],
            "expectations": [],
            "hypotheses": [],
            "facts": [],
            "fingerprints": [],
            "identities": [],
            "events": [],
        }
    news = store.list_news(ticker) if hasattr(store, "list_news") else []
    observations = store.list_observations(ticker) if hasattr(store, "list_observations") else []
    events = store.list_events(ticker) if hasattr(store, "list_events") else []
    rows = list(news) + list(observations) + list(events)
    facts = [str(row.get("title") or row.get("new_fact") or row.get("statement") or "") for row in rows]
    fingerprints = [str(row.get("fingerprint") or "") for row in rows if row.get("fingerprint")]
    identities = [_observation_identity(row) for row in rows]
    return {
        "states": current_states_only(store.list_current_states(ticker) if hasattr(store, "list_current_states") else store.list_states(ticker)),
        "drivers": store.list_drivers(ticker) if hasattr(store, "list_drivers") else [],
        "claims": store.list_active_claims(ticker) if hasattr(store, "list_active_claims") else [],
        "exposures": store.list_exposures(ticker) if hasattr(store, "list_exposures") else [],
        "evidence": store.list_evidence(ticker) if hasattr(store, "list_evidence") else [],
        "links": store.list_links() if hasattr(store, "list_links") else [],
        "causal_edges": coerce_causal_edges(store.list_causal_edges(ticker) if hasattr(store, "list_causal_edges") else [], ticker=ticker),
        "history": store.list_history(ticker) if hasattr(store, "list_history") else [],
        "shadows": store.list_shadows(ticker) if hasattr(store, "list_shadows") else [],
        "market_attentions": store.list_market_attentions(ticker) if hasattr(store, "list_market_attentions") else [],
        "expectations": store.list_expectations(ticker) if hasattr(store, "list_expectations") else [],
        "hypotheses": store.list_hypotheses(ticker) if hasattr(store, "list_hypotheses") else [],
        "facts": facts,
        "fingerprints": fingerprints,
        "identities": identities,
        "events": events,
        "news": news,
        "observations": observations,
    }


def run_brain_update(
    *,
    ticker: str,
    item: dict[str, Any],
    store: BrainStore | None = None,
    mechanical_completer: Any | None = None,
    reasoning_completer: Any | None = None,
    completer: Any | None = None,
    trigger: str | None = None,
    mode: str | None = None,
    brain: dict[str, Any] | None = None,
    allowed_ids: set[str] | None = None,
    research: Any | None = None,
) -> dict[str, Any]:
    """Default path: incremental update. Full Review only on explicit triggers."""
    symbol = str(ticker).upper()
    brain_store = store or BrainStore()
    run_mode = str(mode or DEFAULT_RUN_MODE).strip().lower() or DEFAULT_RUN_MODE
    context = _store_context(brain_store, symbol)
    if brain:
        for key, value in brain.items():
            if value:
                context[key] = value
    recovered = recover_material_paths(
        ticker=symbol,
        states=context.get("states"),
        drivers=context.get("drivers"),
        claims=context.get("claims"),
        exposures=context.get("exposures"),
        edges=context.get("causal_edges"),
        event=item,
    )
    for edge in recovered.get("edges") or []:
        if hasattr(brain_store, "upsert_causal_edge"):
            try:
                brain_store.upsert_causal_edge(edge)
            except Exception:
                continue
    for row in recovered.get("exposures") or []:
        if hasattr(brain_store, "insert_exposure") and row.get("exposure_id"):
            existing_ids = {str(item.get("exposure_id") or "") for item in (context.get("exposures") or [])}
            if str(row.get("exposure_id")) not in existing_ids:
                try:
                    brain_store.insert_exposure(row)
                except Exception:
                    continue
    if hasattr(brain_store, "list_causal_edges"):
        context["causal_edges"] = coerce_causal_edges(brain_store.list_causal_edges(symbol), ticker=symbol)
    if hasattr(brain_store, "list_exposures"):
        context["exposures"] = brain_store.list_exposures(symbol)
    llm_calls: list[dict[str, Any]] = []
    glm52_called = False
    glm53_called = False
    critic_called = False
    started = time.perf_counter()
    full_brain_size = (
        len(context.get("states") or [])
        + len(context.get("drivers") or [])
        + len(context.get("claims") or [])
        + len(context.get("events") or [])
        + len(context.get("evidence") or [])
        + len(context.get("history") or [])
        + len(context.get("causal_edges") or [])
    )

    def _finish(payload: dict[str, Any]) -> dict[str, Any]:
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        payload["event_id"] = item.get("event_id") or payload.get("event_id")
        payload["trace"] = build_runtime_trace(
            result=payload,
            item=item,
            elapsed_ms=elapsed_ms,
            full_brain_size=full_brain_size,
        )
        payload["elapsed_ms"] = elapsed_ms
        return payload

    l0 = process_l0(
        item,
        ticker=symbol,
        existing_facts=context.get("facts") or [],
        fingerprints=context.get("fingerprints") or [],
        identities=context.get("identities") or [],
        allowed_ids=allowed_ids,
        history=context.get("history") or [],
    )
    if l0["stop"]:
        if hasattr(brain_store, "insert_observation"):
            brain_store.insert_observation(
                {
                    "ticker": symbol,
                    "title": l0["title"],
                    "statement": item.get("fact") or item.get("statement") or l0["title"],
                    "kind": item.get("kind") or "news",
                    "material": False,
                    "reason": l0["stop_reason"] or "duplicate",
                    "fingerprint": l0["fingerprint"],
                    "payload": {"l0": {"duplicate": True}},
                }
            )
        return _finish(
            {
                "ticker": symbol,
                "path": "l0_stop",
                "run_mode": run_mode,
                "full_review": False,
                "stopped": True,
                "stop_reason": l0["stop_reason"],
                "duplicate": True,
                "glm52_called": False,
                "glm53_called": False,
                "critic_called": False,
                "material": False,
                "l0": l0,
                "llm_calls": [],
                "token_usage": _token_usage([]),
                "now_chain": build_now_chain(event=item, extract=None, material=False, stopped=l0["stop_reason"] or "duplicate"),
            }
        )

    full_reason = full_review_reason(trigger=trigger, event=item, mode=run_mode)
    is_full_review = bool(full_reason)
    if is_full_review and research is not None:
        try:
            from .pipeline import run_brain

            full_result = run_brain(
                research,
                symbol,
                store=brain_store,
                mechanical_completer=mechanical_completer,
                reasoning_completer=reasoning_completer,
                completer=completer,
                fetch_live=False,
                mode="full",
            )
            now_chain = build_now_chain(
                event=item,
                extract=None,
                exposures=context.get("exposures"),
                transmission=full_result.get("transmission") if isinstance(full_result, dict) else None,
                causal_gaps=list((full_result or {}).get("causal_gaps") or [])[:3],
                market_attentions=context.get("market_attentions"),
                expectations=brain_store.list_expectations(symbol) if hasattr(brain_store, "list_expectations") else [],
                hypotheses=brain_store.list_hypotheses(symbol) if hasattr(brain_store, "list_hypotheses") else [],
                questions=list((full_result or {}).get("questions") or []),
                material=True,
            )
            merged = dict(full_result or {})
            merged.update(
                {
                    "ticker": symbol,
                    "path": "full_review",
                    "run_mode": "full",
                    "full_review": True,
                    "full_review_reason": full_reason,
                    "stopped": False,
                    "material": True,
                    "l0": l0,
                    "now_chain": now_chain,
                    "token_usage": _token_usage(list(merged.get("llm_calls") or [])),
                }
            )
            return _finish(merged)
        except Exception:
            is_full_review = True

    mech, reason = resolve_brain_completers(
        completer,
        mechanical=mechanical_completer,
        reasoning=reasoning_completer,
    )
    extract: dict[str, Any] = {}
    if mech is not None:
        payload, audit = event_extract(
            mech,
            {"ticker": symbol, "item": l0["item"], "STEP_HINT": "event_extract"},
            allowed_ids=allowed_ids,
        )
        llm_calls.append(_calls(audit, "mechanical", "event_extract"))
        glm52_called = bool((audit or {}).get("llm_called"))
        extract = dict(payload or {})
    if not extract:
        extract = {
            "fact": l0["item"].get("fact") or l0["title"],
            "event": l0["title"],
            "entities": list(l0["item"].get("entities") or []),
            "event_type": l0["event_type"],
            "novelty": "new",
            "fact_reliability": l0["fact_reliability"],
            "material": None,
            "possible_affected": [],
        }

    event = {
        **l0["item"],
        "fact": extract.get("fact") or l0["item"].get("fact") or l0["title"],
        "entities": extract.get("entities") or l0["item"].get("entities") or [],
        "event_type": extract.get("event_type") or l0["event_type"],
        "novelty": extract.get("novelty") or "new",
        "fact_reliability": extract.get("fact_reliability") or l0["fact_reliability"],
        "possible_affected": extract.get("possible_affected") or [],
    }
    ingested_reliability = str(l0.get("fact_reliability") or l0["item"].get("fact_reliability") or "")
    if ingested_reliability in LOW_RELIABILITY:
        event["fact_reliability"] = ingested_reliability
    ingested_kind = str(l0["item"].get("kind") or "")
    if ingested_kind in {"rumor", "signal"}:
        event["kind"] = ingested_kind
    gate = materiality_gate(
        event,
        ticker=symbol,
        extract=extract,
        drivers=context.get("drivers"),
        claims=context.get("claims"),
    )
    if not gate["material"]:
        if hasattr(brain_store, "insert_observation"):
            brain_store.insert_observation(
                {
                    "ticker": symbol,
                    "title": l0["title"],
                    "statement": event.get("fact") or l0["title"],
                    "kind": event.get("kind") or "news",
                    "material": False,
                    "reason": gate["reason"],
                    "fingerprint": l0["fingerprint"],
                    "payload": {"extract": extract, "gate": gate},
                }
            )
        return _finish(
            {
                "ticker": symbol,
                "path": "observation_memory",
                "run_mode": run_mode,
                "full_review": False,
                "stopped": True,
                "stop_reason": "non_material",
                "material": False,
                "materiality": gate,
                "glm52_called": glm52_called,
                "glm53_called": False,
                "critic_called": False,
                "l0": l0,
                "extract": extract,
                "llm_calls": llm_calls,
                "token_usage": _token_usage(llm_calls),
                "now_chain": build_now_chain(event=event, extract=extract, material=False, stopped="non_material"),
            }
        )

    price_only = bool(gate.get("price_only") or gate.get("abnormal_price") and str(event.get("kind") or "") == "price")
    if price_only:
        event["kind"] = "price"
        event["source_kind"] = "price"

    affected = locate_affected_objects(
        extract=extract,
        event=event,
        states=context.get("states"),
        drivers=context.get("drivers"),
        claims=context.get("claims"),
        exposures=context.get("exposures"),
        links=context.get("links"),
        causal_edges=context.get("causal_edges"),
        ticker=symbol,
    )
    driver_ids = {
        str(row.get("driver_id") or row.get("canonical_key") or "")
        for row in affected.get("drivers") or []
    }
    driver_ids.discard("")
    merged_exposures = list(affected.get("exposures") or [])
    seen_exposures = {str(row.get("exposure_id") or "") for row in merged_exposures}
    for row in relevant_exposures(event=event, exposures=context.get("exposures"), driver_ids=driver_ids):
        eid = str(row.get("exposure_id") or "")
        if eid and eid not in seen_exposures:
            seen_exposures.add(eid)
            merged_exposures.append(row)
    affected = {**affected, "exposures": merged_exposures}
    anchors = event_anchor_ids(
        event=event,
        exposures=merged_exposures,
        states=affected.get("states") or context.get("states"),
        drivers=affected.get("drivers") or context.get("drivers"),
    )
    object_ids = set(anchors)
    for group, keys in (
        (affected.get("states"), ("state_id", "name")),
        (affected.get("drivers"), ("driver_id", "canonical_key")),
        (affected.get("claims"), ("claim_id",)),
        (merged_exposures, ("exposure_id",)),
    ):
        for row in group or []:
            for key in keys:
                if row.get(key):
                    object_ids.add(str(row.get(key)))
    relevant_edges = relevant_causal_subgraph(
        edges=context.get("causal_edges"),
        object_ids=object_ids,
        limit=12 if is_full_review else 8,
    )
    causal_paths: list[dict[str, Any]] = []
    for claim in (affected.get("claims") or [])[:4]:
        cid = str(claim.get("claim_id") or "")
        if not cid:
            continue
        for path in claim_causal_paths(
            claim_id=cid,
            edges=context.get("causal_edges"),
            start_ids=anchors,
            limit=2,
        ):
            causal_paths.append(compact_path(path))
        if len(causal_paths) >= 4:
            break
    causal_gaps = detect_causal_gaps(
        event=event,
        edges=context.get("causal_edges"),
        related_claims=affected.get("claims"),
        exposures=merged_exposures,
        states=affected.get("states"),
    )
    financial_links = [
        {
            "from_node": edge.get("from_node"),
            "to_node": edge.get("to_node"),
            "relationship_type": edge.get("relationship_type"),
            "mechanism": edge.get("mechanism"),
            "status": edge.get("status"),
        }
        for edge in financial_edges_from_drivers(affected.get("drivers"), ticker=symbol)
    ][:4]
    related_ids = object_ids | {
        str(row.get("claim_id") or "") for row in affected.get("claims") or []
    }
    targeted_attentions = relevant_market_attentions(
        event=event,
        attentions=context.get("market_attentions"),
        related_ids=related_ids,
        limit=3,
    )
    targeted_expectations = _relevant_expectations(event, context.get("expectations"), limit=3)
    targeted_hypotheses = _relevant_hypotheses(event, context.get("hypotheses"), limit=4)
    transmission = assess_event_transmissions(
        event=event,
        edges=context.get("causal_edges"),
        claims=affected.get("claims"),
        exposures=merged_exposures,
        states=affected.get("states"),
        drivers=affected.get("drivers"),
    )
    snapshot = build_snapshot(
        event=event,
        affected=affected,
        evidence=context.get("evidence"),
        links=context.get("links"),
        causal_edges=relevant_edges,
        history=context.get("history"),
        shadows=context.get("shadows"),
        causal_paths=causal_paths[:4],
        causal_gaps=causal_gaps[:3],
        financial_links=financial_links,
        market_attentions=targeted_attentions,
        expectations=targeted_expectations,
        hypotheses=targeted_hypotheses,
    )
    proposals: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    if reason is not None:
        payload, audit = change_proposals(
            reason,
            {
                "ticker": symbol,
                "event": event,
                "snapshot": snapshot,
                "rules": [
                    "Output Change Proposals only.",
                    "Do not write Brain objects directly.",
                    "Rumor cannot modify Current State or Core Claim.",
                ],
            },
            allowed_ids=allowed_ids,
        )
        llm_calls.append(_calls(audit, "reasoning", "change_proposals"))
        glm53_called = bool((audit or {}).get("llm_called"))
        proposals = list((payload or {}).get("proposals") or [])
        questions = list((payload or {}).get("questions") or [])
    if should_enter_shadow(event) and not any(str(row.get("object_type") or "") in {"shadow_state", "shadow"} for row in proposals):
        proposals.append(
            {
                "object_type": "shadow_state",
                "source_kind": "rumor",
                "confidence": "low",
                "fact_reliability": "rumor",
                "to": {
                    "name": event.get("subject") or event.get("title"),
                    "statement": event.get("fact") or event.get("title"),
                    "confidence": "low",
                    "materiality_if_true": "high",
                },
                "reason": "Unconfirmed material event belongs in Shadow State.",
            }
        )
        questions.append(
            {
                "question": f"Can we confirm: {event.get('title') or event.get('fact')}?",
                "reason": "Weak signal is a research question, not a conclusion.",
                "related_objects": [event.get("title") or ""],
            }
        )
    seen_questions = {str(row.get("question") or "") for row in questions}
    for gap in causal_gaps:
        question = str(gap.get("question") or "")
        if question and question not in seen_questions:
            questions.append(
                {
                    "question": question,
                    "reason": gap.get("reason") or "causal_gap",
                    "related_objects": gap.get("related_objects") or [],
                }
            )
            seen_questions.add(question)
        already = any(
            str(row.get("object_type") or "") in {"causal_gap", "research_question"}
            and (
                str((row.get("to") or row.get("to_payload") or {}).get("to_node") or "") == str(gap.get("to_node") or "")
                or str((row.get("to") or row.get("to_payload") or {}).get("question") or "") == question
            )
            for row in proposals
        )
        if not already and question:
            proposals.append(
                {
                    "object_type": "research_question",
                    "source_kind": event.get("kind") or "event",
                    "to": {"question": question, **gap},
                    "reason": gap.get("reason") or "Missing reliable causal path.",
                    "related_objects": gap.get("related_objects") or [],
                }
            )

    market_layer = interpret_market_layer(
        event,
        ticker=symbol,
        existing_expectations=context.get("expectations"),
        existing_hypotheses=context.get("hypotheses"),
    )
    proposals, _dup_skipped = merge_market_proposals(proposals, market_layer.get("proposals") or [])
    for question in market_layer.get("questions") or []:
        token = str(question.get("question") or "")
        if token and token not in seen_questions:
            questions.append(question)
            seen_questions.add(token)
    if price_only:
        proposals = [
            row
            for row in proposals
            if str(row.get("object_type") or "")
            not in {"state", "company_state", "industry_state", "macro_state", "claim", "core_claim", "driver", "value_driver"}
        ]
        for row in proposals:
            if str(row.get("source_kind") or "") != "price":
                row["source_kind"] = "price"
    elif str(event.get("fact_reliability") or "") == "direct_fact" and event.get("confirmed") is not False:
        proposals.extend(
            _evidence_momentum_proposals(
                event=event,
                affected=affected,
                ticker=symbol,
            )
        )

    filtered_questions: list[dict[str, Any]] = []
    seen_q_norm: set[str] = set()
    for question in questions:
        text = str(question.get("question") or "")
        norm = " ".join(text.lower().split())
        if not research_question_ok(text) or norm in seen_q_norm:
            continue
        seen_q_norm.add(norm)
        filtered_questions.append(question)
    questions = filtered_questions
    proposals = [
        row
        for row in proposals
        if str(row.get("object_type") or "") not in {"research_question", "causal_gap"}
        or research_question_ok(str((row.get("to") or row.get("to_payload") or {}).get("question") or row.get("reason") or ""))
    ]

    observations = [event]
    try:
        gate_result = evaluate_brain_changes(
        ticker=symbol,
        observations=observations,
        proposals=proposals,
        brain={
            "existing_facts": context.get("facts") or [],
            "event_fingerprints": context.get("fingerprints") or [],
            "causal_edges": context.get("causal_edges") or [],
            "event_nodes": sorted(anchors),
            "related_entities": context.get("related_entities") or [],
            "states": context.get("states") or [],
            "drivers": context.get("drivers") or [],
            "claims": context.get("claims") or [],
            "exposures": merged_exposures,
        },
        store=brain_store,
        )
    except Exception as exc:
        gate_result = {
            "approved": [],
            "rejected": [
                {
                    "object_type": "runtime",
                    "decision": "reject",
                    "reason": f"rejected_malformed_payload:{type(exc).__name__}",
                    "rules": [{"rule": "unsupported_causal_cannot_transmit", "reason": str(exc)}],
                }
            ],
            "requires_review": [],
            "questions": [],
            "budget": {},
            "auto_commit_allowed": False,
            "current_state_unchanged": True,
            "core_claims_unchanged": True,
            "committed": [],
        }
    for question in questions:
        if hasattr(brain_store, "insert_question") and question.get("question"):
            brain_store.insert_question(
                {
                    "ticker": symbol,
                    "question": question.get("question"),
                    "why_it_matters": question.get("reason") or "",
                    "related_objects": question.get("related_objects") or [],
                }
            )

    critic_result = None
    expand = critic_should_expand(proposals=proposals, budget=gate_result.get("budget"))
    affected_ids = {
        str(row.get("state_id") or row.get("driver_id") or row.get("claim_id") or "")
        for group in (affected.get("states"), affected.get("drivers"), affected.get("claims"))
        for row in (group or [])
    }
    affected_ids.discard("")
    if reason is not None and (gate_result.get("approved") or expand):
        base = critic_context(
            states=snapshot["states"],
            drivers=snapshot["drivers"],
            claims=snapshot["claims"],
            events=[event],
            transmissions=[],
            financial_impacts=[],
            evidence=snapshot.get("evidence") or [],
        )
        scoped = incremental_critic_context(base, affected_ids=affected_ids, expand=expand)
        payload, audit = independent_critic(reason, scoped, allowed_ids=allowed_ids or set())
        llm_calls.append(_calls(audit, "critic", "independent_critic"))
        critic_called = bool((audit or {}).get("llm_called"))
        critic_result = reconcile_critic(list((payload or {}).get("issues") or []), transmissions=[])
        critic_result["scope"] = "expanded" if expand else "incremental"

    unsupported_jump_count = 0
    unexpected_claim_change_count = 0
    if gate_result.get("auto_commit_allowed"):
        for row in gate_result.get("approved") or []:
            if str(row.get("object_type") or "") not in {"claim", "core_claim"}:
                continue
            if not _identity_like_claim(row):
                continue
            unexpected_claim_change_count += 1
            if str(row.get("source_kind") or "") not in {"news", "event"}:
                continue
            target_id = str(row.get("object_id") or (row.get("to_payload") or {}).get("object_id") or "")
            supplied = coerce_causal_edges(row.get("causal_edges") or (row.get("to_payload") or {}).get("causal_edges") or [])
            if supplied:
                if transmission_stop_reason(supplied) or not any(
                    "bclm_" in str(edge.get("to_node") or "") or str(edge.get("to_type") or "") in {"claim", "core_claim"}
                    for edge in supplied
                ):
                    unsupported_jump_count += 1
                continue
            if not target_id:
                unsupported_jump_count += 1
                continue
            walked = next(
                (item for item in (transmission.get("successful") or []) if item.get("claim_id") == target_id),
                None,
            )
            if walked is None:
                unsupported_jump_count += 1
    approved_attentions = []
    for row in gate_result.get("approved") or []:
        if str(row.get("object_type") or "") not in {"market_attention", "price_reaction"}:
            continue
        payload = dict(row.get("to_payload") or {})
        payload.setdefault("statement", payload.get("name") or row.get("reason"))
        payload.setdefault("related_objects", row.get("related_objects") or [])
        approved_attentions.append(payload)
    chain_attentions = list(targeted_attentions)
    seen_att = {str(row.get("attention_id") or row.get("name") or "") for row in chain_attentions}
    for row in approved_attentions:
        token = str(row.get("attention_id") or row.get("name") or row.get("statement") or "")
        if token and token not in seen_att:
            seen_att.add(token)
            chain_attentions.append(row)
    chain_exp: list[dict[str, Any]] = list(targeted_expectations)
    chain_hyp: list[dict[str, Any]] = list(targeted_hypotheses)
    for row in gate_result.get("approved") or []:
        payload = dict(row.get("to_payload") or {})
        kind = str(row.get("object_type") or "")
        if kind in {"expectation", "expectation_state"}:
            chain_exp.append(payload)
        if kind in {"market_driver_hypothesis", "market_driver"}:
            chain_hyp.append(payload)
    if hasattr(brain_store, "list_expectations"):
        chain_exp = list(brain_store.list_expectations(symbol) or chain_exp)[:4]
    if hasattr(brain_store, "list_hypotheses"):
        chain_hyp = list(brain_store.list_hypotheses(symbol) or chain_hyp)[:6]
    now_chain = build_now_chain(
        event=event,
        extract=extract,
        exposures=merged_exposures,
        transmission=transmission,
        causal_gaps=causal_gaps,
        market_attentions=chain_attentions[:4],
        expectations=chain_exp,
        hypotheses=chain_hyp,
        questions=list(questions) + list(gate_result.get("questions") or []),
        material=True,
        unresolved=bool(market_layer.get("unresolved")),
    )
    price_state_violations = sum(
        1
        for row in (gate_result.get("approved") or [])
        if str(row.get("source_kind") or "") == "price" and str(row.get("object_type") or "") in {"state", "company_state", "industry_state", "macro_state"}
    )
    price_claim_violations = sum(
        1
        for row in (gate_result.get("approved") or [])
        if str(row.get("source_kind") or "") == "price" and str(row.get("object_type") or "") in {"claim", "core_claim"}
    )
    market_stats = dict(market_layer.get("stats") or {})
    market_stats["price_fundamental_violations"] = price_state_violations
    market_stats["price_claim_violations"] = price_claim_violations
    market_stats["duplicates_prevented"] = int(market_stats.get("duplicates_prevented") or 0) + int(_dup_skipped)
    return _finish(
        {
            "ticker": symbol,
            "path": "full_review" if is_full_review else "incremental",
            "run_mode": "full" if is_full_review else run_mode,
            "full_review": is_full_review,
            "full_review_reason": full_reason,
            "stopped": False,
            "material": True,
            "materiality": gate,
            "affected": {
                "states": [row.get("state_id") or row.get("name") for row in affected.get("states") or []],
                "drivers": [row.get("driver_id") or row.get("canonical_key") or row.get("name") for row in affected.get("drivers") or []],
                "claims": [row.get("claim_id") or row.get("title") for row in affected.get("claims") or []],
                "exposures": [row.get("exposure_id") or row.get("exposure_type") for row in affected.get("exposures") or []],
            },
            "snapshot": snapshot,
            "proposals": proposals,
            "questions": questions,
            "causal_gaps": causal_gaps,
            "transmission": transmission,
            "unsupported_jump_count": unsupported_jump_count,
            "unexpected_claim_change_count": unexpected_claim_change_count,
            "gate": gate_result,
            "glm52_called": glm52_called,
            "glm53_called": glm53_called,
            "critic_called": critic_called,
            "critic": critic_result,
            "l0": l0,
            "extract": extract,
            "llm_calls": llm_calls,
            "current_state_unchanged": gate_result.get("current_state_unchanged"),
            "core_claims_unchanged": gate_result.get("core_claims_unchanged"),
            "now_chain": now_chain,
            "market_layer": market_stats,
            "token_usage": _token_usage(llm_calls, snapshot),
        }
    )
