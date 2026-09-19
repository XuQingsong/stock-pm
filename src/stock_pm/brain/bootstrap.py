"""Cold-Start Bootstrap: empty Brain → research-pack init, then Incremental.

Reuses run_brain (Evidence Set → GLM → evidence filters). Does not invent a
second initializer and does not let one Event both found the company and
analyze the tape.
"""

from __future__ import annotations

from typing import Any

from .causal import coerce_causal_edges, financial_edges_from_drivers, recover_material_paths
from .history import persist_baseline_history
from .pipeline import run_brain
from .store import BrainStore, durable_brain_store


LIFECYCLE_NEW_TICKER = "NEW_TICKER"
LIFECYCLE_BOOTSTRAPPING = "BOOTSTRAPPING"
LIFECYCLE_BASELINE_READY = "BASELINE_READY"
LIFECYCLE_INCREMENTAL = "INCREMENTAL"


def _rows(store: Any, method: str, ticker: str) -> list[dict[str, Any]]:
    if store is None or not hasattr(store, method):
        return []
    return list(getattr(store, method)(ticker) or [])


def company_states(store: Any, ticker: str) -> list[dict[str, Any]]:
    rows = _rows(store, "list_current_states", ticker) or _rows(store, "list_states", ticker)
    company = [
        row
        for row in rows
        if str(row.get("state_type") or "company").lower() in {"company", "company_state"}
    ]
    return company or list(rows)


def value_drivers(store: Any, ticker: str) -> list[dict[str, Any]]:
    return _rows(store, "list_drivers", ticker)


def core_claims(store: Any, ticker: str) -> list[dict[str, Any]]:
    rows = _rows(store, "list_active_claims", ticker)
    return [row for row in rows if row.get("is_core")]


def baseline_inventory(store: Any, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    states = company_states(store, symbol)
    drivers = value_drivers(store, symbol)
    claims = core_claims(store, symbol)
    return {
        "ticker": symbol,
        "states": len(states),
        "drivers": len(drivers),
        "core_claims": len(claims),
        "state_ids": [str(row.get("state_id") or "") for row in states if row.get("state_id")],
        "driver_ids": [str(row.get("driver_id") or "") for row in drivers if row.get("driver_id")],
        "claim_ids": [str(row.get("claim_id") or "") for row in claims if row.get("claim_id")],
    }


def brain_has_baseline(store: Any, ticker: str) -> bool:
    """Valid baseline = Company State AND Value Driver AND Core Claim."""
    inv = baseline_inventory(store, ticker)
    return bool(inv["states"] and inv["drivers"] and inv["core_claims"])


def brain_has_slow_layer(store: Any, ticker: str) -> bool:
    """True after a bootstrap attempt that persisted any Slow Brain object."""
    inv = baseline_inventory(store, ticker)
    return bool(inv["states"] or inv["drivers"] or inv["core_claims"])


def brain_initialized(store: Any, ticker: str) -> bool:
    return brain_has_baseline(store, ticker)


def brain_lifecycle(store: Any, ticker: str) -> str:
    if brain_has_baseline(store, ticker):
        return LIFECYCLE_BASELINE_READY
    inv = baseline_inventory(store, ticker)
    if inv["states"] or inv["drivers"] or inv["core_claims"]:
        return LIFECYCLE_BOOTSTRAPPING
    return LIFECYCLE_NEW_TICKER


def _high_budget_reasoning(existing: Any | None) -> Any:
    """Bootstrap-only larger completion budget. Incremental runtime stays unchanged."""
    try:
        from dataclasses import replace

        from stock_pm.brain.routing import ROLE_REASONING, BrainCompleter, layer_settings
        from stock_pm.research.agents.base import SettingsCompleter

        if existing is not None and not isinstance(existing, (SettingsCompleter, BrainCompleter)):
            return existing
        cfg = layer_settings(getattr(existing, "settings", None), role=ROLE_REASONING)
        return SettingsCompleter(replace(cfg, llm_max_tokens=max(int(cfg.llm_max_tokens or 0), 32768)))
    except Exception:
        return existing


def _token_usage(calls: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = list(calls or [])
    def _sum(key: str) -> int:
        return sum(int(row.get(key) or 0) for row in rows)
    input_tokens = _sum("input_tokens")
    output_tokens = _sum("output_tokens")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "calls": [
            {
                "model": row.get("model"),
                "call_type": row.get("step") or row.get("call_type") or row.get("role"),
                "input_tokens": int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "role": row.get("role") or row.get("step"),
            }
            for row in rows
        ],
    }


def _persist_recovered_graph(store: Any, ticker: str) -> dict[str, int]:
    """Candidate / observed / supported stubs from existing objects. Never established."""
    if store is None:
        return {"edges": 0, "exposures": 0}
    symbol = str(ticker).upper()
    states = _rows(store, "list_states", symbol)
    drivers = _rows(store, "list_drivers", symbol)
    claims = _rows(store, "list_active_claims", symbol)
    exposures = _rows(store, "list_exposures", symbol)
    edges = coerce_causal_edges(_rows(store, "list_causal_edges", symbol), ticker=symbol)
    recovered = recover_material_paths(
        ticker=symbol,
        states=states,
        drivers=drivers,
        claims=claims,
        exposures=exposures,
        edges=edges,
        event=None,
    )
    edge_n = 0
    exp_n = 0
    existing_exp = {str(row.get("exposure_id") or "") for row in exposures}
    for row in recovered.get("exposures") or []:
        eid = str(row.get("exposure_id") or "")
        if not eid or eid in existing_exp:
            continue
        if hasattr(store, "insert_exposure"):
            try:
                store.insert_exposure({**row, "ticker": symbol})
                existing_exp.add(eid)
                exp_n += 1
            except Exception:
                continue
    if exp_n:
        exposures = _rows(store, "list_exposures", symbol)
        recovered = recover_material_paths(
            ticker=symbol,
            states=states,
            drivers=drivers,
            claims=claims,
            exposures=exposures,
            edges=coerce_causal_edges(_rows(store, "list_causal_edges", symbol), ticker=symbol),
            event=None,
        )
    for edge in list(recovered.get("edges") or []) + list(financial_edges_from_drivers(drivers, ticker=symbol)):
        status = str(edge.get("status") or "candidate")
        if status == "established":
            edge = {**edge, "status": "candidate"}
        if hasattr(store, "upsert_causal_edge"):
            try:
                store.upsert_causal_edge({**edge, "ticker": symbol})
                edge_n += 1
            except Exception:
                continue
    return {"edges": edge_n, "exposures": exp_n}


def bootstrap_brain(
    research: Any,
    ticker: str,
    *,
    store: BrainStore | None = None,
    mechanical_completer: Any | None = None,
    reasoning_completer: Any | None = None,
    completer: Any | None = None,
    fetch_live: bool = True,
) -> dict[str, Any]:
    """Build a Minimum Viable Investment Brain from the research pack.

    Not an Event path. LLM output still passes run_brain evidence / selection
    filters (allowed_ids, driver universe, core cap, driver binding, unbound-fact strip).
    """
    symbol = str(ticker or "").upper()
    brain_store = durable_brain_store(store, research)
    if brain_has_baseline(brain_store, symbol):
        inv = baseline_inventory(brain_store, symbol)
        return {
            "ticker": symbol,
            "path": "cold_start_bootstrap",
            "bootstrap": True,
            "bootstrap_skipped": True,
            "brain_initialized": True,
            "lifecycle": LIFECYCLE_INCREMENTAL,
            "full_review": False,
            "stopped": False,
            "material": False,
            "inventory": inv,
            "token_usage": _token_usage([]),
            "llm_calls": [],
            "glm52_called": False,
            "glm53_called": False,
            "critic_called": False,
        }
    if research is None:
        return {
            "ticker": symbol,
            "path": "needs_bootstrap",
            "bootstrap": False,
            "brain_initialized": False,
            "lifecycle": brain_lifecycle(brain_store, symbol),
            "full_review": False,
            "stopped": True,
            "stop_reason": "needs_bootstrap",
            "material": False,
            "inventory": baseline_inventory(brain_store, symbol),
            "token_usage": _token_usage([]),
            "llm_calls": [],
            "glm52_called": False,
            "glm53_called": False,
            "critic_called": False,
        }

    injected = completer if completer is not None else getattr(research, "completer", None)
    bootstrap_reason = _high_budget_reasoning(reasoning_completer or injected)
    result = run_brain(
        research,
        symbol,
        store=brain_store,
        mechanical_completer=mechanical_completer,
        reasoning_completer=bootstrap_reason,
        completer=None,
        fetch_live=fetch_live,
        mode="full",
    )
    first_calls = list((result or {}).get("llm_calls") or ((result or {}).get("audit") or {}).get("llm_calls") or [])
    if not brain_has_baseline(brain_store, symbol):
        retry = run_brain(
            research,
            symbol,
            store=brain_store,
            mechanical_completer=mechanical_completer,
            reasoning_completer=bootstrap_reason,
            completer=None,
            fetch_live=False,
            mode="full",
        )
        retry_calls = list((retry or {}).get("llm_calls") or ((retry or {}).get("audit") or {}).get("llm_calls") or [])
        result = {**(retry or {}), "baseline_retry": True}
        result["llm_calls"] = first_calls + retry_calls
        audit = dict((result.get("audit") or {}))
        audit["llm_calls"] = result["llm_calls"]
        result["audit"] = audit
    graph = _persist_recovered_graph(brain_store, symbol)
    persist_baseline_history(brain_store, symbol)
    initialized = brain_has_baseline(brain_store, symbol)
    lifecycle = LIFECYCLE_BASELINE_READY if initialized else LIFECYCLE_BOOTSTRAPPING
    calls = list((result or {}).get("llm_calls") or ((result or {}).get("audit") or {}).get("llm_calls") or [])
    return {
        "ticker": symbol,
        "path": "cold_start_bootstrap",
        "bootstrap": True,
        "bootstrap_skipped": False,
        "brain_initialized": initialized,
        "lifecycle": lifecycle,
        "full_review": False,
        "stopped": False,
        "material": True,
        "run_brain": result,
        "inventory": baseline_inventory(brain_store, symbol),
        "recovered_graph": graph,
        "states": (result or {}).get("states") or [],
        "drivers": (result or {}).get("drivers") or [],
        "claims": (result or {}).get("claims") or [],
        "exposures": (result or {}).get("exposures") or [],
        "questions": (result or {}).get("questions") or [],
        "evidence_set_id": (result or {}).get("evidence_set_id"),
        "audit": (result or {}).get("audit") or {},
        "llm_calls": calls,
        "token_usage": _token_usage(calls),
        "glm52_called": any(str(row.get("role") or row.get("step") or "") in {"mechanical", "event_extract"} for row in calls),
        "glm53_called": any(
            str(row.get("llm_called") or False) and str(row.get("step") or "")
            in {"company_understanding", "value_drivers", "core_claims", "claim_reasoning", "pm_synthesis", "independent_critic"}
            for row in calls
        )
        or any(int(row.get("output_tokens") or 0) > 0 for row in calls),
        "critic_called": any(str(row.get("step") or "") == "independent_critic" for row in calls),
        "direct_llm_write": False,
        "phase0": {
            "path": "historical_evidence_glm_filters",
            "filters": [
                "evidence_set_allowed_ids",
                "normalize_state",
                "select_driver_universe",
                "select_core_max_5",
                "claims_require_drivers",
                "strip_unbound_facts",
            ],
        },
    }
