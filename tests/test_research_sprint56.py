from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.research.consistency import audit_pm_reasoning
from stock_pm.research.errors import FixtureRejectedError
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pm_judge import record_pm_judgment, thesis_diff
from stock_pm.research.service import ResearchService
from stock_pm.research.snapshot import (
    apply_missing_spot_guard,
    classify_target_change,
    freeze_live_snapshot,
    market_comparison_for,
    source_is_fixture,
    valuation_method_version,
)
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import ACTOR_PM
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def production_like_store(ticker: str, *, revenue: float, eps: float, spot: float, sector: str, net_margin: float = 31.0) -> InMemoryResearchStore:
    store = InMemoryResearchStore()
    symbol = ticker.upper()
    store.raw_fundamentals[symbol] = {
        "captured_at": "2026-09-12T00:00:00+00:00",
        "revenue_ttm": revenue,
        "eps_ttm": eps,
        "gross_margin_pct": 63.0,
        "operating_margin_pct": 38.0,
        "net_margin_pct": net_margin,
        "source": "fundamentals_snapshots",
        "raw_data": {"diluted_shares": round(revenue * (net_margin / 100.0) / eps) if eps else None},
    }
    store.raw_bars[symbol] = [{"session_date": "2026-09-12", "close_price": spot, "close": spot}]
    store.raw_earnings[symbol] = [
        {
            "fiscal_period": "2026Q2",
            "report_date": "2026-06-05",
            "revenue_actual": revenue / 4,
            "eps_actual": eps / 4,
            "net_income_actual": revenue / 4 * (net_margin / 100.0),
            "source": "earnings_reports",
        }
    ]
    return store


def production_service(ticker: str, **kwargs) -> ResearchService:
    store = production_like_store(ticker, **kwargs)
    svc = ResearchService(store)
    svc.ensure_issuer(ticker, sector=kwargs.get("sector") or "半导体", legal_name=f"{ticker} Inc")
    return svc


def test_fixture_source_is_marked() -> None:
    source = DictPackSource.from_mapping("ZZZT", load_fixture("avgo.json"))
    assert source_is_fixture(source) is True
    svc = ResearchService(InMemoryResearchStore(), pack_source=source)
    pack = svc.build_pack("ZZZT")
    assert pack["is_fixture"] is True
    assert pack["source"] == "fixture"


def test_production_env_rejects_fixture_pack(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    source = DictPackSource.from_mapping("AVGO", load_fixture("avgo.json"))
    svc = ResearchService(InMemoryResearchStore(), pack_source=source)
    with pytest.raises(FixtureRejectedError):
        svc.build_pack("AVGO")


def test_fixture_cannot_overwrite_production_pack() -> None:
    svc = production_service("AVGO", revenue=87_000_000_000, eps=8.57, spot=345.0, sector="半导体")
    pack = svc.build_pack("AVGO")
    assert pack["is_fixture"] is False
    assert pack["company_profile"]["revenue_ttm"] == 87_000_000_000
    fixture = ResearchService(svc.store, pack_source=DictPackSource.from_mapping("AVGO", load_fixture("avgo.json")))
    with pytest.raises(FixtureRejectedError):
        fixture.build_pack("AVGO")
    still = svc.get_pack("AVGO")
    assert still["company_profile"]["revenue_ttm"] == 87_000_000_000
    assert still["is_fixture"] is False


def test_production_snapshot_excludes_fixture_rows() -> None:
    svc = production_service("AVGO", revenue=87_000_000_000, eps=8.57, spot=345.0, sector="半导体")
    svc.build_pack("AVGO")
    prod = svc.freeze_research_snapshot("AVGO")
    assert prod["is_fixture"] is False
    assert prod["snapshot_status"] == "valid"
    fixture_store = InMemoryResearchStore()
    fixture_svc = ResearchService(fixture_store, pack_source=DictPackSource.from_mapping("ZZZT", load_fixture("avgo.json")))
    fixture_svc.build_pack("ZZZT")
    frozen = fixture_svc.freeze_research_snapshot("ZZZT")
    assert frozen["is_fixture"] is True
    latest = fixture_svc.store.get_latest_snapshot("ZZZT", include_fixture=False)
    assert latest is None
    included = fixture_svc.store.get_latest_snapshot("ZZZT", include_fixture=True)
    assert included["snapshot_id"] == frozen["snapshot_id"]


def test_pm_valuation_and_reasoning_share_snapshot_id() -> None:
    svc = production_service("AVGO", revenue=87_000_000_000, eps=8.57, spot=345.0, sector="半导体")
    result = run_new_ticker_research(svc, "AVGO", max_depth=3, max_tasks=16, adjudicate=True)
    pm = result["pm_judge"]
    assert pm and not pm.get("skipped")
    snapshot_id = pm["snapshot_id"]
    assert snapshot_id
    assert pm["valuation"]["snapshot_id"] == snapshot_id
    assert pm["thesis"]["snapshot_id"] == snapshot_id
    assert (pm.get("pm_reasoning") or {}).get("snapshot_id") == snapshot_id or (
        (pm.get("thesis") or {}).get("snapshot_id") == snapshot_id
        and pm["valuation"]["snapshot_id"] == snapshot_id
    )
    assert pm["snapshot_manifest"]["snapshot_id"] == snapshot_id
    assert pm["snapshot_manifest"]["pack"]["revenue_ttm"] == 87_000_000_000
    assert pm["snapshot_manifest"]["market"]["spot"] == 345.0
    pack = pm["snapshot"]["pack"]
    assert pack["company_profile"]["revenue_ttm"] == 87_000_000_000
    assert pack["company_profile"]["eps_ttm"] == 8.57
    assert pack["company_profile"]["last_close"] == 345.0
    assert pm["valuation"]["spot_price"] == 345.0
    assert pm["valuation"]["valuation_method_version"]
    assert result["snapshot"]["snapshot_id"] == snapshot_id


def test_cohr_and_xom_production_snapshots_are_not_fixtures() -> None:
    cases = (
        ("COHR", 5_800_000_000, 1.1, 92.0, "半导体", 8.0),
        ("XOM", 340_000_000_000, 7.8, 118.0, "能源", 10.0),
    )
    for ticker, revenue, eps, spot, sector, margin in cases:
        svc = production_service(ticker, revenue=revenue, eps=eps, spot=spot, sector=sector, net_margin=margin)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=16, adjudicate=True)
        pm = result["pm_judge"]
        assert pm and not pm.get("skipped"), ticker
        assert pm["snapshot"]["is_fixture"] is False
        assert pm["valuation"]["snapshot_id"] == pm["snapshot_id"]
        assert pm["thesis"]["snapshot_id"] == pm["snapshot_id"]
        assert pm["snapshot"]["pack"]["company_profile"]["last_close"] == spot
        assert pm["snapshot"]["pack"]["company_profile"]["revenue_ttm"] == revenue


def test_missing_spot_forbids_market_disagreement() -> None:
    reasoning = {
        "market_disagreement": [
            {
                "pm_believes": "duration unproven",
                "market_appears_to_price": "implied growth below PM Base",
            }
        ],
        "golden_answers": {"market_disagreement": ["spot vs base"]},
    }
    apply_missing_spot_guard(reasoning, spot=None)
    assert reasoning["market_comparison_status"] == "unavailable"
    assert reasoning["market_comparison_reason"] == "spot_price_missing"
    assert reasoning["market_disagreement"] == []
    audit = audit_pm_reasoning(
        {"market_disagreement": [], "top_thesis_changing_evidence": []},
        evidence=[],
        valuation={"spot_price": None, "bull_case": {"target_value": 260}},
    )
    assert audit["market_comparison_status"] == "unavailable"
    assert audit["verdict"] == "PASS"


def test_snapshot_diff_splits_data_and_method_change() -> None:
    previous = {
        "snapshot_id": "rsnap_old",
        "valuation_method_version": "eps-runway-trailing-pe-v1",
        "spot_price": 345,
        "base_case": {"target_value": 530, "eps": 13.4, "multiple": 40, "revenue": 87_000_000_000},
        "calibration_json": {"eps_method": "eps_runway", "snapshot_id": "rsnap_old"},
    }
    current = {
        "snapshot_id": "rsnap_new",
        "valuation_method_version": "sprint46-complete-bridge-v1",
        "spot_price": None,
        "base_case": {"target_value": 165, "eps": 6.5, "multiple": 25, "revenue": 51_000_000_000},
        "calibration_json": {"eps_method": "complete_bridge", "snapshot_id": "rsnap_new"},
    }
    classified = classify_target_change(previous, current)
    assert classified["snapshot_changed"] is True
    assert classified["methodology_change"] is True
    assert "data refresh" in classified["target_change_due_to"]
    assert "methodology change" in classified["target_change_due_to"]
    diff = thesis_diff(
        {"core_thesis": "old", "snapshot_id": "rsnap_old"},
        {"core_thesis": "new", "snapshot_id": "rsnap_new"},
        previous_valuation=previous,
        current_valuation=current,
    )
    assert diff["what_changed"] == "DATA SNAPSHOT CHANGED"
    assert diff["methodology_change"] is True
    assert "DATA SNAPSHOT CHANGED" in (diff["valuation_change"] or {}).get("reason", "")


def test_complete_bridge_has_method_version() -> None:
    assert valuation_method_version({"eps_method": "complete_bridge"}) == "sprint46-complete-bridge-v1"
    assert valuation_method_version({"eps_method": "eps_runway"}) == "eps-runway-trailing-pe-v1"


def test_fixture_pm_run_still_binds_one_snapshot() -> None:
    svc = service_with_fixture("ZZZT", "avgo.json")
    result = run_new_ticker_research(svc, "ZZZT", max_depth=3, max_tasks=16, adjudicate=True)
    pm = result["pm_judge"]
    assert pm["snapshot_id"]
    assert pm["valuation"]["snapshot_id"] == pm["snapshot_id"]
    assert pm["snapshot"]["is_fixture"] is True
    assert market_comparison_for(pm["snapshot"].get("spot_price"))["market_comparison_status"] == "unavailable"
    assert (pm.get("pm_reasoning") or {}).get("market_comparison_status") in {None, "unavailable"} or (
        pm.get("market_comparison") or {}
    ).get("market_comparison_status") == "unavailable"


def test_create_valuation_reads_snapshot_spot_not_body() -> None:
    svc = production_service("TEST", revenue=10_000_000_000, eps=2.0, spot=40.0, sector="半导体", net_margin=20.0)
    svc.build_pack("TEST")
    frozen = svc.freeze_research_snapshot("TEST")
    thesis = svc.create_thesis("TEST", {"core_thesis": "observe", "snapshot_id": frozen["snapshot_id"]}, actor=ACTOR_PM)
    row = svc.create_valuation(
        "TEST",
        {
            "thesis_id": thesis["id"],
            "bear_case": {},
            "base_case": {"target_value": 50},
            "bull_case": {},
            "spot_price": 999,
            "snapshot_id": frozen["snapshot_id"],
        },
        actor=ACTOR_PM,
    )
    assert row["snapshot_id"] == frozen["snapshot_id"]
    assert row["spot_price"] == 40.0


def test_freeze_live_snapshot_marks_invalid_on_ticker_mismatch() -> None:
    frozen = freeze_live_snapshot(
        {
            "ticker": "AVGO",
            "pack": {"ticker": "XOM", "company_profile": {"last_close": 10}},
            "evidence": [{"id": "e1", "ticker": "AVGO"}],
            "assumptions": [],
        }
    )
    assert frozen["snapshot_status"] == "invalid"
    assert any("pack ticker" in item for item in frozen["invalid_reasons"])
