from __future__ import annotations

from stock_pm.brain.budget import change_scope
from stock_pm.brain.causal import edge_can_transmit, transmit_path
from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.hysteresis import accumulate_claim_evidence, next_claim_status
from stock_pm.brain.layers import classify_brain_object, is_fast_layer, layer_speed, object_layer, slower_than
from stock_pm.brain.phase0 import evaluate_brain_changes
from stock_pm.brain.shadow import current_states_only, promote_shadow, shadow_blocks_current_state, should_enter_shadow
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import BRAIN_PHASE, COGNITIVE_LAYERS, CONSTITUTION_RULES
from stock_pm.migrate import discover_migrations


CORE_CLAIM = {
    "object_id": "bclm_avgo_duration",
    "status": "strongly_supported",
    "is_core": True,
    "claim_type": "operating",
    "statement": "Custom silicon demand remains durable through the current AI cycle.",
    "support_strength": 4,
    "counter_strength": 0,
}


def _seed_claim(store: BrainStore) -> dict:
    claim = store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_avgo_duration",
            "title": "AI demand duration",
            "statement": CORE_CLAIM["statement"],
            "claim_type": "operating",
            "status": "strongly_supported",
            "is_core": True,
            "importance": "high",
            "confidence": "high",
        }
    )
    version = store.insert_version(
        {
            "claim_id": claim["claim_id"],
            "version": 1,
            "statement": CORE_CLAIM["statement"],
            "status": "strongly_supported",
            "confidence": "high",
        }
    )
    return {"claim": claim, "version": version}


def test_phase0_objects_map_to_five_layers() -> None:
    assert BRAIN_PHASE == "phase0"
    assert COGNITIVE_LAYERS == (
        "observation",
        "market",
        "state",
        "investment_reasoning",
        "structural_knowledge",
    )
    assert object_layer("news") == "observation"
    assert object_layer("price") == "observation"
    assert object_layer("market_driver") == "market"
    assert object_layer("price_reaction") == "market"
    assert object_layer("company_state") == "state"
    assert object_layer("core_claim") == "investment_reasoning"
    assert object_layer("value_driver") == "investment_reasoning"
    assert object_layer("causal_edge") == "structural_knowledge"
    assert layer_speed("observation") == "fastest"
    assert layer_speed("market_attention") == "fast"
    assert layer_speed("company_state") == "medium"
    assert layer_speed("core_claim") == "slow"
    assert layer_speed("causal_edge") == "slowest"
    assert is_fast_layer("market")
    assert is_fast_layer("price_reaction")
    assert not is_fast_layer("core_claim")
    assert slower_than("core_claim", "event")
    assert slower_than("causal_relationship", "core_claim")
    assert classify_brain_object({"object_type": "shadow_state"})["layer"] == "state"
    assert len(CONSTITUTION_RULES) == 14


def test_case1_unconfirmed_google_order_enters_shadow() -> None:
    store = BrainStore()
    seeded = _seed_claim(store)
    rumor = {
        "kind": "news",
        "name": "possible_google_order_reduction",
        "subject": "possible_google_order_reduction",
        "title": "Unconfirmed: Google may reduce AVGO orders",
        "fact": "Google may reduce Broadcom custom-silicon orders.",
        "confidence": "low",
        "fact_reliability": "rumor",
        "materiality_if_true": "high",
        "event_key": "possible_google_order_reduction",
    }
    result = evaluate_brain_changes(
        ticker="AVGO",
        observations=[rumor],
        proposals=[
            {
                "object_type": "company_state",
                "source_kind": "news",
                "confidence": "low",
                "fact_reliability": "rumor",
                "name": "possible_google_order_reduction",
                "from_payload": {"statement": "Google orders are stable.", "confidence": "medium"},
                "to_payload": {
                    "name": "possible_google_order_reduction",
                    "statement": "Google is reducing AVGO orders.",
                    "confidence": "low",
                },
                "reason": "Unconfirmed order cut rumor.",
            },
            {
                "object_type": "core_claim",
                "object_id": CORE_CLAIM["object_id"],
                "source_kind": "news",
                "is_core": True,
                "from_payload": CORE_CLAIM,
                "to_payload": {**CORE_CLAIM, "status": "challenged", "statement": "Google order cut challenges duration."},
                "reason": "Rumor challenges the duration claim.",
            },
        ],
        store=store,
    )
    assert should_enter_shadow(rumor)
    assert result["shadows"]
    assert result["shadows"][0]["name"] == "possible_google_order_reduction"
    assert result["shadows"][0]["confidence"] == "low"
    assert shadow_blocks_current_state(result["shadows"][0])
    assert result["current_state_unchanged"] is True
    assert result["core_claims_unchanged"] is True
    assert result["approved"] == []
    assert store.list_shadows("AVGO")
    assert store.list_states("AVGO") == []
    assert len(store.list_versions(seeded["claim"]["claim_id"])) == 1
    assert store.claims[CORE_CLAIM["object_id"]]["status"] == "strongly_supported"


def test_case2_price_drop_without_fundamental_evidence() -> None:
    store = BrainStore()
    seeded = _seed_claim(store)
    result = evaluate_brain_changes(
        ticker="AVGO",
        observations=[
            {
                "kind": "price",
                "title": "AVGO -8% in one session",
                "fact": "AVGO closed down 8% with no new issuer filing.",
                "reason": "Single-day price move without new fundamental evidence.",
                "fundamental_evidence_ids": [],
            }
        ],
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CORE_CLAIM["object_id"],
                "source_kind": "price",
                "is_core": True,
                "from_payload": CORE_CLAIM,
                "to_payload": {
                    **CORE_CLAIM,
                    "status": "challenged",
                    "statement": "AVGO is mispriced after the drawdown.",
                },
                "reason": "Unexplained price move implies mispricing.",
            }
        ],
        store=store,
    )
    assert result["observations"]
    assert result["observations"][0]["layer"] == "observation"
    assert result["questions"]
    assert "market pricing" in result["questions"][0]["question"].lower()
    assert result["core_claims_unchanged"] is True
    rules = {row["rule"] for item in result["rejected"] for row in item.get("rules") or []}
    assert "price_cannot_modify_fundamental_claim" in rules
    assert "unexplained_price_is_not_mispricing" in rules
    assert store.claims[CORE_CLAIM["object_id"]]["status"] == "strongly_supported"
    assert len(store.list_versions(seeded["claim"]["claim_id"])) == 1
    assert store.list_news("AVGO")


def test_case3_candidate_causal_edge_stops_transmission() -> None:
    edges = [
        {"from_node": "meta_ai_capex", "to_node": "ai_infrastructure", "status": "supported"},
        {"from_node": "ai_infrastructure", "to_node": "networking_demand", "status": "candidate"},
        {"from_node": "networking_demand", "to_node": "avgo_eps", "status": "candidate"},
        {"from_node": "avgo_eps", "to_node": "core_claim", "status": "candidate"},
    ]
    walked = transmit_path(edges)
    assert walked["stopped"] is True
    assert walked["reached_claim"] is False
    assert walked["stopped_at"]["to_node"] == "networking_demand"
    assert not edge_can_transmit(edges[1])
    result = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CORE_CLAIM["object_id"],
                "source_kind": "event",
                "is_core": True,
                "from_payload": CORE_CLAIM,
                "to_payload": {**CORE_CLAIM, "status": "strongly_supported", "statement": "Meta capex lifts AVGO EPS."},
                "causal_edges": edges,
                "reason": "Meta capex should raise AVGO EPS.",
            }
        ],
    )
    assert result["approved"] == []
    assert result["core_claims_unchanged"] is True
    rules = {row["rule"] for item in result["rejected"] for row in item.get("rules") or []}
    assert "unsupported_causal_cannot_transmit" in rules


def test_case4_duplicate_outlets_do_not_version_claims() -> None:
    store = BrainStore()
    seeded = _seed_claim(store)
    outlets = ("Reuters", "Bloomberg", "WSJ", "FT", "CNBC")
    observations = [
        {
            "kind": "news",
            "event_key": "meta_ai_capex_raise",
            "subject": "meta_ai_capex_raise",
            "title": f"Meta raises 2026 AI capex - {outlet}",
            "url": f"https://example.com/{outlet.lower()}/meta-capex",
            "fact": "Meta raised 2026 AI capital expenditure.",
            "confidence": "high",
            "fact_reliability": "direct_fact",
            "confirmed": True,
        }
        for outlet in outlets
    ]
    proposals = [
        {
            "object_type": "core_claim",
            "object_id": CORE_CLAIM["object_id"],
            "source_kind": "news",
            "is_core": True,
            "duplicate": True,
            "title": item["title"],
            "new_fact": item["fact"],
            "from_payload": CORE_CLAIM,
            "to_payload": {**CORE_CLAIM, "new_version": True, "status": "strongly_supported"},
            "reason": "Repeat outlet coverage.",
        }
        for item in observations
    ]
    result = evaluate_brain_changes(
        ticker="AVGO",
        observations=observations,
        proposals=proposals,
        store=store,
        brain={"existing_facts": [CORE_CLAIM["statement"]]},
    )
    assert result["duplicate_count"] == 4
    assert len(result["observations"]) <= 1
    assert result["claim_versions_created"] == 0
    assert result["core_claims_unchanged"] is True
    assert len(store.list_versions(seeded["claim"]["claim_id"])) == 1
    assert all(row["decision"] == "reject" for row in result["rejected"])
    assert "duplicate_news_cannot_version_claim" in {
        rule["rule"] for row in result["rejected"] for rule in row.get("rules") or []
    }


def test_case5_abnormal_change_scope_requires_review() -> None:
    store = BrainStore()
    _seed_claim(store)
    proposals = [
        {
            "object_type": "core_claim",
            "object_id": f"claim_{idx}",
            "source_kind": "news",
            "is_core": True,
            "from_payload": {"status": "strongly_supported", "is_core": True, "statement": f"Claim {idx}"},
            "to_payload": {"status": "challenged", "is_core": True, "statement": f"Claim {idx} revised"},
            "reason": "Ordinary news rewrite.",
            "evidence_ids": ["ev_1"],
        }
        for idx in range(3)
    ]
    proposals.extend(
        {
            "object_type": "value_driver",
            "object_id": f"driver_{idx}",
            "source_kind": "news",
            "from_payload": {"name": f"Driver {idx}"},
            "to_payload": {"name": f"Driver {idx} rewritten"},
            "reason": "Ordinary news rewrite.",
        }
        for idx in range(2)
    )
    proposals.append(
        {
            "object_type": "scenario",
            "source_kind": "news",
            "to_payload": {"scope": "base", "base_case_change": True, "statement": "Rewrite base case."},
            "reason": "Ordinary news rewrite.",
        }
    )
    proposals.extend(
        {
            "object_type": "causal_edge",
            "source_kind": "news",
            "from_payload": {"status": "candidate"},
            "to_payload": {"status": "established", "from_node": f"a{idx}", "to_node": f"b{idx}"},
            "reason": "Ordinary news rewrite.",
        }
        for idx in range(3)
    )
    scope = change_scope(proposals)
    assert scope["abnormal_change_scope"] is True
    result = evaluate_brain_changes(ticker="AVGO", proposals=proposals, store=store)
    assert result["budget"]["requires_review"] is True
    assert result["requires_review"]
    assert result["auto_commit_allowed"] is False
    assert result["approved"] == []
    assert all(row["decision"] == "requires_review" for row in result["requires_review"])
    assert store.list_proposals("AVGO", decision="approve") == []
    assert store.list_history("AVGO") == []


def test_claim_hysteresis_single_news_cannot_flip_status() -> None:
    current = {"status": "strongly_supported", "support_strength": 4, "counter_strength": 0}
    held = next_claim_status(current, "challenged", independent_counter_count=1, source_kind="news")
    assert held["changed"] is False
    assert held["status"] == "strongly_supported"
    accumulated = accumulate_claim_evidence(current, direction="oppose", strength="medium")
    assert accumulated["counter_strength"] == 1
    assert accumulated["support_trend"] == "flat"
    stepped = next_claim_status(current, "challenged", independent_counter_count=2, source_kind="news")
    assert stepped["status"] != "challenged"
    assert stepped["status"] in {"partially_supported", "strongly_supported"}


def test_absence_of_evidence_is_not_counter_evidence() -> None:
    hits = constitution_violations(
        {
            "object_type": "core_claim",
            "source_kind": "news",
            "is_core": True,
            "from_payload": CORE_CLAIM,
            "to_payload": {"status": "challenged", "is_core": True, "statement": CORE_CLAIM["statement"]},
            "reason": "There is no evidence this is false.",
            "evidence_ids": [],
        }
    )
    assert any(row["rule"] == "absence_is_not_counter_evidence" for row in hits)


def test_related_company_cannot_prove_issuer_fact() -> None:
    hits = constitution_violations(
        {
            "object_type": "company_state",
            "source_kind": "news",
            "ticker": "AVGO",
            "from_payload": {"statement": "AVGO demand is stable."},
            "to_payload": {"statement": "AVGO demand is proven by Meta capex."},
            "evidence": {
                "source_url": "https://www.meta.com/investors/10q",
                "source_type": "official_document",
                "source": "meta.com",
                "fact": "Meta increased AI capex.",
                "raw_reference": {"query_type": "related_entity", "entity": "Meta"},
            },
        },
        brain={"ticker": "AVGO", "related_entities": [{"name": "Meta", "domain": "meta.com"}]},
    )
    assert any(row["rule"] == "related_entity_cannot_prove_issuer" for row in hits)


def test_phase0_migration_is_discovered() -> None:
    names = [item.filename for item in discover_migrations()]
    assert "migrations/0020_brain_phase0.sql" in names
    assert "migrations/0021_brain_phase1_runtime.sql" in names


def test_market_layer_is_fast_and_not_write_locked() -> None:
    hits = constitution_violations(
        {
            "object_type": "market_attention",
            "source_kind": "news",
            "from_payload": {"statement": "Market was focused on AI duration."},
            "to_payload": {"statement": "Market attention flipped to AI capex slowdown."},
            "reason": "Today the tape started pricing a capex slowdown.",
            "evidence_ids": ["ev_attn"],
        }
    )
    assert hits == []
    result = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "market_attention",
                "source_kind": "news",
                "from_payload": {"statement": "AI duration"},
                "to_payload": {"statement": "AI capex slowdown"},
                "reason": "Attention moved.",
                "evidence_ids": ["ev_attn"],
            }
        ],
    )
    assert result["approved"]
    assert result["approved"][0]["object_type"] == "market_attention"


def test_shadow_state_is_isolated_from_current_state() -> None:
    store = BrainStore()
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_type": "company",
            "name": "Google customer exposure",
            "statement": "Google remains a named customer.",
            "confidence": "medium",
        }
    )
    store.upsert_shadow(
        {
            "ticker": "AVGO",
            "name": "possible_google_order_reduction",
            "statement": "Google may reduce orders.",
            "confidence": "low",
            "status": "open",
        }
    )
    current = store.list_current_states("AVGO")
    shadows = store.list_shadows("AVGO")
    assert current and all("shadow" not in str(row.get("state_id") or "") for row in current)
    assert current_states_only(current + shadows) == current
    assert shadows
    assert promote_shadow(shadows[0]) is None
    proposal = promote_shadow(shadows[0], confirmed=True)
    assert proposal is not None
    assert proposal["source_kind"] == "shadow_confirmed"
    assert proposal["object_type"] == "company_state"


def test_rejected_proposals_are_persisted() -> None:
    store = BrainStore()
    _seed_claim(store)
    result = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CORE_CLAIM["object_id"],
                "source_kind": "news",
                "is_core": True,
                "from_payload": CORE_CLAIM,
                "to_payload": {**CORE_CLAIM, "status": "challenged"},
                "reason": "One article challenges duration.",
                "related_objects": ["bclm_avgo_duration"],
            }
        ],
        store=store,
    )
    assert result["rejected"]
    stored = store.list_proposals("AVGO", decision="reject")
    assert stored
    assert stored[0]["decision"] == "reject"
    assert stored[0]["reason_code"]
    assert stored[0]["created_at"]
    assert stored[0]["object_type"] == "core_claim"

