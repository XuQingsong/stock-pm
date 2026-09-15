from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.research.agents.industry import IndustryAgent
from stock_pm.research.agents.quant import QuantAgent
from stock_pm.research.agents.risk import RiskAgent
from stock_pm.research.assumptions import propose_status, summarize_assumption
from stock_pm.research.errors import ResearchPermissionError
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.relevance import independence_key_for, judge_link
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import (
    ACTOR_PM,
    NEGATIVE_MARKET_REACTION_TASK,
    AgentInput,
    AgentOutput,
)
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"
CONTRACT_FACT = (
    "The company signed a multi-year custom AI accelerator contract; "
    "about 25 percent will be recognized as revenue over the next 12 months"
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def test_same_evidence_has_different_relevance_per_assumption() -> None:
    evidence = {
        "fact": CONTRACT_FACT,
        "source_type": "sec_filing",
        "source_url": "https://example.test/10q",
        "source_time": "2026-06-30",
    }
    visibility = judge_link(evidence, {"statement": "AI demand has some visibility", "category": "demand"})
    persist = judge_link(
        evidence,
        {"statement": "Recent revenue growth can persist over the next two years", "category": "demand"},
    )
    guidance = judge_link(
        evidence,
        {"statement": "Management will deliver next-quarter guidance", "category": "guidance_delivery"},
    )
    assert visibility is not None
    assert visibility["direction"] == "support"
    assert visibility["strength"] == "strong"
    assert visibility["relevance"] == "direct"
    assert persist is not None
    assert persist["direction"] == "support"
    assert persist["relevance"] == "indirect"
    assert persist["strength"] in {"weak", "moderate"}
    assert guidance is not None
    assert guidance["direction"] == "contextual" or guidance["relevance"] in {"background", "indirect"}
    assert guidance["strength"] != "strong"


def test_engine_clusters_same_source_excerpts() -> None:
    assumption = {
        "id": "rasm_1",
        "statement": "AI demand has some visibility",
        "status": "unverified",
        "category": "demand",
        "confidence": 0.6,
    }
    url = "https://sec.example/10-q"
    facts = [
        "The company signed a multi-year custom AI accelerator contract",
        "About 25 percent of the customer contract is recognized as revenue over 12 months",
        "Customer contracts include a long-term agreement for custom accelerators",
        "The lease agreement covers compute capacity tied to the same customer contract",
        "Multi-year customer contracts remain the visibility source",
    ]
    evidence_by_id = {
        f"rev_{idx}": {
            "id": f"rev_{idx}",
            "fact": fact,
            "source_type": "sec_filing",
            "source_url": url,
            "source_time": "2026-06-09T00:00:00+00:00",
            "source": "10-Q",
        }
        for idx, fact in enumerate(facts, start=1)
    }
    links = [
        {"evidence_id": evidence_id, "direction": "support", "strength": "strong", "relevance": "direct"}
        for evidence_id in evidence_by_id
    ]
    view = summarize_assumption(assumption, links=links, evidence_by_id=evidence_by_id)
    keys = {independence_key_for(row) for row in evidence_by_id.values()}
    assert len(keys) == 1
    assert view["supporting_count"] == 1
    assert "reasoning" in view
    assert "confidence_delta" in view
    assert view["current_confidence"] == 0.6
    families = view["reasoning"]["families"]
    assert families
    assert int(families[0]["members"]) >= 5


def test_engine_does_not_count_votes() -> None:
    one_family = summarize_assumption(
        {"id": "a", "statement": "AI demand has some visibility", "category": "demand", "confidence": 0.5},
        links=[{"evidence_id": "e1", "direction": "support", "strength": "strong", "relevance": "direct"}],
        evidence_by_id={
            "e1": {
                "fact": CONTRACT_FACT,
                "source_type": "sec_filing",
                "source_url": "https://example.test/10q",
                "source_time": "2026-06-30",
            }
        },
    )
    five_copies = summarize_assumption(
        {"id": "a", "statement": "AI demand has some visibility", "category": "demand", "confidence": 0.5},
        links=[
            {"evidence_id": f"e{idx}", "direction": "support", "strength": "strong", "relevance": "direct"}
            for idx in range(5)
        ],
        evidence_by_id={
            f"e{idx}": {
                "fact": CONTRACT_FACT,
                "source_type": "sec_filing",
                "source_url": "https://example.test/10q",
                "source_time": "2026-06-30",
            }
            for idx in range(5)
        },
    )
    assert one_family["support_score"] == five_copies["support_score"]
    assert one_family["proposed_status"] == five_copies["proposed_status"]


def test_risk_without_hard_oppose_is_unchanged() -> None:
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
                "price_reaction_history": [{"post_5d_return_pct": -6.1, "report_date": "2026-03-05"}],
            },
            assumptions=[
                {"id": "rasm_d", "statement": "Customer deployment plans can be fulfilled", "category": "execution"}
            ],
        )
    )
    assert output.proposed_assumption_changes
    assert all(item["proposed_status"] == "unchanged" for item in output.proposed_assumption_changes)
    assert any("未发现足够反证" in str(item.get("reason") or "") for item in output.proposed_assumption_changes)
    assert all(item.get("direction") != "oppose" or item.get("relevance") != "direct" for item in output.assumption_links)
    assert all("post-print" not in str(item.get("reason") or "").lower() or item.get("direction") == "contextual" for item in output.assumption_links)


def test_risk_weakens_only_with_hard_oppose() -> None:
    agent = RiskAgent()
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "skeptic_attack"},
            research_pack={
                "official_documents": [
                    {
                        "text": "Management delayed deployment of the customer ramp after a supply miss and cancelled the project following power allocation shortfalls.",
                        "source": "8-K",
                        "url": "https://example.test/8k",
                        "published_at": "2026-03-05T00:00:00+00:00",
                        "source_type": "sec_filing",
                    }
                ],
                "earnings_history": [{"report_date": "2026-03-05"}],
                "price_reaction_history": [],
            },
            assumptions=[
                {"id": "rasm_e", "statement": "Customer deployment plans can be fulfilled", "category": "execution"}
            ],
        )
    )
    assert any(item["proposed_status"] in {"weaken", "broken"} for item in output.proposed_assumption_changes)
    assert any(item.get("direction") == "oppose" and item.get("relevance") == "direct" for item in output.assumption_links)


def test_quant_price_is_contextual_and_opens_reaction_task() -> None:
    agent = QuantAgent()
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "quant_price_in"},
            research_pack={
                "company_profile": {"revenue_growth_yoy_pct": 20.0, "eps_ttm": 4.0, "last_close": 80.0, "pe_ttm": 20.0},
                "earnings_history": [{"report_date": "2026-03-05", "revenue_surprise_pct": 8.0}],
                "price_reaction_history": [
                    {
                        "report_date": "2026-03-05",
                        "fiscal_period": "2026Q1",
                        "day_return_pct": -1.75,
                        "post_1d_return_pct": -1.75,
                        "post_5d_return_pct": -3.1,
                        "vs_spy_1d_pct": -2.1,
                        "volume_vs_20d_avg": 2.9,
                    }
                ],
                "benchmark_etf": "SOXX",
                "missing_fields": [],
            },
            assumptions=[
                {"id": "rasm_g", "statement": "Recent revenue growth can persist over the next two years", "category": "demand"}
            ],
        )
    )
    assert all(item.get("direction") == "contextual" for item in output.assumption_links)
    assert all(item.get("proposed_status") == "unchanged" for item in output.proposed_assumption_changes)
    titles = [getattr(item, "title", None) or item.get("title") for item in output.follow_up_tasks]
    assert NEGATIVE_MARKET_REACTION_TASK in titles
    blob = json.dumps(output.findings + [json.dumps(item) for item in output.new_evidence], ensure_ascii=False).lower()
    assert "priced_in" not in blob


def test_industry_does_not_batch_prove_every_assumption() -> None:
    agent = IndustryAgent()
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "industry_check"},
            research_pack={
                "official_documents": [
                    {
                        "text": CONTRACT_FACT + ". Supply agreements with foundry partners cover the next two years.",
                        "source": "10-Q",
                        "url": "https://example.test/10q",
                        "published_at": "2026-03-05T00:00:00+00:00",
                        "source_type": "sec_filing",
                    }
                ],
                "earnings_history": [{"report_date": "2026-03-05"}],
            },
            assumptions=[
                {"id": "a1", "statement": "AI demand has some visibility", "category": "demand"},
                {"id": "a2", "statement": "Recent revenue growth can persist over the next two years", "category": "demand"},
                {"id": "a3", "statement": "Management will deliver next-quarter guidance", "category": "guidance_delivery"},
            ],
        )
    )
    by_id = {item["assumption_id"]: item for item in output.proposed_assumption_changes}
    statuses = {item["proposed_status"] for item in output.proposed_assumption_changes}
    assert "unchanged" in statuses
    if "a2" in by_id:
        assert by_id["a2"]["proposed_status"] != "strengthen" or by_id["a1"]["proposed_status"] == "strengthen"
    links_by_assumption = {}
    for item in output.assumption_links:
        links_by_assumption.setdefault(item.get("assumption_id"), []).append(item)
    if "a1" in links_by_assumption and "a2" in links_by_assumption:
        vis = links_by_assumption["a1"][0]
        persist = links_by_assumption["a2"][0]
        assert (vis.get("relevance"), vis.get("strength")) != (persist.get("relevance"), persist.get("strength")) or vis.get("direction") != persist.get("direction")


def test_persist_does_not_batch_link_supported_ids() -> None:
    svc = ResearchService(InMemoryResearchStore())
    first = svc.create_assumption("TEST", {"statement": "AI demand has some visibility", "category": "demand"})
    second = svc.create_assumption(
        "TEST",
        {"statement": "Recent revenue growth can persist over the next two years", "category": "demand"},
    )
    task = svc.create_task("TEST", {"task_type": "industry_check", "title": "industry", "assigned_agents": ["industry"]})
    agent_run = svc.store.insert_agent_run(
        {"ticker": "TEST", "task_id": task["id"], "agent_name": "industry", "status": "running"}
    )
    svc.persist_agent_output(
        task,
        AgentOutput(
            findings=["contract language present"],
            new_evidence=[
                {
                    "evidence_type": "industry",
                    "fact": CONTRACT_FACT,
                    "source": "10-Q",
                    "source_url": "https://example.test/10q",
                    "source_time": "2026-03-05T00:00:00+00:00",
                    "source_type": "sec_filing",
                    "_key": "ind-1",
                }
            ],
            supported_assumption_ids=[first["id"], second["id"]],
            challenged_assumption_ids=[second["id"]],
            assumption_links=[
                {
                    "assumption_id": first["id"],
                    "evidence_key": "ind-1",
                    "direction": "support",
                    "strength": "strong",
                    "relevance": "direct",
                    "reason": "multi-year contract is direct demand visibility",
                }
            ],
            agent_name="industry",
        ),
        agent_run_id=agent_run["id"],
        max_depth=2,
    )
    first_links = svc.store.list_links(assumption_id=first["id"])
    second_links = svc.store.list_links(assumption_id=second["id"])
    assert first_links
    assert first_links[0]["relevance"] == "direct"
    assert not second_links


def test_engine_reasoning_and_pm_status_gate() -> None:
    assert propose_status(2.0, 0.2) == "strengthen"
    svc = ResearchService(InMemoryResearchStore())
    assumption = svc.create_assumption("TEST", {"statement": "AI demand has some visibility", "category": "demand"})
    evidence = svc.create_evidence(
        "TEST",
        {
            "evidence_type": "filing",
            "fact": CONTRACT_FACT,
            "source": "10-Q",
            "source_time": "2026-03-05T00:00:00+00:00",
            "retrieved_at": "2026-03-05T00:00:00+00:00",
            "source_type": "sec_filing",
            "source_url": "https://example.test/10q",
        },
        actor="industry",
    )
    assert evidence["source_quality"] == "primary"
    assert evidence["independence_key"]
    svc.link_assumption_evidence(
        "TEST",
        assumption_id=assumption["id"],
        evidence_id=evidence["id"],
        direction="support",
        strength="strong",
        relevance="direct",
        reason="contract is direct visibility",
    )
    from stock_pm.research.assumptions import record_engine_proposals

    views = record_engine_proposals(svc, "TEST")
    assert views[0]["reasoning"]["positives"] or views[0]["reasoning"]["limits"]
    assert "confidence_delta" in views[0]
    assert svc.store.get_assumption(assumption["id"])["status"] == "unverified"
    with pytest.raises(ResearchPermissionError):
        svc.update_assumption_status("TEST", assumption["id"], actor="industry", status="strengthened")
    updated = svc.update_assumption_status("TEST", assumption["id"], actor=ACTOR_PM, status="strengthened")
    assert updated["status"] == "strengthened"


def test_sprint35_same_path_avgo_cohr_xom_differentiates() -> None:
    engine_status_sets = []
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24)
        snapshot = result["snapshot"]
        engine = snapshot["assumption_engine"]
        agents = {row.get("agent_name") for row in snapshot["agent_runs"]}
        assert {"fundamental", "industry", "quant", "risk"} <= agents
        assert all(row.get("status") == "unverified" for row in snapshot["assumptions"])
        assert engine
        assert all("confidence_delta" in row for row in engine)
        assert all(isinstance(row.get("reasoning"), dict) for row in engine)
        blob = json.dumps(snapshot["findings"], ensure_ascii=False).lower()
        assert "priced_in" not in blob
        assert "priced in" not in blob
        engine_status_sets.append({row.get("proposed_status") for row in engine})
        risk_proposals = [
            row for row in snapshot["assumption_proposals"] if row.get("produced_by") == "risk"
        ]
        if risk_proposals:
            assert {row.get("proposed_status") for row in risk_proposals} <= {"strengthen", "weaken", "unchanged", "broken"}
        links = snapshot.get("links") or []
        if not links:
            links = svc.store.list_links(ticker=ticker)
        by_evidence: dict[str, set[str]] = {}
        for link in links:
            if link.get("direction") != "support":
                continue
            by_evidence.setdefault(str(link.get("evidence_id")), set()).add(str(link.get("assumption_id")))
        if by_evidence:
            assumption_count = len(snapshot["assumptions"])
            assert all(len(ids) < assumption_count or assumption_count <= 1 for ids in by_evidence.values())
        assert result["workflow_run"]["status"] in {"success", "partial"}
    assert any(len(statuses) > 1 for statuses in engine_status_sets) or any(
        statuses == {"unchanged"} for statuses in engine_status_sets
    )
