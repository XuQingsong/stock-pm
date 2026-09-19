"""Persist Slow Brain, history, claim evidence, and Expectation comparison."""

from __future__ import annotations

import pytest

from stock_pm.brain.expectation import coerce_expectation_comparison, compare_actual_to_expectation, normalize_expectation
from stock_pm.brain.history import meaningful_delta, record_history
from stock_pm.brain.bootstrap import bootstrap_brain, brain_has_baseline
from stock_pm.brain.pm_view import build_pm_view
from stock_pm.brain.store import BrainStore
from stock_pm.database import Database
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource

from test_brain_phase1 import FakeBrainCompleter, STAMP, _pack


def test_actual_below_expected_is_never_in_line() -> None:
    assert coerce_expectation_comparison(1.50, 1.81) == "below"
    assert compare_actual_to_expectation(1.50, 1.81) == {"comparison": "below", "trend": "falling"}
    row = normalize_expectation({"name": "Q3 GAAP EPS", "actual": 1.50, "expected": 1.81, "comparison": "in_line"}, ticker="LITE")
    assert row["comparison"] == "below"
    store = BrainStore()
    stored = store.upsert_expectation({"ticker": "LITE", "name": "Q3 GAAP EPS", "actual": 1.50, "expected": 1.81, "comparison": "in_line"})
    assert stored["comparison"] == "below"
    snap = build_pm_view(store, "LITE")
    assert snap["llm_invoked"] is False
    assert snap["market_view"]["expectations"][0]["comparison"] == "below"


def test_stale_inline_expectation_is_coerced_on_pm_view() -> None:
    store = BrainStore()
    store.expectations["bexpc_eps"] = {
        "expectation_id": "bexpc_eps",
        "ticker": "LITE",
        "name": "Q3 GAAP EPS",
        "subject": "Q3 GAAP EPS",
        "actual": 1.50,
        "expected": 1.81,
        "comparison": "in_line",
        "trend": "unchanged",
        "confidence": "medium",
        "supporting_evidence_ids": [],
        "last_material_change": "GAAP EPS 1.50 vs 1.81",
        "reason": "1.50 vs 1.81",
        "source_kind": "news",
    }
    snap = build_pm_view(store, "LITE")
    assert snap["llm_invoked"] is False
    assert snap["market_view"]["expectations"][0]["comparison"] == "below"


def test_missing_expected_is_unknown() -> None:
    assert coerce_expectation_comparison(1.50, None) == "unknown"
    row = normalize_expectation({"name": "print", "actual": 1.50, "expected": None, "comparison": "in_line"}, ticker="LITE")
    assert row["comparison"] == "unknown"


def test_timestamp_only_history_is_not_persisted() -> None:
    assert meaningful_delta({"statement": "same", "updated_at": "t1"}, {"statement": "same", "updated_at": "t2"}) is False
    store = BrainStore()
    skipped = store.insert_history(
        {
            "ticker": "AVGO",
            "object_type": "company_state",
            "object_id": "bst_x",
            "from_payload": {"statement": "same", "confidence": "medium", "updated_at": "t1"},
            "to_payload": {"statement": "same", "confidence": "medium", "updated_at": "t2"},
            "reason": "timestamp only",
        }
    )
    assert skipped is None
    assert store.list_history("AVGO") == []
    record_history(
        store,
        ticker="AVGO",
        object_type="company_state",
        object_id="bst_x",
        from_payload={"statement": "old"},
        to_payload={"statement": "new"},
        reason="real delta",
    )
    rows = store.list_history("AVGO")
    assert len(rows) == 1
    assert rows[0]["to_payload"]["statement"] == "new"


def test_claim_support_counter_and_history_are_readable() -> None:
    first = BrainStore()
    first.insert_claim({"ticker": "AVGO", "claim_id": "bclm_dur", "title": "AI duration", "statement": "Duration holds.", "status": "partially_supported", "is_core": True})
    first.upsert_evidence({"id": "rev_support", "ticker": "AVGO", "fact": "AI demand continues to be very strong.", "source": "sec.gov"})
    first.upsert_evidence({"id": "rev_counter", "ticker": "AVGO", "fact": "EPS missed consensus.", "source": "street"})
    first.insert_link({"claim_id": "bclm_dur", "evidence_id": "rev_support", "direction": "support", "strength": "strong", "reason": "Exhibit supports demand."})
    first.insert_link({"claim_id": "bclm_dur", "evidence_id": "rev_counter", "direction": "oppose", "strength": "medium", "reason": "Print missed."})
    first.insert_state({"ticker": "AVGO", "state_id": "bst_ai", "state_type": "company", "name": "AI demand", "statement": "Demand is elevated."})
    first.insert_driver({"ticker": "AVGO", "driver_id": "bdrv_ai", "canonical_key": "ai_demand", "name": "AI demand", "current_state": "Strong."})
    first.insert_history(
        {
            "ticker": "AVGO",
            "object_type": "core_claim",
            "object_id": "bclm_dur",
            "from_payload": {"status": "strongly_supported"},
            "to_payload": {"status": "partially_supported"},
            "reason": "miss challenged duration",
        }
    )
    snap = build_pm_view(first, "AVGO")
    assert snap["llm_invoked"] is False
    assert snap["core_claims"][0]["strongest_support"]["id"] == "rev_support"
    assert snap["core_claims"][0]["strongest_support"]["source"] == "sec.gov"
    assert snap["core_claims"][0]["strongest_counter"]["id"] == "rev_counter"
    assert snap["what_changed"]
    assert any(row["family"] == "Claim" for row in snap["what_changed"])


def postgres_or_skip() -> Database:
    db = Database()
    if not db.ping():
        db.close()
        pytest.skip("PostgreSQL is not reachable")
    db.initialize()
    return db


def test_claim_support_counter_and_history_survive_new_store() -> None:
    from stock_pm.research.ids import new_id

    db = postgres_or_skip()
    ticker = f"AZ{new_id('t')[-4:]}".upper()
    claim_id = new_id("bclm")
    support_id = new_id("rev")
    counter_id = new_id("rev")
    first = BrainStore(db)
    first.insert_claim({"ticker": ticker, "claim_id": claim_id, "title": "AI duration", "statement": "Duration holds.", "status": "partially_supported", "is_core": True})
    first.upsert_evidence({"id": support_id, "ticker": ticker, "fact": "AI demand continues to be very strong.", "source": "sec.gov"})
    first.upsert_evidence({"id": counter_id, "ticker": ticker, "fact": "EPS missed consensus.", "source": "street"})
    first.insert_link({"claim_id": claim_id, "evidence_id": support_id, "direction": "support", "strength": "strong", "reason": "Exhibit supports demand."})
    first.insert_link({"claim_id": claim_id, "evidence_id": counter_id, "direction": "oppose", "strength": "medium", "reason": "Print missed."})
    first.insert_history(
        {
            "ticker": ticker,
            "object_type": "core_claim",
            "object_id": claim_id,
            "from_payload": {"status": "strongly_supported"},
            "to_payload": {"status": "partially_supported"},
            "reason": "miss challenged duration",
        }
    )
    reader = BrainStore(db)
    snap = build_pm_view(reader, ticker)
    assert snap["llm_invoked"] is False
    card = next(row for row in snap["core_claims"] if row["claim_id"] == claim_id)
    assert card["strongest_support"]["id"] == support_id
    assert card["strongest_support"]["source"] == "sec.gov"
    assert card["strongest_counter"]["id"] == counter_id
    assert any(row["family"] == "Claim" and row["object_id"] == claim_id for row in snap["what_changed"])
    db.close()


def _bootstrap_service(ticker: str) -> ResearchService:
    pack = {**_pack(), "ticker": ticker}
    source = DictPackSource.from_mapping(ticker, pack)
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=FakeBrainCompleter())
    svc.store.upsert_pack(pack)
    svc.ensure_issuer(ticker, legal_name="Lumentum", sector="光通信")
    svc.create_evidence(
        ticker,
        {
            "evidence_type": "filing",
            "fact": "Management said demand remained strong in the latest quarter.",
            "excerpt": "demand remained strong",
            "source": "sec.gov",
            "source_url": "https://www.sec.gov/Archives/lite",
            "source_time": STAMP,
            "retrieved_at": STAMP,
            "source_type": "sec_filing",
        },
        actor="test",
    )
    return svc


def test_lite_bootstrap_survives_new_store_instance(monkeypatch) -> None:
    from stock_pm.research.ids import new_id

    db = postgres_or_skip()
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    ticker = f"LT{new_id('t')[-4:]}".upper()
    svc = _bootstrap_service(ticker)
    writer = BrainStore(db)
    result = bootstrap_brain(svc, ticker, store=writer, completer=FakeBrainCompleter(), fetch_live=False)
    assert result["brain_initialized"] is True
    assert brain_has_baseline(writer, ticker) is True
    claim_ids = [row["claim_id"] for row in writer.list_active_claims(ticker) if row.get("is_core")]
    assert claim_ids
    reader = BrainStore(db)
    assert brain_has_baseline(reader, ticker) is True
    snap = build_pm_view(reader, ticker, research=svc)
    assert snap["llm_invoked"] is False
    assert snap["core_claims"]
    assert snap["what_changed"]
    families = {row["family"] for row in snap["what_changed"]}
    assert {"State", "Driver", "Claim"} <= families
    support = snap["core_claims"][0].get("strongest_support")
    assert support is not None
    assert support.get("id") or support.get("fact") or support.get("reason")
    db.close()
