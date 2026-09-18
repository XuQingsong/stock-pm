"""Phase 1 Brain Runtime: incremental update. LLM proposes; Phase 0 decides writes."""

from __future__ import annotations

from typing import Any

from .critic import critic_context, incremental_critic_context, reconcile_critic
from .incremental import critic_should_expand, full_review_reason
from .l0 import process_l0
from .llm_steps import change_proposals, event_extract, independent_critic
from .materiality import materiality_gate
from .phase0 import _observation_identity, evaluate_brain_changes
from .routing import resolve_brain_completers
from .shadow import current_states_only, should_enter_shadow
from .snapshot import build_snapshot, locate_affected_objects
from .store import BrainStore
from .types import DEFAULT_RUN_MODE


def _calls(audit: dict[str, Any] | None, role: str, step: str) -> dict[str, Any]:
    row = dict(audit or {})
    row["role"] = role
    row["step"] = step
    return row


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
        "evidence": [],
        "links": store.list_links() if hasattr(store, "list_links") else [],
        "causal_edges": store.list_causal_edges(ticker) if hasattr(store, "list_causal_edges") else [],
        "history": store.list_history(ticker) if hasattr(store, "list_history") else [],
        "shadows": store.list_shadows(ticker) if hasattr(store, "list_shadows") else [],
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
    llm_calls: list[dict[str, Any]] = []
    glm52_called = False
    glm53_called = False
    critic_called = False

    full_reason = full_review_reason(trigger=trigger, event=item, mode=run_mode)
    if full_reason:
        return {
            "ticker": symbol,
            "path": "full_review",
            "run_mode": "full",
            "full_review": True,
            "full_review_reason": full_reason,
            "glm52_called": False,
            "glm53_called": False,
            "critic_called": False,
            "stopped": False,
            "material": True,
            "llm_calls": [],
        }

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
        return {
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
        }

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
        return {
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
        }

    affected = locate_affected_objects(
        extract=extract,
        event=event,
        states=context.get("states"),
        drivers=context.get("drivers"),
        claims=context.get("claims"),
        exposures=context.get("exposures"),
    )
    snapshot = build_snapshot(
        event=event,
        affected=affected,
        evidence=context.get("evidence"),
        links=context.get("links"),
        causal_edges=context.get("causal_edges"),
        history=context.get("history"),
        shadows=context.get("shadows"),
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

    observations = [event]
    gate_result = evaluate_brain_changes(
        ticker=symbol,
        observations=observations,
        proposals=proposals,
        brain={
            "existing_facts": context.get("facts") or [],
            "event_fingerprints": context.get("fingerprints") or [],
            "causal_edges": context.get("causal_edges") or [],
            "related_entities": context.get("related_entities") or [],
        },
        store=brain_store,
    )
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

    return {
        "ticker": symbol,
        "path": "incremental",
        "run_mode": run_mode,
        "full_review": False,
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
    }
