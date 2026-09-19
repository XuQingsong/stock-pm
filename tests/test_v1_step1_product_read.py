"""V1 Step 1: API / data mapping over persisted Brain. No second kernel. No GLM."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.pm_view import build_pm_view
from stock_pm.brain.product_read import (
    EMPTY_DOMINANT,
    PRICE_PARTIAL,
    PRICE_UNEXPLAINED,
    aggregate_dominant_drivers,
    attach_claim_detail,
    build_market_overview,
    is_fundamental_core_claim,
    is_trigger_event,
    structural_paths,
    ticker_sensitivities,
)
from stock_pm.brain.store import BrainStore
from stock_pm.brain.view import build_claim_detail
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService


def _seed_global_ai_driver(store: BrainStore) -> None:
    store.upsert_hypothesis(
        {
            "ticker": "AVGO",
            "canonical_key": "ai_demand",
            "kind": "ai_demand",
            "hypothesis": "AI capex expectations are the live market variable.",
            "name": "AI capex expectations",
            "status": "supported",
            "confidence": "medium",
            "supporting_observations": ["att_ai_tape"],
        }
    )
    store.upsert_hypothesis(
        {
            "ticker": "LITE",
            "canonical_key": "ai_demand",
            "kind": "ai_demand",
            "hypothesis": "Optical names are trading AI capex expectations, not one print.",
            "name": "AI capex expectations",
            "status": "active",
            "confidence": "medium",
        }
    )
    store.upsert_market_attention(
        {
            "ticker": "AVGO",
            "attention_id": "att_ai_tape",
            "name": "AI capex tape",
            "statement": "Tape is trading AI infrastructure spend expectations.",
        }
    )
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_type": "macro",
            "name": "AI capex expectations",
            "statement": "Hyperscaler AI spend remains the cross-asset variable.",
            "state_key": "ai_capex_expectations",
        }
    )


def _seed_meta_capex_event(store: BrainStore) -> None:
    store.insert_event(
        {
            "ticker": "AVGO",
            "event_id": "bev_meta_capex",
            "event_type": "capex",
            "title": "Meta raises AI capital expenditure",
            "subject": "Meta AI capex",
            "event_date": "2026-09-10",
            "materiality": "material",
        }
    )


def test_case1_meta_capex_is_trigger_not_dominant_driver() -> None:
    store = BrainStore()
    _seed_meta_capex_event(store)
    store.upsert_hypothesis(
        {
            "ticker": "AVGO",
            "canonical_key": "meta_capex",
            "kind": "company_specific",
            "hypothesis": "Meta raised AI capex and that is the story.",
            "status": "candidate",
        }
    )
    assert is_trigger_event(store.list_events("AVGO")[0]) is True
    empty = aggregate_dominant_drivers(store)
    assert empty == []
    _seed_global_ai_driver(store)
    drivers = aggregate_dominant_drivers(store)
    assert drivers
    blob = " ".join(f"{row.get('id')} {row.get('name')} {row.get('category')}" for row in drivers).lower()
    assert "meta" not in blob
    assert "bev_meta_capex" not in blob
    assert any(row.get("category") == "ai_capex_expectations" for row in drivers)
    assert "bev_meta_capex" in (drivers[0].get("trigger_event_ids") or [])
    overview = build_market_overview(store)
    assert overview["llm_invoked"] is False
    assert overview["empty_state"] is None
    assert all("meta" not in str(row.get("name") or "").lower() for row in overview["dominant_drivers"])


def test_case2_sensitivity_is_not_trigger_and_not_relevance() -> None:
    store = BrainStore()
    _seed_global_ai_driver(store)
    _seed_meta_capex_event(store)
    store.insert_driver(
        {
            "ticker": "AVGO",
            "driver_id": "bdrv_avgo_ai",
            "canonical_key": "ai_demand",
            "name": "AI demand durability",
            "category": "demand",
            "current_state": "Exposed to AI capex expectations through custom silicon.",
            "importance": "medium",
        }
    )
    store.insert_exposure(
        {
            "ticker": "AVGO",
            "exposure_id": "bexp_avgo_ai",
            "object_name": "AI capex expectations",
            "mechanism": "Custom silicon converts AI capex expectations into revenue.",
            "magnitude": "medium",
            "related_driver_id": "bdrv_avgo_ai",
        }
    )
    drivers = aggregate_dominant_drivers(store)
    rows = ticker_sensitivities(store, "AVGO", drivers)
    assert rows
    assert all(row.get("market_driver_id") != "bev_meta_capex" for row in rows)
    assert all("meta" not in str(row.get("market_driver_id") or "").lower() for row in rows)
    assert all(row.get("sensitivity") != row.get("current_relevance") or row.get("sensitivity") for row in rows)
    top = rows[0]
    assert top["sensitivity"] in {"low", "medium", "high"}
    assert top["current_relevance"] in {"low", "medium", "high"}
    assert top["sensitivity"] != top["current_relevance"]
    assert "bexp_avgo_ai" in (top.get("linked_exposure_ids") or [])
    assert "bdrv_avgo_ai" in (top.get("linked_driver_ids") or [])


def test_case4_core_claims_exclude_market_pricing_and_valuation() -> None:
    store = BrainStore()
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_fund",
            "title": "AI revenue durability",
            "statement": "Custom silicon demand remains durable.",
            "claim_type": "operating",
            "is_core": True,
            "importance": "high",
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_mkt",
            "title": "市场在交易AI资本开支",
            "statement": "The market is trading AI capex, not the print.",
            "claim_type": "operating",
            "is_core": True,
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_val",
            "title": "The premium multiple is conditional on rates",
            "statement": "Valuation is sensitive to rates.",
            "claim_type": "valuation",
            "claim_dimension": "valuation_sensitivity",
            "is_core": True,
        }
    )
    assert is_fundamental_core_claim(store.get_claim("bclm_fund")) is True
    assert is_fundamental_core_claim(store.get_claim("bclm_mkt")) is False
    assert is_fundamental_core_claim(store.get_claim("bclm_val")) is False
    snapshot = build_pm_view(store, "AVGO")
    titles = [row["title"] for row in snapshot["core_claims"]]
    assert titles == ["AI revenue durability"]
    excluded = [row["claim_id"] for row in snapshot.get("valuation_or_market_claims") or []]
    assert "bclm_mkt" in excluded
    assert "bclm_val" in excluded


def test_case5_trigger_is_not_structural_graph_root() -> None:
    store = BrainStore()
    store.upsert_causal_edge(
        {
            "ticker": "AVGO",
            "from_node": "bev_meta_capex",
            "to_node": "bdrv_avgo_ai",
            "from_type": "event",
            "to_type": "value_driver",
            "relationship_type": "event_to_state",
            "mechanism": "Meta capex print hits the driver.",
            "status": "observed",
        }
    )
    store.upsert_causal_edge(
        {
            "ticker": "AVGO",
            "from_node": "bst_ai_demand",
            "to_node": "bdrv_avgo_ai",
            "from_type": "company_state",
            "to_type": "value_driver",
            "relationship_type": "state_to_exposure",
            "mechanism": "Demand state feeds the AI driver.",
            "status": "supported",
            "evidence_ids": ["bev_meta_capex"],
        }
    )
    paths = structural_paths(store, "AVGO")
    assert paths
    assert all(row.get("from_node") != "bev_meta_capex" for row in paths)
    assert all(row.get("from_type") != "event" for row in paths)
    assert any("bev_meta_capex" in (row.get("evidence_ids") or []) for row in paths)


def test_case6_page_paths_never_invoke_llm(monkeypatch) -> None:
    store = BrainStore()
    _seed_global_ai_driver(store)
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_core",
            "title": "AI revenue durability",
            "statement": "Demand remains durable.",
            "is_core": True,
            "what_would_invalidate": "A named customer cuts AI spend.",
        }
    )
    research = ResearchService(store=InMemoryResearchStore())

    def boom(*args, **kwargs):
        raise AssertionError("page path must not call GLM or re-run Brain")

    monkeypatch.setattr("stock_pm.brain.pipeline.run_brain", boom)
    monkeypatch.setattr("stock_pm.brain.runtime.run_brain_update", boom)
    brain_api._override = {"research": research, "store": store}
    try:
        client = TestClient(api.app)
        market = client.get("/api/market/overview")
        company = client.get("/api/brain/AVGO/pm-view")
        claim = client.get("/api/brain/AVGO/claims/bclm_core")
        lite = client.get("/api/brain/LITE/pm-view")
    finally:
        brain_api._override = None
    assert market.status_code == 200
    assert company.status_code == 200
    assert claim.status_code == 200
    assert lite.status_code == 200
    assert market.json()["llm_invoked"] is False
    assert company.json()["llm_invoked"] is False
    assert claim.json()["llm_invoked"] is False
    assert lite.json()["llm_invoked"] is False
    assert claim.json()["what_would_invalidate"] == ["A named customer cuts AI spend."]


def test_case7_empty_persisted_states_are_honest() -> None:
    store = BrainStore()
    overview = build_market_overview(store)
    assert overview["llm_invoked"] is False
    assert overview["dominant_drivers"] == []
    assert overview["empty_state"] == EMPTY_DOMINANT
    assert overview["pricing_axis"] == []
    snapshot = build_pm_view(store, "AVGO")
    assert snapshot["core_claims"] == []
    assert snapshot["market_environment"]["sensitivities"] == []
    assert snapshot["market_environment"]["empty_state"] == EMPTY_DOMINANT
    assert snapshot["thesis"]["empty"] is True
    assert snapshot["quote"]["empty"] is True
    missing = build_claim_detail(store, ResearchService(store=InMemoryResearchStore()), "AVGO", "missing")
    assert missing is None


def test_unresolved_price_never_forces_single_cause() -> None:
    store = BrainStore()
    _seed_global_ai_driver(store)
    store.upsert_hypothesis(
        {
            "ticker": "AVGO",
            "canonical_key": "duration_reprice",
            "kind": "valuation",
            "hypothesis": "Duration risk is also in the tape.",
            "status": "candidate",
            "confidence": "low",
        }
    )
    store.upsert_divergence(
        {
            "ticker": "AVGO",
            "signature": "avgo-unexplained",
            "status": "open",
            "explanation_grade": "partially_explained",
            "unresolved_question": "Why did price fall more than the print explains?",
        }
    )
    snapshot = build_pm_view(store, "AVGO")
    attr = snapshot["price_attribution"]
    assert attr["forced_single_cause"] is False
    assert attr["price_is_not_claim_invalidation"] is True
    assert attr["status"] in {PRICE_PARTIAL, PRICE_UNEXPLAINED}
    assert len(attr["explanations"]) >= 2
    assert attr["unexplained"]


def test_http_market_and_company_and_claim_use_same_store(monkeypatch) -> None:
    store = BrainStore()
    _seed_global_ai_driver(store)
    _seed_meta_capex_event(store)
    store.insert_claim(
        {
            "ticker": "LITE",
            "claim_id": "bclm_lite",
            "title": "Datacom transceiver ramp",
            "statement": "Cloud transceivers remain the live claim.",
            "is_core": True,
        }
    )
    research = ResearchService(store=InMemoryResearchStore())
    brain_api._override = {"research": research, "store": store}
    try:
        client = TestClient(api.app)
        market = client.get("/api/market/overview").json()
        lite = client.get("/api/brain/LITE/pm-view").json()
        claim = client.get("/api/brain/LITE/claims/bclm_lite").json()
    finally:
        brain_api._override = None
    assert market["source"] == "persisted_brain"
    assert lite["source"] == "persisted_brain"
    assert claim["source"] == "persisted_brain"
    assert lite["core_claims"][0]["title"] == "Datacom transceiver ramp"
    assert attach_claim_detail(claim, store, "LITE")["llm_invoked"] is False
