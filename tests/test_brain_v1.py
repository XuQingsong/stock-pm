from __future__ import annotations

from dataclasses import replace

from stock_pm.brain.drivers import (
    is_print_restatement,
    make_canonical_key,
    make_driver_key,
    normalize_driver,
    select_driver_universe,
)
from stock_pm.brain.routing import (
    ROLE_MECHANICAL,
    ROLE_REASONING,
    canonical_brain_model,
    layer_settings,
    resolve_brain_completers,
)
from stock_pm.brain.events import build_event
from stock_pm.brain.exposure import infer_exposure, may_affect_company_claim, related_entity_cannot_prove_issuer
from stock_pm.brain.knowledge import classify_information
from stock_pm.brain.state_layer import make_state_key, normalize_state
from stock_pm.brain.financial_bridge import normalize_financial_impact
from stock_pm.brain.scenario import apply_scenario_policy, qualifies_for_base
from stock_pm.brain.critic import reconcile_critic
from stock_pm.brain.transmission import validate_transmission
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.brain.pipeline import run_brain

from test_brain_phase1 import FakeBrainCompleter, _seed_evidence, _service


def test_revenue_print_is_not_a_value_driver() -> None:
    assert is_print_restatement("Revenue grew 20%", "Revenue grew 20% in the latest quarter")
    allowed = {"rev_1"}
    raw = {
        "canonical_key": "revenue_grew_20pct",
        "name": "Revenue grew 20%",
        "description": "Revenue grew 20% in the latest quarter.",
        "category": "demand",
        "importance": "high",
        "uncertainty": "medium",
        "evidence_ids": ["rev_1"],
        "why_it_matters": "It is a print.",
    }
    assert normalize_driver(raw, ticker="AVGO", allowed_ids=allowed) is None
    kept, rejected = select_driver_universe([raw], ticker="AVGO", allowed_ids=allowed)
    assert kept == []
    assert rejected


def test_value_driver_stable_identity() -> None:
    allowed = {"rev_1"}
    first = normalize_driver(
        {
            "canonical_key": "ai_demand_durability",
            "name": "AI demand durability",
            "description": "Whether hyperscaler AI demand persists beyond the current deployment wave.",
            "category": "demand",
            "financial_link": "revenue",
            "current_state": "Demand is elevated and concentrated.",
            "importance": "high",
            "uncertainty": "high",
            "persistence": "medium",
            "why_it_matters": "Duration binds the earnings and multiple path.",
            "evidence_ids": ["rev_1"],
        },
        ticker="AVGO",
        allowed_ids=allowed,
    )
    second = normalize_driver(
        {
            "canonical_key": "ai_demand_durability",
            "name": "Will AI demand last?",
            "description": "Durability of custom-silicon demand rather than a one-quarter print.",
            "category": "demand",
            "financial_link": "revenue",
            "current_state": "Still the binding variable.",
            "importance": "high",
            "uncertainty": "high",
            "persistence": "medium",
            "why_it_matters": "It decides whether growth is structural.",
            "evidence_ids": ["rev_1"],
        },
        ticker="AVGO",
        allowed_ids=allowed,
        existing=first,
    )
    assert first is not None and second is not None
    assert first["canonical_key"] == second["canonical_key"] == "ai_demand_durability"
    assert first["driver_key"] == second["driver_key"] == make_driver_key("AVGO", "ai_demand_durability")
    assert first["driver_id"] == second["driver_id"]
    store = BrainStore()
    stored = store.upsert_driver(first)
    again = store.upsert_driver({**second, "name": "AI demand duration"})
    assert stored["driver_id"] == again["driver_id"]
    assert len(store.list_drivers("AVGO")) == 1


def test_brain_routing_uses_env_not_deepseek_default() -> None:
    settings = replace(
        Settings(),
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com/v1",
        llm_api_key="sk-deepseek",
        mechanical_model_name="GLM-5.2",
        reasoning_model_name="GLM-5.3",
        mechanical_model_api_key="sk-mech",
        reasoning_model_api_key="sk-reason",
        mechanical_model_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        reasoning_model_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        mechanical_model_provider="openai",
        reasoning_model_provider="openai",
        dashscope_api_key="",
        strong_model_api_key="",
    )
    mechanical = layer_settings(settings, role=ROLE_MECHANICAL)
    reasoning = layer_settings(settings, role=ROLE_REASONING)
    assert mechanical.llm_model == canonical_brain_model("GLM-5.2", role=ROLE_MECHANICAL)
    assert reasoning.llm_model == canonical_brain_model("GLM-5.3", role=ROLE_REASONING)
    assert mechanical.llm_model != "deepseek-chat"
    assert reasoning.llm_model != "deepseek-chat"
    assert mechanical.llm_model != reasoning.llm_model
    assert "deepseek" not in (mechanical.llm_base_url or "").lower()
    mech, reason = resolve_brain_completers(settings=settings)
    assert mech.role == ROLE_MECHANICAL
    assert reason.role == ROLE_REASONING


def test_injected_completer_is_shared_for_tests() -> None:
    fake = FakeBrainCompleter()
    mech, reason = resolve_brain_completers(fake)
    assert mech is fake
    assert reason is fake


def test_canonical_key_is_stable_across_wording() -> None:
    assert make_canonical_key({"canonical_key": "customer_concentration"}) == "customer_concentration"
    assert make_canonical_key({"name": "Customer Concentration"}) == "customer_concentration"


def test_brain_run_persists_drivers_before_claims(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    result = run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    assert result["drivers"]
    assert result["drivers"][0]["canonical_key"] == "demand_durability"
    assert result["claims"]
    assert result["claims"][0].get("related_driver_ids")
    assert result["claims"][0]["related_driver_ids"][0] == result["drivers"][0]["driver_id"]
    assert store.list_drivers("ZZZT")


def test_event_requires_exposure_before_claim() -> None:
    event = {
        "event_id": "bev_meta",
        "title": "Meta AI capex rises",
        "subject": "Meta capex",
        "entities": ["Meta"],
        "event_type": "capex",
        "materiality": "material",
    }
    exposure = infer_exposure(
        ticker="AVGO",
        state_or_event=event,
        related_entities=[{"name": "Meta", "ticker": "META"}],
        origin="related_entity",
    )
    assert exposure is not None
    assert exposure["related_only"] is True
    assert may_affect_company_claim(exposure) is False
    issuer_news = infer_exposure(
        ticker="AVGO",
        state_or_event={"title": "Broadcom custom silicon demand update", "subject": "AVGO demand"},
        origin="issuer_news",
    )
    assert may_affect_company_claim(issuer_news) is True
    assert may_affect_company_claim(None) is False


def test_related_entity_cannot_directly_prove_issuer_fact() -> None:
    evidence = {
        "source_url": "https://www.meta.com/investors/10q",
        "source_type": "official_document",
        "source": "meta.com",
        "fact": "Meta increased AI capex.",
        "raw_reference": {"query_type": "related_entity", "entity": "Meta"},
    }
    assert related_entity_cannot_prove_issuer(
        evidence,
        ticker="AVGO",
        related_entities=[{"name": "Meta", "domain": "meta.com"}],
    )
    issuer = {
        "source_url": "https://www.sec.gov/Archives/avgo-10q",
        "source": "sec.gov",
        "source_type": "sec_filing",
        "fact": "Broadcom reported semiconductor revenue.",
    }
    assert related_entity_cannot_prove_issuer(issuer, ticker="AVGO") is False


def test_sec_source_is_not_automatically_material() -> None:
    row = {
        "source_url": "https://www.sec.gov/Archives/apple-8k",
        "source_type": "sec_filing",
        "source": "sec.gov",
        "fact": "Apple furnished an 8-K cover page with no operating update.",
        "title": "Form 8-K",
    }
    classified = classify_information(row, ticker="AAPL")
    assert classified["source_quality"] == "issuer_primary"
    assert classified["layer"] in {"context", "noise"}


def test_state_identity_is_stable() -> None:
    first = normalize_state(
        {"name": "Hyperscaler AI capex accelerating", "state_type": "industry", "statement": "Capex is accelerating.", "evidence_ids": ["rev_1"]},
        ticker="AVGO",
        allowed_ids={"rev_1"},
    )
    second = normalize_state(
        {"name": "Hyperscaler AI capex accelerating", "state_type": "industry", "statement": "Still accelerating.", "evidence_ids": ["rev_1"]},
        ticker="AVGO",
        allowed_ids={"rev_1"},
        existing=first,
    )
    assert first and second
    assert first["state_key"] == second["state_key"] == make_state_key("AVGO", "industry", "Hyperscaler AI capex accelerating")
    assert first["state_id"] == second["state_id"]


def test_duplicate_event_fingerprint() -> None:
    raw = {"title": "Demand update", "published_at": "2026-09-16", "url": "https://www.reuters.com/test-demand", "layer": "material"}
    first = build_event(raw, ticker="ZZZT")
    second = build_event(raw, ticker="ZZZT", existing=[first])
    assert first and first["duplicate"] is False
    assert second and second["duplicate"] is True


def test_unsupported_transmission_cannot_leap() -> None:
    allowed = {"rev_1"}
    leap = validate_transmission(
        {
            "direction": "up",
            "transmission_chain": [
                {"layer": "event", "statement": "Meta capex rose", "evidence_ids": ["rev_1"]},
                {"layer": "claim", "statement": "AVGO revenue rises", "evidence_ids": ["rev_1"]},
            ],
            "affected_claims": ["bclm_1"],
        },
        allowed_ids=allowed,
        exposure={"can_affect_claim": True},
    )
    assert leap["truncated"] is True
    assert leap["reason"] == "unsupported_leap"
    assert leap["affected_claims"] == []
    missing = validate_transmission(
        {
            "transmission_chain": [
                {"layer": "event", "statement": "Capex news", "evidence_ids": ["rev_1"]},
                {"layer": "state", "statement": "Industry capex up", "evidence_ids": []},
            ]
        },
        allowed_ids=allowed,
        exposure={"can_affect_claim": True},
    )
    assert missing["reason"] == "unsupported_transmission_step"
    bare = validate_transmission({"direction": "bullish"}, allowed_ids=allowed)
    assert bare["valid"] is False
    blocked = validate_transmission(
        {
            "transmission_chain": [
                {"layer": "event", "statement": "Meta capex", "evidence_ids": ["rev_1"]},
                {"layer": "state", "statement": "AI capex accelerating", "evidence_ids": ["rev_1"]},
                {"layer": "exposure", "statement": "Unknown AVGO share", "evidence_ids": ["rev_1"]},
                {"layer": "claim", "statement": "AVGO bullish", "evidence_ids": ["rev_1"]},
            ],
            "affected_claims": ["bclm_1"],
            "affected_drivers": ["bdrv_1"],
        },
        allowed_ids=allowed,
        exposure={"can_affect_claim": False, "related_only": True},
    )
    assert blocked["affected_claims"] == []
    assert blocked["scenario_only"] is True


def test_one_event_defaults_to_scenario_only() -> None:
    evidence = [{"id": "rev_news", "fact": "A reporter said demand was strong", "source_url": "https://www.reuters.com/a", "source_type": "web_search"}]
    decision = qualifies_for_base(
        ticker="AVGO",
        event={"title": "Demand chatter"},
        transmission={"base_case_change": True, "scenario_only": False},
        evidence_rows=evidence,
    )
    assert decision["scenario_only"] is True
    assert decision["base_update_allowed"] is False
    applied = apply_scenario_policy({"base_case_change": True, "scenario_only": False}, decision)
    assert applied["scenario_only"] is True
    assert applied["base_case_change"] is False


def test_persistent_evidence_can_update_base() -> None:
    evidence = [
        {"id": "rev_10q", "fact": "Management guidance reported continued AI semiconductor demand", "source_url": "https://www.sec.gov/avgo-10q", "source": "sec.gov", "source_type": "sec_filing"},
        {"id": "rev_2", "fact": "Reported results followed through on prior guidance", "source_url": "https://www.reuters.com/avgo-results", "source_type": "web_search"},
    ]
    decision = qualifies_for_base(
        ticker="AVGO",
        event={"title": "Guidance and reported results"},
        transmission={"base_case_change": True},
        evidence_rows=evidence,
    )
    assert decision["persistence_confirmed"] is True
    assert decision["base_update_allowed"] is True
    applied = apply_scenario_policy({"base_case_change": True}, decision)
    assert applied["base_case_change"] is True
    assert applied["scenario_only"] is False


def test_financial_impact_direction_without_magnitude() -> None:
    item = normalize_financial_impact(
        {"metric": "revenue", "direction": "up", "magnitude_range": {"low": 0.1, "high": 0.2}, "evidence_ids": []},
        allowed_ids={"rev_1"},
        object_type="driver",
        object_id="bdrv_1",
    )
    assert item is not None
    assert item["direction"] == "up"
    assert item["magnitude_range"] is None
    assert item["direction_only"] is True
    grounded = normalize_financial_impact(
        {"metric": "gross_margin", "direction": "up", "magnitude_range": "100-200bps", "evidence_ids": ["rev_1"]},
        allowed_ids={"rev_1"},
        object_type="driver",
        object_id="bdrv_1",
    )
    assert grounded["direction_only"] is False
    assert grounded["magnitude_range"] == "100-200bps"


def test_critic_blocks_unsupported_base_change() -> None:
    result = reconcile_critic(
        [
            {
                "issue_type": "wrong_base_case_update",
                "severity": "high",
                "affected_object": "event:bev_1",
                "reasoning": "A single news item is not persistent operating evidence.",
                "required_fix": "Keep scenario_only.",
            }
        ],
        transmissions=[{"event_id": "bev_1", "base_case_change": True, "scenario_only": False, "affected_claims": ["bclm_1"]}],
    )
    assert result["transmissions"][0]["base_case_change"] is False
    assert result["transmissions"][0]["scenario_only"] is True
    assert result["issues"][0]["resolved"] is True
    high = reconcile_critic(
        [
            {
                "issue_type": "unsupported_leap",
                "severity": "high",
                "affected_object": "claim:bclm_1",
                "reasoning": "Event jumped to claim without exposure evidence.",
                "required_fix": "Truncate chain.",
            }
        ],
        transmissions=[{"event_id": "bev_1", "affected_claims": ["bclm_1"], "truncated": False}],
    )
    assert high["inconsistent"] is True
    assert high["status"] == "inconsistent"
    assert high["transmissions"][0]["affected_claims"] == []



