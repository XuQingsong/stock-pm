"""Cold-Start Bootstrap. Ticker-agnostic. No LITE special case."""

from __future__ import annotations

from stock_pm.brain.bootstrap import (
    LIFECYCLE_BASELINE_READY,
    LIFECYCLE_INCREMENTAL,
    bootstrap_brain,
    brain_has_baseline,
    brain_initialized,
)
from stock_pm.brain.incremental import full_review_reason
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore

from test_brain_phase1 import FakeBrainCompleter, _pack, _seed_evidence, _service
from test_brain_runtime import RuntimeFakeCompleter, _seed_brain


def test_empty_brain_is_not_initialized() -> None:
    store = BrainStore()
    assert brain_has_baseline(store, "ZZZT") is False
    assert brain_initialized(store, "ZZZT") is False


def test_imported_research_assumption_cannot_complete_baseline() -> None:
    store = BrainStore()
    _seed_brain(store)
    for row in store.list_active_claims("AVGO"):
        if row.get("is_core"):
            store.update_claim_pointer(row["claim_id"], {"claim_key": "rasm:legacy", "is_core": True})
    assert brain_has_baseline(store, "AVGO") is False


def test_seeded_brain_is_initialized() -> None:
    store = BrainStore()
    _seed_brain(store)
    assert brain_has_baseline(store, "AVGO") is True


def test_empty_material_event_does_not_initialize_company() -> None:
    store = BrainStore()
    result = run_brain_update(
        ticker="ZZZT",
        item={
            "kind": "news",
            "title": "Customer confirmed a material order update",
            "fact": "A named customer confirmed a material order update.",
            "event_type": "customer",
            "confirmed": True,
            "fact_reliability": "direct_fact",
        },
        store=store,
        completer=RuntimeFakeCompleter(),
    )
    assert result["path"] == "needs_bootstrap"
    assert result["brain_initialized"] is False
    assert result["glm53_called"] is False
    assert store.list_drivers("ZZZT") == []
    assert store.list_active_claims("ZZZT") == []


def test_empty_non_material_still_stops_without_bootstrap() -> None:
    store = BrainStore()
    result = run_brain_update(
        ticker="ZZZT",
        item={
            "kind": "news",
            "title": "Issuer launches branded merch with no operating update",
            "fact": "Analyst recap of a product promo. No operating update.",
            "url": "https://example.com/recap/merch",
        },
        store=store,
        completer=RuntimeFakeCompleter(),
    )
    assert result["path"] == "observation_memory"
    assert result["brain_initialized"] is False


def test_empty_price_event_does_not_bootstrap() -> None:
    store = BrainStore()
    result = run_brain_update(
        ticker="ZZZT",
        item={
            "kind": "price",
            "title": "Shares move -6.2% with no new filing",
            "fact": "Shares moved -6.2% without a new operating disclosure.",
            "price_change_pct": -6.2,
            "event_type": "other",
            "fact_reliability": "signal",
        },
        store=store,
        completer=RuntimeFakeCompleter(),
    )
    assert result["path"] != "needs_bootstrap"
    assert result["path"] != "cold_start_bootstrap"
    assert result["brain_initialized"] is False
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_bootstrap_from_research_pack_not_from_event(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    event = {
        "kind": "news",
        "title": "A one-off headline that must not found the company",
        "fact": "This single headline is not the historical evidence set.",
        "confirmed": True,
        "fact_reliability": "direct_fact",
    }
    result = run_brain_update(
        ticker="ZZZT",
        item=event,
        store=store,
        research=svc,
        completer=svc.completer,
    )
    assert result["path"] == "cold_start_bootstrap"
    assert result["event_deferred"] is True
    assert result["brain_initialized"] is True
    assert result["lifecycle"] == LIFECYCLE_BASELINE_READY
    assert result["direct_llm_write"] is False
    assert store.list_states("ZZZT")
    assert store.list_drivers("ZZZT")
    assert any(row.get("is_core") for row in store.list_active_claims("ZZZT"))
    titles = " ".join(str(row.get("title") or "") for row in store.list_active_claims("ZZZT"))
    assert "one-off headline" not in titles.lower()


def test_partial_materialized_brain_completes_baseline_before_event(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    store.insert_claim({
        "ticker": "ZZZT", "claim_id": "bclm_partial", "claim_key": "partial",
        "title": "Imported research assumption", "statement": "An imported assumption.",
        "claim_type": "operating", "is_core": True,
    })
    assert brain_has_baseline(store, "ZZZT") is False
    result = run_brain_update(
        ticker="ZZZT",
        item={"kind": "news", "title": "Material customer update", "fact": "Customer demand changed."},
        store=store,
        research=svc,
        completer=svc.completer,
    )
    assert result["path"] == "cold_start_bootstrap"
    assert result["event_deferred"] is True
    assert result["brain_initialized"] is True


def test_bootstrap_once_then_incremental(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    first = bootstrap_brain(svc, "ZZZT", store=store, completer=FakeBrainCompleter(), fetch_live=False)
    assert first["bootstrap_skipped"] is False
    assert first["brain_initialized"] is True
    second = bootstrap_brain(svc, "ZZZT", store=store, completer=FakeBrainCompleter(), fetch_live=False)
    assert second["bootstrap_skipped"] is True
    assert second["lifecycle"] == LIFECYCLE_INCREMENTAL
    result = run_brain_update(
        ticker="ZZZT",
        item={
            "kind": "news",
            "title": "Customer confirmed a demand update",
            "fact": "A named customer confirmed a demand update.",
            "event_type": "customer",
            "entities": ["Customer"],
            "confirmed": True,
            "fact_reliability": "direct_fact",
        },
        store=store,
        trigger="first_run",
        completer=RuntimeFakeCompleter(),
    )
    assert result["path"] == "incremental"
    assert result["full_review"] is False
    assert result["brain_initialized"] is True
    assert result["lifecycle"] == LIFECYCLE_INCREMENTAL


def test_partial_slow_layer_allows_incremental() -> None:
    store = BrainStore()
    store.insert_state(
        {
            "ticker": "ZZZT",
            "state_id": "bst_demand",
            "state_type": "company",
            "name": "demand",
            "statement": "Demand is the live operating state.",
            "confidence": "medium",
        }
    )
    store.insert_driver(
        {
            "ticker": "ZZZT",
            "driver_id": "bdrv_demand",
            "canonical_key": "demand_durability",
            "name": "Demand durability",
            "category": "demand",
        }
    )
    assert brain_has_baseline(store, "ZZZT") is False
    result = run_brain_update(
        ticker="ZZZT",
        item={
            "kind": "news",
            "title": "Customer confirmed a demand update",
            "fact": "A named customer confirmed a demand update.",
            "event_type": "customer",
            "confirmed": True,
            "fact_reliability": "direct_fact",
        },
        store=store,
        completer=RuntimeFakeCompleter(),
    )
    assert result["path"] == "incremental"
    assert result["brain_initialized"] is False


def test_first_run_is_not_a_full_review_trigger() -> None:
    assert full_review_reason(trigger="first_run") is None
    assert full_review_reason(trigger="earnings") == "earnings"
    assert full_review_reason(event={"event_type": "guidance"}) == "guidance"
