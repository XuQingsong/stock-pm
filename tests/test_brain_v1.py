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
