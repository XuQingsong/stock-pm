from datetime import datetime, timezone

import pytest

from stock_pm.research.errors import CrossTickerError, ProvenanceError, ResearchPermissionError
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.types import ACTOR_PM


STAMP = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).isoformat()


def service() -> ResearchService:
    return ResearchService(InMemoryResearchStore())


def test_new_ticker_gets_issuer_profile_without_invented_cik() -> None:
    svc = service()
    row = svc.ensure_issuer("COHR", legal_name="Coherent Corp", sector="半导体", source="test")
    assert row["ticker"] == "COHR"
    assert row["cik"] is None
    assert "cik" in row["missing_fields"]
    pack = svc.get_pack("COHR")
    assert pack["template_id"] == "semiconductor"
    assert pack["missing_fields"]


def test_evidence_requires_source_and_time() -> None:
    svc = service()
    with pytest.raises(ProvenanceError):
        svc.create_evidence("ZZZZ", {"evidence_type": "news", "fact": "x", "source": "wsj"})


def test_assumption_starts_unverified_and_cannot_be_core_without_pm() -> None:
    svc = service()
    row = svc.create_assumption(
        "ZZZZ",
        {"statement": "demand holds", "status": "strengthened", "thesis_role": "supporting"},
        actor="fundamental",
    )
    assert row["status"] == "unverified"
    with pytest.raises(ResearchPermissionError):
        svc.create_assumption("ZZZZ", {"statement": "core claim", "thesis_role": "core"}, actor="fundamental")


def test_assumption_evidence_links_are_many_to_many_same_ticker() -> None:
    svc = service()
    evidence = svc.create_evidence(
        "ZZZZ",
        {
            "evidence_type": "fundamental",
            "fact": "revenue grew",
            "source": "10-Q",
            "source_time": STAMP,
            "retrieved_at": STAMP,
        },
    )
    first = svc.create_assumption("ZZZZ", {"statement": "growth continues"})
    second = svc.create_assumption("ZZZZ", {"statement": "guidance is credible"})
    svc.link_assumption_evidence("ZZZZ", assumption_id=first["id"], evidence_id=evidence["id"], direction="support")
    svc.link_assumption_evidence("ZZZZ", assumption_id=second["id"], evidence_id=evidence["id"], direction="support")
    other = svc.create_evidence(
        "AAAA",
        {
            "evidence_type": "news",
            "fact": "other co",
            "source": "wsj",
            "source_time": STAMP,
            "retrieved_at": STAMP,
        },
    )
    with pytest.raises(CrossTickerError):
        svc.link_assumption_evidence("ZZZZ", assumption_id=first["id"], evidence_id=other["id"], direction="support")
    links = svc.store.list_links(evidence_id=evidence["id"])
    assert len(links) == 2


def test_only_pm_can_change_status_and_write_thesis_versions() -> None:
    svc = service()
    evidence = svc.create_evidence(
        "ZZZZ",
        {
            "evidence_type": "transcript",
            "fact": "management restated long-term demand",
            "source": "earnings call",
            "source_time": STAMP,
            "retrieved_at": STAMP,
        },
    )
    assumption = svc.create_assumption("ZZZZ", {"statement": "long-term demand holds", "importance": "high"})
    with pytest.raises(ResearchPermissionError):
        svc.update_assumption_status("ZZZZ", assumption["id"], actor="risk", status="strengthened")
    with pytest.raises(ProvenanceError):
        svc.update_assumption_status("ZZZZ", assumption["id"], actor=ACTOR_PM, status="strengthened")
    svc.link_assumption_evidence("ZZZZ", assumption_id=assumption["id"], evidence_id=evidence["id"], direction="support")
    updated = svc.update_assumption_status(
        "ZZZZ",
        assumption["id"],
        actor=ACTOR_PM,
        status="strengthened",
        thesis_role="core",
        importance="critical",
    )
    assert updated["status"] == "strengthened"
    assert updated["thesis_role"] == "core"
    with pytest.raises(ResearchPermissionError):
        svc.create_thesis("ZZZZ", {"core_thesis": "should fail"}, actor="fundamental")
    v1 = svc.create_thesis(
        "ZZZZ",
        {
            "core_thesis": "compounding on durable demand",
            "key_assumption_ids": [assumption["id"]],
            "short_term_view": "watch",
            "mid_term_view": "constructive",
            "long_term_view": "own",
        },
        actor=ACTOR_PM,
    )
    v2 = svc.create_thesis("ZZZZ", {"core_thesis": "same chain, tighter risk"}, actor=ACTOR_PM)
    assert v1["version"] == 1
    assert v2["version"] == 2
    assert svc.store.get_thesis(v1["id"])["core_thesis"] == "compounding on durable demand"
    history = svc.store.list_theses("ZZZZ")
    assert [row["version"] for row in history] == [1, 2]


def test_valuation_requires_three_cases_and_existing_thesis() -> None:
    svc = service()
    with pytest.raises(ProvenanceError):
        svc.create_valuation("ZZZZ", {"bear_case": {}, "base_case": {}, "bull_case": {}}, actor=ACTOR_PM)
    svc.create_thesis("ZZZZ", {"core_thesis": "own the compounder"}, actor=ACTOR_PM)
    row = svc.create_valuation(
        "ZZZZ",
        {"bear_case": {}, "base_case": {"target_value": 100}, "bull_case": {}},
        actor=ACTOR_PM,
    )
    assert row["base_case"]["target_value"] == 100
    assert row["bear_case"]["revenue"] is None
    thesis = svc.store.get_latest_thesis("ZZZZ")
    assert thesis["valuation_id"] == row["id"]


def test_mutations_write_agent_run_audit() -> None:
    svc = service()
    svc.create_task("ZZZZ", {"task_type": "discover_fundamentals", "title": "read filings"})
    runs = svc.store.list_agent_runs("ZZZZ")
    assert runs
    assert runs[0]["agent_name"] == "human_api"
    assert runs[0]["input_hash"]
