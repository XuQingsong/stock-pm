from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.research.agents.quant import QuantAgent, classify_tension
from stock_pm.research.agents.risk import RiskAgent
from stock_pm.research.assumptions import propose_status, summarize_assumption
from stock_pm.research.errors import ResearchPermissionError
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.schema import validate_agent_output
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import ACTOR_PM, AgentInput, AgentOutput
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def test_quant_never_emits_priced_in() -> None:
    agent = QuantAgent()
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "quant_price_in"},
            research_pack={
                "company_profile": {"revenue_growth_yoy_pct": 20.0, "eps_ttm": 4.0, "last_close": 80.0, "pe_ttm": 20.0},
                "earnings_history": [{"report_date": "2026-03-05", "revenue_surprise_pct": 5.0}],
                "price_reaction_history": [
                    {
                        "report_date": "2026-03-05",
                        "fiscal_period": "2026Q1",
                        "day_return_pct": 9.0,
                        "post_1d_return_pct": 9.0,
                        "post_5d_return_pct": 11.0,
                        "vs_spy_1d_pct": 7.0,
                        "vs_spy_5d_pct": 8.0,
                        "vs_qqq_1d_pct": 6.0,
                        "vs_sector_1d_pct": 5.0,
                    }
                ],
                "benchmark_etf": "SOXX",
                "missing_fields": [],
            },
            assumptions=[{"id": "rasm_test", "statement": "demand holds", "category": "demand"}],
        )
    )
    blob = json.dumps(output.findings + [json.dumps(item) for item in output.new_evidence], ensure_ascii=False).lower()
    assert "priced_in" not in blob
    assert "priced in" not in blob
    assert any("tension" in item.lower() for item in output.findings)
    assert classify_tension(fund_change=20, price_1d=9, vs_spy_1d=7, vs_spy_5d=8) == "price_ahead"


def test_schema_strips_priced_in_and_agent_status_writes() -> None:
    cleaned = validate_agent_output(
        AgentOutput(
            findings=["tension is aligned", "this is priced_in", "buy the dip"],
            new_assumptions=[{"statement": "growth continues", "status": "strengthened", "thesis_role": "core"}],
            proposed_assumption_changes=[
                {
                    "assumption_id": "rasm_1",
                    "proposed_status": "strengthened",
                    "reason": "support outweighs opposition",
                },
                {"assumption_id": "rasm_1", "proposed_status": "hold", "reason": "invalid"},
            ],
            confidence=0.4,
            agent_name="industry",
        ),
        agent_name="industry",
    )
    assert cleaned.findings == ["tension is aligned"]
    assert cleaned.new_assumptions[0]["status"] == "unverified"
    assert cleaned.new_assumptions[0]["thesis_role"] == "supporting"
    assert cleaned.proposed_assumption_changes[0]["proposed_status"] == "strengthen"


def test_engine_aggregates_support_oppose_and_does_not_write_status() -> None:
    assert propose_status(2.0, 0.2) == "strengthen"
    assert propose_status(0.4, 1.0) == "weaken"
    assert propose_status(0.4, 2.2) == "broken"
    assert propose_status(1.0, 1.0) == "unchanged"
    view = summarize_assumption(
        {
            "id": "rasm_1",
            "statement": "demand holds",
            "status": "unverified",
            "category": "demand",
            "importance": "high",
            "thesis_role": "supporting",
            "next_verification": "need customer confirmation",
        },
        links=[
            {"evidence_id": "rev_1", "direction": "support", "strength": "strong"},
            {"evidence_id": "rev_2", "direction": "oppose", "strength": "weak"},
            {"evidence_id": "rev_3", "direction": "contextual", "strength": "moderate"},
        ],
        evidence_by_id={
            "rev_1": {"id": "rev_1", "fact": "customers expanded forecasts", "evidence_type": "industry", "source_type": "earnings_release"},
            "rev_2": {"id": "rev_2", "fact": "largest customer is 21 percent", "evidence_type": "filing", "source_type": "sec_filing"},
            "rev_3": {"id": "rev_3", "fact": "post 1d return 4%", "evidence_type": "quant", "source_type": "structured_provider"},
        },
    )
    assert view["proposed_status"] in {"strengthen", "weaken", "unchanged", "broken"}
    assert len(view["supporting_evidence"]) == 1
    assert len(view["opposing_evidence"]) == 1
    assert len(view["contextual_evidence"]) == 1
    assert view["status"] == "unverified"
    assert view["unresolved_gaps"]


def test_persist_proposals_leave_assumption_status_unverified() -> None:
    svc = ResearchService(InMemoryResearchStore())
    assumption = svc.create_assumption("TEST", {"statement": "demand holds", "category": "demand"})
    evidence = svc.create_evidence(
        "TEST",
        {
            "evidence_type": "industry",
            "fact": "customers increased capital expenditure plans",
            "source": "8-K",
            "source_time": "2026-03-05T00:00:00+00:00",
            "retrieved_at": "2026-03-05T00:00:00+00:00",
            "source_type": "earnings_release",
        },
        actor="industry",
    )
    task = svc.create_task("TEST", {"task_type": "industry_check", "title": "industry", "assigned_agents": ["industry"]})
    agent_run = svc.store.insert_agent_run({"ticker": "TEST", "task_id": task["id"], "agent_name": "industry", "status": "running"})
    persisted = svc.persist_agent_output(
        task,
        AgentOutput(
            findings=["customer capex language present"],
            new_evidence=[],
            assumption_links=[
                {"assumption_id": assumption["id"], "evidence_id": evidence["id"], "direction": "support", "reason": "capex"}
            ],
            proposed_assumption_changes=[
                {
                    "assumption_id": assumption["id"],
                    "proposed_status": "strengthen",
                    "reason": "customer capex language supports the demand claim",
                }
            ],
            agent_name="industry",
        ),
        agent_run_id=agent_run["id"],
        max_depth=2,
    )
    assert persisted["assumption_proposals"]
    assert svc.store.get_assumption(assumption["id"])["status"] == "unverified"
    with pytest.raises(ResearchPermissionError):
        svc.update_assumption_status("TEST", assumption["id"], actor="industry", status="strengthened")
    svc.link_assumption_evidence("TEST", assumption_id=assumption["id"], evidence_id=evidence["id"], direction="support")
    updated = svc.update_assumption_status("TEST", assumption["id"], actor=ACTOR_PM, status="strengthened")
    assert updated["status"] == "strengthened"


def test_sprint3_same_workflow_for_avgo_cohr_xom() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24)
        snapshot = result["snapshot"]
        assumptions = snapshot["assumptions"]
        engine = snapshot["assumption_engine"]
        proposals = snapshot["assumption_proposals"]
        agents = {row.get("agent_name") for row in snapshot["agent_runs"]}
        assert {"fundamental", "industry", "quant", "risk"} <= agents
        assert assumptions
        assert engine
        assert proposals
        assert all(row.get("status") == "unverified" for row in assumptions)
        blob = json.dumps(snapshot["findings"], ensure_ascii=False).lower()
        assert "priced_in" not in blob
        assert "priced in" not in blob
        assert any(row.get("proposed_status") in {"strengthen", "weaken", "unchanged", "broken"} for row in engine)
        assert result["workflow_run"]["status"] in {"success", "partial"}


def test_risk_agent_seeks_counter_evidence() -> None:
    agent = RiskAgent()
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "skeptic_attack"},
            research_pack={
                "company_profile": {
                    "transcripts": [
                        {
                            "text": "The largest customer accounted for 21 percent of revenue. Execution depends on factory ramps.",
                            "source": "earnings call",
                            "source_time": "2026-03-05T21:00:00+00:00",
                        }
                    ]
                },
                "official_documents": [],
                "earnings_history": [{"report_date": "2026-03-05"}],
                "price_reaction_history": [{"post_5d_return_pct": 6.1, "report_date": "2026-03-05"}],
            },
            assumptions=[{"id": "rasm_d", "statement": "Recent revenue growth can persist", "category": "demand"}],
        )
    )
    assert output.challenged_assumption_ids or output.proposed_assumption_changes
    assert any("alternative explanation" in item.lower() or "counter" in item.lower() or "concentration" in item.lower() for item in output.findings)
    assert all(item.get("proposed_status") in {"strengthen", "weaken", "unchanged", "broken"} for item in output.proposed_assumption_changes)
