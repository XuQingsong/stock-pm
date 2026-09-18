from __future__ import annotations

import json

from stock_pm.brain.causal import (
    assess_event_transmissions,
    detect_causal_gaps,
    edge_can_transmit,
    financial_edges_from_drivers,
    next_edge_status,
    normalize_causal_edge,
    transmit_path,
)
from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.exposure import normalize_exposure, relevant_exposures
from stock_pm.brain.layers import object_layer
from stock_pm.brain.phase0 import evaluate_brain_changes
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import BRAIN_RUNTIME, CAUSAL_EDGE_STATUSES, CONSTITUTION_RULES, TRANSMITTABLE_EDGE_STATUSES
from stock_pm.migrate import discover_migrations


CLAIM_ID = "bclm_duration"
DRIVER_ID = "bdrv_ai_demand"
EXPOSURE_ID = "bexp_avgo_asic"
STATE_ID = "bst_ai_infra"
EVENT_NODE = "hyperscaler_ai_capex"


def _edge(src: str, dst: str, status: str, **extra: object) -> dict:
    payload = {
        "from_node": src,
        "to_node": dst,
        "status": status,
        "relationship_type": extra.pop("relationship_type", "other"),
        "mechanism": extra.pop("mechanism", f"{src} -> {dst}"),
        "support_evidence_ids": extra.pop("support_evidence_ids", ["rev_path"]),
        **extra,
    }
    edge = normalize_causal_edge(payload, ticker="AVGO")
    assert edge is not None
    return edge


def _supported_path(*, middle_status: str = "supported") -> list[dict]:
    return [
        _edge(EVENT_NODE, STATE_ID, "supported", relationship_type="event_to_state", from_type="event", to_type="company_state"),
        _edge(STATE_ID, EXPOSURE_ID, middle_status, relationship_type="state_to_exposure", from_type="company_state", to_type="exposure"),
        _edge(EXPOSURE_ID, DRIVER_ID, "supported", relationship_type="exposure_to_driver", from_type="exposure", to_type="value_driver"),
        _edge(DRIVER_ID, CLAIM_ID, "supported", relationship_type="driver_to_claim", from_type="value_driver", to_type="core_claim"),
    ]


def _seed_brain(store: BrainStore, *, edges: list[dict] | None = None) -> None:
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_id": STATE_ID,
            "state_type": "company",
            "name": "AI infrastructure deployment",
            "statement": "Hyperscaler AI infrastructure deployment remains elevated.",
            "confidence": "medium",
        }
    )
    store.insert_driver(
        {
            "ticker": "AVGO",
            "driver_id": DRIVER_ID,
            "canonical_key": "ai_semiconductor_demand_durability",
            "name": "AI semiconductor demand durability",
            "category": "demand",
            "financial_link": "revenue",
            "why_it_matters": "Unit demand theoretically lifts AI revenue.",
            "current_state": "Custom silicon demand remains strong.",
            "evidence_ids": ["rev_exhibit"],
            "related_claim_ids": [CLAIM_ID],
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": CLAIM_ID,
            "title": "AI revenue durability",
            "statement": "AI revenue durability remains high.",
            "claim_type": "operating",
            "status": "strongly_supported",
            "is_core": True,
            "related_driver_ids": [DRIVER_ID],
        }
    )
    store.insert_exposure(
        {
            "ticker": "AVGO",
            "exposure_id": EXPOSURE_ID,
            "subject": "AVGO",
            "object_name": "Hyperscaler custom silicon / ASIC demand",
            "exposure_type": "customer",
            "direction": "positive",
            "magnitude": "high",
            "mechanism": "AVGO sells custom silicon to hyperscalers.",
            "reason": "Named hyperscaler ASIC exposure.",
            "related_driver_id": DRIVER_ID,
            "related_claim_id": CLAIM_ID,
            "can_affect_claim": True,
            "direct_or_indirect": "direct",
        }
    )
    store.upsert_evidence(
        {
            "id": "rev_exhibit",
            "ticker": "AVGO",
            "title": "Exhibit 99.1",
            "fact": "AI accelerator and networking demand continues to be very strong.",
        }
    )
    for edge in edges or _supported_path():
        store.upsert_causal_edge(edge)


class Phase2Completer:
    def __init__(self, mode: str = "path") -> None:
        self.mode = mode
        self.calls: list[str] = []

    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        text = user.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            payload, _end = json.JSONDecoder().raw_decode(text[start:])
        if "STEP_ID: event_extract" in system:
            self.calls.append("event_extract")
            item = payload.get("item") or {}
            blob = f"{item.get('title') or ''} {item.get('fact') or ''}".lower()
            return _ok(
                {
                    "fact": item.get("fact") or item.get("title") or "",
                    "event": item.get("title") or "",
                    "entities": ["Meta", "Google"] if "meta" in blob or "google" in blob or "hyperscaler" in blob else ["AVGO"],
                    "event_type": "capex" if "capex" in blob else "customer",
                    "novelty": "new",
                    "confidence": "high",
                    "fact_reliability": "direct_fact",
                    "material": True,
                    "possible_affected": [
                        "ai_semiconductor_demand_durability",
                        "customer_concentration",
                        "AI revenue durability",
                    ],
                    "reason": "fixture extract",
                }
            )
        if "STEP_ID: change_proposals" in system:
            self.calls.append("change_proposals")
            event = payload.get("event") or {}
            snapshot = payload.get("snapshot") or {}
            if self.mode == "new_edge":
                body = {
                    "proposals": [
                        {
                            "object_type": "causal_edge",
                            "source_kind": "event",
                            "to": {
                                "from_node": "meta_ai_capex",
                                "to_node": EXPOSURE_ID,
                                "relationship_type": "customer",
                                "mechanism": "Meta incremental AI capex may raise AVGO ASIC demand.",
                                "status": "candidate",
                            },
                            "reason": "Possible new relationship; start as candidate.",
                        }
                    ],
                    "questions": [],
                }
            elif self.mode == "established_edge":
                body = {
                    "proposals": [
                        {
                            "object_type": "causal_edge",
                            "source_kind": "event",
                            "to": {
                                "from_node": "meta_ai_capex",
                                "to_node": EXPOSURE_ID,
                                "status": "established",
                                "mechanism": "One article proves the relationship.",
                            },
                            "reason": "Invalid established write.",
                        }
                    ],
                    "questions": [],
                }
            elif self.mode == "jump":
                claim_id = ((snapshot.get("claims") or [{}])[0] or {}).get("claim_id") or CLAIM_ID
                body = {
                    "proposals": [
                        {
                            "object_type": "core_claim",
                            "object_id": claim_id,
                            "source_kind": "news",
                            "is_core": True,
                            "from": {"status": "strongly_supported", "is_core": True, "statement": "Duration holds."},
                            "to": {"status": "challenged", "is_core": True, "statement": "Meta capex directly changes the claim."},
                            "reason": "Unsupported Event to Claim jump.",
                        }
                    ],
                    "questions": [],
                }
            elif self.mode == "financial":
                body = {
                    "proposals": [
                        {
                            "object_type": "financial_impact",
                            "source_kind": "event",
                            "to": {
                                "object_type": "driver",
                                "object_id": DRIVER_ID,
                                "metric": "revenue",
                                "direction": "up",
                                "mechanism": "Customer demand theoretically increases revenue.",
                                "scope": "scenario_only",
                            },
                            "reason": "Driver to financial metric, not Base Case.",
                        }
                    ],
                    "questions": [],
                }
            elif self.mode == "counter":
                edges = snapshot.get("causal_edges") or []
                target = next((row for row in edges if str(row.get("from_node") or "") == EXPOSURE_ID), edges[0] if edges else {})
                body = {
                    "proposals": [
                        {
                            "object_type": "causal_edge",
                            "object_id": target.get("edge_id"),
                            "source_kind": "news",
                            "from": target,
                            "to": {
                                **target,
                                "status": "challenged",
                                "counter_evidence_ids": ["rev_counter"],
                            },
                            "independent_counter_count": 1,
                            "evidence_ids": ["rev_counter"],
                            "reason": "Customer dual-sourcing challenges the exposure edge.",
                        }
                    ],
                    "questions": [],
                }
            else:
                body = {
                    "proposals": [
                        {
                            "object_type": "market_attention",
                            "source_kind": "news",
                            "to": {"statement": "Market attention on hyperscaler AI capex."},
                            "reason": "Material capex event along a known causal path.",
                            "evidence_ids": ["rev_exhibit"],
                        }
                    ],
                    "questions": [],
                }
            assert snapshot.get("full_brain") is not True
            return _ok(body)
        self.calls.append("other")
        return _ok({})


def _ok(body: dict) -> dict:
    return {
        "status": "ok",
        "payload": body,
        "model": "fake-brain",
        "provider": "test",
        "llm_called": True,
        "llm_status": "ok",
        "fallback_used": False,
        "input_tokens": 12,
        "output_tokens": 18,
        "latency_ms": 4,
    }


def _capex_event() -> dict:
    return {
        "kind": "news",
        "event_id": "bev_meta_capex",
        "event_key": EVENT_NODE,
        "subject": EVENT_NODE,
        "title": "Meta raises 2026 hyperscaler AI capex",
        "fact": "Meta increased AI capital expenditure, supporting custom silicon and networking demand.",
        "event_type": "capex",
        "entities": ["Meta"],
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "confirmed": True,
    }


def test_phase2_runtime_flag_and_graph_reuses_brain_objects() -> None:
    assert BRAIN_RUNTIME == "phase2"
    assert object_layer("exposure") == "state"
    assert object_layer("causal_edge") == "structural_knowledge"
    assert object_layer("causal_gap") == "structural_knowledge"
    assert object_layer("financial_metric") == "investment_reasoning"
    assert object_layer("company_state") == "state"
    assert object_layer("value_driver") == "investment_reasoning"
    assert object_layer("core_claim") == "investment_reasoning"
    assert "candidate" in CAUSAL_EDGE_STATUSES
    assert "established" in TRANSMITTABLE_EDGE_STATUSES
    assert not edge_can_transmit({"status": "candidate"})
    names = [item.filename for item in discover_migrations()]
    assert "migrations/0022_brain_phase2_causal.sql" in names
    assert len(CONSTITUTION_RULES) == 17


def test_case1_supported_path_can_transmit() -> None:
    edges = _supported_path()
    walked = transmit_path(edges)
    assert walked["stopped"] is False
    assert walked["reached_claim"] is True
    store = BrainStore()
    _seed_brain(store, edges=edges)
    for idx in range(12):
        store.upsert_causal_edge(_edge(f"noise_{idx}", f"noise_t_{idx}", "supported"))
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase2Completer("path"),
    )
    assert result["path"] == "incremental"
    assert result["snapshot"]["targeted"] is True
    assert result["snapshot"]["full_brain"] is False
    assert len(result["snapshot"]["causal_edges"]) <= 8
    assert len(result["snapshot"]["causal_edges"]) < 12
    assert result["transmission"]["successful_count"] >= 1
    assert result["transmission"]["blocked_count"] == 0
    assert result["core_claims_unchanged"] is True
    assert result["unsupported_jump_count"] == 0
    assert result["unexpected_claim_change_count"] == 0
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["trace"]["glm53_causal_context_tokens"] >= 0
    assert result["snapshot"]["causal_paths"]
    assert any(EXPOSURE_ID in (row.get("nodes") or []) or EXPOSURE_ID in (row.get("edge_ids") or []) for row in result["snapshot"]["causal_paths"]) or any(
        str(edge.get("from_node") or "") == EXPOSURE_ID or str(edge.get("to_node") or "") == EXPOSURE_ID
        for edge in result["snapshot"]["causal_edges"]
    )


def test_case2_candidate_edge_stops_downstream_writes() -> None:
    edges = _supported_path(middle_status="candidate")
    walked = transmit_path(edges)
    assert walked["stopped"] is True
    assert not edge_can_transmit(edges[1])
    result = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "value_driver",
                "object_id": DRIVER_ID,
                "source_kind": "event",
                "to_payload": {"current_state": "Demand rewritten from a candidate path."},
                "causal_edges": edges,
                "reason": "Should stop before the driver.",
            },
            {
                "object_type": "core_claim",
                "object_id": CLAIM_ID,
                "source_kind": "event",
                "is_core": True,
                "from_payload": {"status": "strongly_supported", "is_core": True, "statement": "AI revenue durability remains high."},
                "to_payload": {"status": "challenged", "is_core": True, "statement": "Claim rewritten."},
                "causal_edges": edges,
                "reason": "Should stop before the claim.",
            },
        ],
        brain={"causal_edges": edges, "event_nodes": [EVENT_NODE]},
    )
    rules = {row["rule"] for item in result["rejected"] for row in item.get("rules") or []}
    assert "unsupported_causal_cannot_transmit" in rules
    assert result["approved"] == []
    assert result["core_claims_unchanged"] is True


def test_case3_new_relationship_starts_candidate_not_established() -> None:
    store = BrainStore()
    approved = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "source_kind": "event",
                "to_payload": {
                    "from_node": "meta_ai_capex",
                    "to_node": EXPOSURE_ID,
                    "relationship_type": "customer",
                    "mechanism": "Meta capex may flow into AVGO ASIC exposure.",
                    "status": "candidate",
                },
                "reason": "Newly discovered relationship.",
            }
        ],
        store=store,
    )
    assert approved["approved"]
    assert approved["approved"][0]["to_payload"]["status"] == "candidate"
    persisted = store.list_causal_edges("AVGO")
    assert persisted
    assert persisted[0]["status"] == "candidate"
    hits = constitution_violations(
        {
            "object_type": "causal_edge",
            "source_kind": "event",
            "to_payload": {"from_node": "a", "to_node": "b", "status": "established"},
            "reason": "One article.",
        }
    )
    assert any(row["rule"] == "new_causal_edge_starts_candidate" for row in hits)
    blocked_store = BrainStore()
    rejected = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "source_kind": "news",
                "to_payload": {"from_node": "a", "to_node": "b", "status": "established", "mechanism": "skip"},
                "reason": "Cannot establish from one event.",
            }
        ],
        store=blocked_store,
    )
    assert rejected["approved"] == []
    assert any(
        any(rule.get("rule") == "new_causal_edge_starts_candidate" for rule in (row.get("rules") or []))
        for row in rejected["rejected"]
    )
    assert blocked_store.list_causal_edges("AVGO") == []


def test_case4_counter_evidence_challenges_edge_without_erasing_history() -> None:
    store = BrainStore()
    edge = _edge(
        EXPOSURE_ID,
        DRIVER_ID,
        "established",
        relationship_type="exposure_to_driver",
        support_evidence_ids=["rev_support_1", "rev_support_2"],
        support_strength=3,
    )
    stored = store.upsert_causal_edge(edge)
    stepped = next_edge_status(stored, "challenged", independent_counter_count=1, source_kind="news")
    assert stepped["status"] == "challenged"
    result = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "object_id": stored["edge_id"],
                "source_kind": "news",
                "from_payload": stored,
                "to_payload": {
                    **stored,
                    "status": "challenged",
                    "counter_evidence_ids": ["rev_counter"],
                },
                "independent_counter_count": 1,
                "evidence_ids": ["rev_counter"],
                "reason": "Customer dual-source plan challenges the exposure.",
            }
        ],
        brain={"causal_edges": [stored]},
        store=store,
    )
    assert result["approved"]
    updated = store.list_causal_edges("AVGO")[0]
    assert updated["status"] == "challenged"
    assert "rev_support_1" in (updated.get("support_evidence_ids") or [])
    assert "rev_counter" in (updated.get("counter_evidence_ids") or [])
    history = store.list_history("AVGO")
    assert history
    assert updated["edge_id"] == stored["edge_id"]


def test_case5_causal_gap_creates_research_question_not_a_jump() -> None:
    partial = [_edge(EVENT_NODE, STATE_ID, "supported", relationship_type="event_to_state")]
    event = _capex_event()
    gaps = detect_causal_gaps(
        event=event,
        edges=partial,
        related_claims=[{"claim_id": CLAIM_ID, "title": "AI revenue durability"}],
        states=[{"state_id": STATE_ID, "name": "AI infrastructure deployment"}],
    )
    assert gaps
    hits = constitution_violations(
        {
            "object_type": "core_claim",
            "object_id": CLAIM_ID,
            "source_kind": "event",
            "from_payload": {"status": "strongly_supported", "is_core": True, "statement": "holds"},
            "to_payload": {"status": "challenged", "is_core": True, "statement": "Meta capex changes the claim."},
            "reason": "Jump.",
        },
        brain={"causal_edges": partial, "event_nodes": [EVENT_NODE]},
    )
    assert any(row["rule"] in {"unsupported_event_claim_jump", "news_cannot_modify_core_claim"} for row in hits)
    store = BrainStore()
    _seed_brain(store, edges=partial)
    result = run_brain_update(
        ticker="AVGO",
        item=event,
        store=store,
        completer=Phase2Completer("jump"),
    )
    assert result["core_claims_unchanged"] is True
    assert result["unsupported_jump_count"] == 0
    assert result["snapshot"]["causal_gaps"] or result["questions"] or store.list_questions("AVGO")
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["snapshot"]["full_brain"] is False


def test_case6_driver_to_financial_metric_cannot_modify_base() -> None:
    driver = {
        "driver_id": DRIVER_ID,
        "canonical_key": "ai_semiconductor_demand_durability",
        "financial_link": "revenue",
        "why_it_matters": "Unit demand theoretically lifts revenue.",
        "evidence_ids": ["rev_exhibit"],
    }
    links = financial_edges_from_drivers([driver], ticker="AVGO")
    assert links
    assert links[0]["to_node"] == "revenue"
    assert links[0]["relationship_type"] == "driver_to_financial"
    allowed = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "financial_impact",
                "source_kind": "event",
                "to_payload": {
                    "object_type": "driver",
                    "object_id": DRIVER_ID,
                    "metric": "revenue",
                    "direction": "up",
                    "mechanism": "Customer demand theoretically increases revenue.",
                    "scope": "scenario_only",
                },
                "reason": "Express the financial transmission.",
            }
        ],
        store=BrainStore(),
    )
    assert allowed["approved"]
    blocked = constitution_violations(
        {
            "object_type": "financial_impact",
            "source_kind": "event",
            "to_payload": {
                "object_id": DRIVER_ID,
                "metric": "revenue",
                "scope": "base",
                "base_case_change": True,
            },
            "reason": "Rewrite base case from a driver link.",
        }
    )
    assert any(row["rule"] == "financial_transmission_cannot_modify_base" for row in blocked)
    store = BrainStore()
    _seed_brain(store)
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase2Completer("financial"),
    )
    assert result["snapshot"]["financial_links"]
    assert result["snapshot"]["financial_links"][0]["to_node"] == "revenue"
    assert result["core_claims_unchanged"] is True
    assert not any(
        str((row.get("to_payload") or {}).get("scope") or "") == "base" and row.get("decision") == "approve"
        for row in result["gate"]["approved"]
    )


def test_exposure_is_a_first_class_brain_object() -> None:
    row = normalize_exposure(
        {
            "subject": "AVGO",
            "object_name": "Google AI ASIC demand",
            "exposure_type": "customer",
            "direction": "positive",
            "magnitude": "high",
            "mechanism": "Google is a named custom-silicon customer.",
            "related_driver_id": DRIVER_ID,
        },
        ticker="AVGO",
    )
    assert row["subject"] == "AVGO"
    assert row["object_name"]
    assert row["direction"] == "positive"
    assert row["mechanism"]
    matched = relevant_exposures(
        event={"title": "Google ASIC expansion", "entities": ["Google"], "event_type": "customer"},
        exposures=[row],
        driver_ids={DRIVER_ID},
    )
    assert matched


def test_phase1_targeted_snapshot_still_holds_with_causal_context() -> None:
    store = BrainStore()
    _seed_brain(store)
    store.insert_driver(
        {
            "ticker": "AVGO",
            "driver_id": "bdrv_leverage",
            "canonical_key": "balance_sheet_leverage_deleveraging",
            "name": "Balance sheet leverage",
            "category": "capital_allocation",
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_tax",
            "title": "Tax rate stability",
            "statement": "Tax is not the live debate.",
            "is_core": False,
        }
    )
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase2Completer("path"),
    )
    snapshot = result["snapshot"]
    driver_ids = {row.get("driver_id") for row in snapshot["drivers"]}
    claim_ids = {row.get("claim_id") for row in snapshot["claims"]}
    assert DRIVER_ID in driver_ids
    assert "bdrv_leverage" not in driver_ids
    assert CLAIM_ID in claim_ids
    assert "bclm_tax" not in claim_ids
    assert snapshot["full_brain"] is False
    assert len(snapshot["causal_edges"]) <= 8


def test_assess_transmissions_counts_success_and_block() -> None:
    ok = assess_event_transmissions(
        event=_capex_event(),
        edges=_supported_path(),
        claims=[{"claim_id": CLAIM_ID, "title": "AI revenue durability"}],
        exposures=[{"exposure_id": EXPOSURE_ID, "object_name": "ASIC", "exposure_type": "customer"}],
        states=[{"state_id": STATE_ID, "name": "AI infrastructure deployment"}],
    )
    assert ok["successful_count"] >= 1
    blocked = assess_event_transmissions(
        event=_capex_event(),
        edges=_supported_path(middle_status="candidate"),
        claims=[{"claim_id": CLAIM_ID, "title": "AI revenue durability"}],
        exposures=[{"exposure_id": EXPOSURE_ID, "object_name": "ASIC", "exposure_type": "customer"}],
        states=[{"state_id": STATE_ID, "name": "AI infrastructure deployment"}],
    )
    assert blocked["blocked_count"] >= 1
    assert blocked["successful_count"] == 0
