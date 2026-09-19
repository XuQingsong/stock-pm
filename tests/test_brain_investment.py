"""Investment reasoning chain: Claim → Impact → Scenario → Valuation → Thesis."""

from __future__ import annotations

import pytest

from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.investment import (
    apply_invalidation_evidence,
    build_downstream_objects,
    run_downstream_reasoning,
)
from stock_pm.brain.pm_view import build_pm_view
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.database import Database
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource

from test_brain_phase1 import FakeBrainCompleter, _pack
from test_brain_phase3 import Phase3Completer


def _claim(store: BrainStore, **overrides: object) -> dict:
    row = {
        "ticker": overrides.get("ticker") or "AVGO",
        "claim_id": overrides.get("claim_id") or "bclm_ai_demand",
        "title": "AI demand durability remains strong",
        "statement": "AI demand durability strengthened and remains the binding earnings variable.",
        "status": "partially_supported",
        "is_core": True,
        "confidence": "medium",
        "why_it_matters": "Higher AI revenue mix plus operating leverage.",
        "claim_subject": "demand_duration",
        "financial_driver": "revenue",
        "supporting_evidence_ids": ["rev_ai_support"],
        "what_would_invalidate": "AI demand slows or a named customer cuts.",
    }
    row.update(overrides)
    return store.insert_claim(row)


def _research(*, pe: float | None = 16.0) -> ResearchService:
    pack = _pack()
    pack["ticker"] = "AVGO"
    if pe is None:
        pack["company_profile"] = {**(pack.get("company_profile") or {}), "pe_ttm": None, "ev_ebitda": None, "ps_ttm": None}
        pack["missing_fields"] = list(pack.get("missing_fields") or []) + ["pe_ttm", "ev_ebitda"]
    else:
        pack["company_profile"] = {**(pack.get("company_profile") or {}), "pe_ttm": pe}
    source = DictPackSource.from_mapping("AVGO", pack)
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=FakeBrainCompleter())
    svc.store.upsert_pack(pack)
    return svc


def test_case1_positive_claim_chain() -> None:
    store = BrainStore()
    claim = _claim(store)
    store.upsert_evidence({"id": "rev_ai_support", "ticker": "AVGO", "fact": "AI demand continues to be very strong.", "source": "sec.gov"})
    result = run_downstream_reasoning(store, "AVGO", trigger="thesis_refresh", research=_research(), affected_claim_ids=[claim["claim_id"]])
    assert result["ran"] is True
    assert result["glm_called"] is False
    impacts = [row for row in result["impacts"] if row.get("claim_id") == claim["claim_id"]]
    metrics = {row.get("financial_metric") or row.get("metric"): row for row in impacts}
    assert metrics["revenue"]["direction"] == "positive"
    assert metrics["EPS"]["direction"] in {"positive", "uncertain"}
    assert metrics["operating_margin"]["direction"] in {"positive", "uncertain"}
    types = {row["scenario_type"]: row for row in result["scenarios"]}
    assert set(types) == {"bull", "base", "bear"}
    assert "strong" in " ".join(types["bull"]["assumptions"]).lower() or "demand" in " ".join(types["bull"]["assumptions"]).lower()
    valuation = result["valuation"]
    assert valuation is not None
    assert valuation["valuation_data_missing"] is False
    assert "pe_ttm" in (valuation.get("supporting_data") or {})
    assert "fair_value" not in (valuation.get("supporting_data") or {})
    assert "price_target" not in (valuation.get("supporting_data") or {})
    thesis = result["thesis"]
    assert claim["claim_id"] in (thesis.get("top_supporting_claim_ids") or [])
    assert thesis["base_scenario_id"] == types["base"]["scenario_id"]
    updated = store.get_claim(claim["claim_id"])
    assert updated["what_would_invalidate"]
    assert updated["financial_impact_ids"]
    assert updated["scenario_implication"]
    snap = build_pm_view(store, "AVGO")
    assert snap["llm_invoked"] is False
    assert snap["financial_impacts"]
    assert snap["base_scenario"]["scenario_type"] == "base"
    assert snap["valuation_state"]["valuation_id"] == valuation["valuation_id"]
    assert snap["current_thesis"]["thesis_id"] == thesis["thesis_id"]


def test_case2_risk_claim_does_not_flip_thesis() -> None:
    store = BrainStore()
    positive = _claim(store)
    risk = _claim(
        store,
        claim_id="bclm_concentration",
        title="Customer concentration risk materially rises",
        statement="Unquantified customer concentration is now a material operating risk.",
        claim_subject="customer_concentration",
        why_it_matters="A large buyer cut would hit revenue and the multiple.",
        what_would_invalidate="Concentration declines with independent customer evidence.",
    )
    first = run_downstream_reasoning(store, "AVGO", trigger="thesis_refresh", research=_research(), affected_claim_ids=[positive["claim_id"]])
    second = run_downstream_reasoning(store, "AVGO", trigger="material_claim_change", research=_research())
    assert second["ran"] is True
    impacts = [row for row in second["impacts"] if row.get("claim_id") == risk["claim_id"]]
    assert any(row.get("direction") == "negative" for row in impacts)
    bear = next(row for row in second["scenarios"] if row["scenario_type"] == "bear")
    first_bear = next(row for row in first["scenarios"] if row["scenario_type"] == "bear")
    assert bear["probability_band"] in {"medium", "high"}
    rank = {"low": 0, "unknown": 0, "medium": 1, "high": 2}
    assert rank[bear["probability_band"]] >= rank.get(first_bear["probability_band"], 0)
    valuation = second["valuation"]
    assert valuation["valuation_direction"] in {"compression_risk", "neutral", "uncertain"}
    thesis = second["thesis"]
    assert risk["claim_id"] in (thesis.get("top_risk_claim_ids") or [])
    assert positive["claim_id"] in (thesis.get("top_supporting_claim_ids") or [])
    assert "working" in (thesis.get("current_thesis") or "").lower() or thesis.get("base_scenario_id")
    assert thesis.get("current_thesis") != "sell"
    updated = store.get_claim(risk["claim_id"])
    assert updated["scenario_implication"] == "bear_support_up"


def test_case3_price_only_cannot_write_downstream() -> None:
    store = BrainStore()
    claim = _claim(store)
    before = run_downstream_reasoning(store, "AVGO", trigger="thesis_refresh", research=_research())
    impact_ids = {row["impact_id"] for row in before["impacts"]}
    scenario_ids = {row["scenario_id"]: row.get("probability_band") for row in before["scenarios"]}
    valuation_id = before["valuation"]["valuation_id"]
    thesis_text = before["thesis"]["current_thesis"]
    result = run_brain_update(
        ticker="AVGO",
        item={
            "kind": "price",
            "event_type": "other",
            "title": "AVGO shares fall 8% with no new filing",
            "fact": "Stock -8% with no new fundamental evidence.",
            "price_change_pct": -8.0,
            "fact_reliability": "signal",
        },
        store=store,
        completer=Phase3Completer("path"),
    )
    assert (result.get("downstream") or {}).get("ran") is False
    after_impacts = {row["impact_id"] for row in store.list_financial_impacts("AVGO")}
    after_scenarios = {row["scenario_id"]: row.get("probability_band") for row in store.list_scenarios("AVGO")}
    assert after_impacts == impact_ids
    assert after_scenarios == scenario_ids
    assert store.latest_valuation_state("AVGO")["valuation_id"] == valuation_id
    assert store.latest_thesis("AVGO")["current_thesis"] == thesis_text
    price_hits = constitution_violations(
        {
            "object_type": "thesis_snapshot",
            "source_kind": "price",
            "to_payload": {"current_thesis": "Price proves the thesis is broken.", "claim_id": claim["claim_id"]},
            "reason": "Tape down 8%.",
        }
    )
    assert any(row["rule"] == "price_cannot_modify_investment_downstream" for row in price_hits)
    event_hits = constitution_violations(
        {
            "object_type": "thesis_snapshot",
            "source_kind": "event",
            "to_payload": {"current_thesis": "One print flips the thesis."},
            "reason": "Single event rewrite.",
        }
    )
    assert any(row["rule"] == "event_cannot_modify_investment_downstream" for row in event_hits)


def test_case4_missing_valuation_data_is_explicit() -> None:
    store = BrainStore()
    _claim(store)
    built = build_downstream_objects(ticker="AVGO", claims=store.list_active_claims("AVGO"), research=_research(pe=None), store=store)
    valuation = built["valuation"]
    assert valuation["valuation_data_missing"] is True
    data = valuation.get("supporting_data") or {}
    assert "pe_ttm" not in data
    assert "fair_value" not in data
    assert "price_target" not in data
    assert "target_multiple" not in data
    result = run_downstream_reasoning(store, "AVGO", trigger="thesis_refresh", research=_research(pe=None))
    stored = result["valuation"]
    assert stored["valuation_data_missing"] is True
    assert "fair_value" not in (stored.get("supporting_data") or {})


def test_case5_persistence_survives_new_store() -> None:
    from stock_pm.research.ids import new_id

    db = Database()
    if not db.ping():
        db.close()
        pytest.skip("PostgreSQL is not reachable")
    db.initialize()
    ticker = f"IZ{new_id('t')[-4:]}".upper()
    writer = BrainStore(db)
    claim = _claim(writer, ticker=ticker, claim_id=new_id("bclm"))
    svc = _research()
    result = run_downstream_reasoning(writer, ticker, trigger="thesis_refresh", research=svc)
    assert result["ran"] is True
    reader = BrainStore(db)
    impacts = reader.list_financial_impacts(ticker)
    assert any(row.get("claim_id") == claim["claim_id"] for row in impacts)
    assert {row.get("scenario_type") for row in reader.list_scenarios(ticker)} == {"bull", "base", "bear"}
    assert reader.latest_valuation_state(ticker) is not None
    assert reader.latest_thesis(ticker) is not None
    snap = build_pm_view(reader, ticker)
    assert snap["llm_invoked"] is False
    assert snap["financial_impacts"]
    assert snap["base_scenario"]
    assert snap["valuation_state"]
    assert snap["current_thesis"]
    db.close()


def test_case6_invalidation_updates_momentum_not_delete() -> None:
    store = BrainStore()
    claim = _claim(
        store,
        what_would_invalidate="customer concentration worsens with independent buyer evidence",
    )
    before = run_downstream_reasoning(store, "AVGO", trigger="thesis_refresh", research=_research())
    event = {
        "kind": "news",
        "title": "Top customers now account for a much larger share of demand",
        "fact": "Customer concentration worsens as the two largest buyers increase share.",
        "evidence_id": "rev_conc_hit",
        "source": "sec.gov",
        "fact_reliability": "direct_fact",
    }
    hits = apply_invalidation_evidence(store, "AVGO", event=event, claims=[store.get_claim(claim["claim_id"])])
    assert hits
    assert hits[0]["deleted"] is False
    live = store.get_claim(claim["claim_id"])
    assert live is not None
    assert live["status"] == claim["status"]
    links = store.list_links(claim_id=claim["claim_id"])
    assert any(row.get("direction") == "oppose" for row in links)
    after = run_downstream_reasoning(store, "AVGO", trigger="material_claim_change", research=_research())
    assert after["ran"] is True
    assert not any(str(row.get("decision") or "") == "reject" for row in after.get("rejected") or [])
    assert after["impacts"]
    assert after["scenarios"]
    assert after["thesis"]
    assert store.list_history("AVGO")
    assert live["claim_id"] == claim["claim_id"]


def test_event_cannot_write_claim_linked_financial_impact() -> None:
    hits = constitution_violations(
        {
            "object_type": "financial_impact",
            "source_kind": "event",
            "to_payload": {"claim_id": "bclm_x", "financial_metric": "revenue", "direction": "positive"},
            "reason": "Event jumps to financial impact.",
        }
    )
    assert any(row["rule"] == "event_cannot_modify_investment_downstream" for row in hits)
    allowed = constitution_violations(
        {
            "object_type": "financial_impact",
            "source_kind": "event",
            "to_payload": {
                "object_type": "driver",
                "object_id": "bdrv_x",
                "metric": "revenue",
                "direction": "up",
                "scope": "scenario_only",
            },
            "reason": "Express the financial transmission.",
        }
    )
    assert not any(row["rule"] == "event_cannot_modify_investment_downstream" for row in allowed)
