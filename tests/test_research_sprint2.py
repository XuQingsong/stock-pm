from __future__ import annotations

import json
from pathlib import Path

from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pack_builder import PackBuilder
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def test_pack_builder_marks_missing_and_does_not_invent() -> None:
    svc = ResearchService(InMemoryResearchStore())
    pack = svc.build_pack("ZZZZ")
    assert pack["ticker"] == "ZZZZ"
    assert "earnings_history" in pack["missing_fields"]
    assert "transcripts" in pack["missing_fields"]
    assert pack["earnings_history"] == []
    assert pack["company_profile"]["cik"] in (None, "")


def test_pack_builder_rebuilds_snapshot_from_source_refs() -> None:
    source = DictPackSource.from_mapping("AVGO", load_fixture("avgo.json"))
    pack = PackBuilder(source).build("AVGO")
    assert pack["template_id"] == "semiconductor"
    assert 4 <= len(pack["earnings_history"]) <= 6
    assert pack["earnings_history"][0]["revenue"] == 15000000000
    assert pack["earnings_history"][0]["revenue_estimate"] == 14200000000
    assert pack["price_reaction_history"]
    assert pack["source_refs"]["earnings_reports"]
    assert pack["company_profile"]["fcf"] == 18000000000
    assert "custom silicon" in {item["name"] for item in pack["earnings_history"][0]["segments"]}


def test_sprint2_workflow_discovers_commitments_without_ticker_branches() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("NVDA", "nvda.json"), ("COHR", "cohr.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24)
        snapshot = result["snapshot"]
        pack = snapshot["pack"]
        evidence = snapshot["evidence"]
        assumptions = snapshot["assumptions"]
        tasks = snapshot["tasks"]
        assert pack["ticker"] == ticker
        assert pack["earnings_history"]
        assert len(assumptions) >= 3
        assert evidence
        assert all(row.get("source") and row.get("source_time") for row in evidence)
        statements = " ".join(row["statement"].lower() for row in assumptions)
        facts = " ".join(row["fact"].lower() for row in evidence)
        assert "growth" in statements or "demand" in statements or "guidance" in statements
        assert "long-term" in facts or "guidance" in facts or "year-over-year" in facts
        follow_ups = [row for row in tasks if int(row.get("depth") or 0) > 0]
        assert follow_ups
        assert result["workflow_run"]["status"] in {"success", "partial"}
        findings = snapshot["findings"]
        assert findings


def test_empty_pack_does_not_fabricate_commitments() -> None:
    svc = ResearchService(InMemoryResearchStore())
    result = run_new_ticker_research(svc, "ZZZZ", max_depth=2, max_tasks=8)
    evidence = result["snapshot"]["evidence"]
    for row in evidence:
        assert row.get("source")
    assert "earnings_history" in result["pack"]["missing_fields"]
