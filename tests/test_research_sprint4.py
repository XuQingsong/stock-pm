from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.research.errors import ResearchPermissionError
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pm_judge import adjudicate_assumption, record_pm_judgment, thesis_diff
from stock_pm.research.quality import assess_research_quality_axes
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import ACTOR_PM, QUALITY_AXES
from stock_pm.research.valuation import build_valuation_cases, round_target
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def _pack_with_price(template_id: str = "semiconductor") -> dict:
    return {
        "template_id": template_id,
        "company_profile": {
            "legal_name": "Example Co",
            "eps_ttm": 4.0,
            "revenue_ttm": 50000000000,
            "fcf": 18000000000,
            "last_close": 100.0,
            "pe_ttm": 25.0,
            "net_margin_pct": 30.0,
            "revenue_growth_yoy_pct": 90.0,
        },
        "earnings_history": [{"report_date": "2026-03-05", "revenue": 15, "eps": 1.4}],
        "guidance_history": [{"text": "raised guidance", "source": "earnings call"}],
        "price_reaction_history": [
            {
                "report_date": "2026-03-05",
                "day_return_pct": -1.75,
                "post_1d_return_pct": -1.75,
                "volume_vs_20d_avg": 2.9,
            }
        ],
        "missing_fields": [],
    }


def test_only_pm_writes_status_thesis_and_valuation() -> None:
    svc = ResearchService(InMemoryResearchStore())
    assumption = svc.create_assumption("TEST", {"statement": "demand has visibility", "category": "demand"})
    evidence = svc.create_evidence(
        "TEST",
        {
            "evidence_type": "filing",
            "fact": "The company signed a multi-year custom AI accelerator contract",
            "source": "10-Q",
            "source_time": "2026-03-05T00:00:00+00:00",
            "retrieved_at": "2026-03-05T00:00:00+00:00",
            "source_type": "sec_filing",
        },
        actor="industry",
    )
    svc.link_assumption_evidence(
        "TEST",
        assumption_id=assumption["id"],
        evidence_id=evidence["id"],
        direction="support",
        strength="strong",
        relevance="direct",
        reason="contract is direct visibility",
    )
    with pytest.raises(ResearchPermissionError):
        svc.update_assumption_status("TEST", assumption["id"], actor="industry", status="strengthened")
    with pytest.raises(ResearchPermissionError):
        svc.create_thesis("TEST", {"core_thesis": "should fail"}, actor="quant")
    with pytest.raises(ResearchPermissionError):
        svc.create_valuation("TEST", {"bear_case": {}, "base_case": {}, "bull_case": {}}, actor="risk")
    svc.create_thesis("TEST", {"core_thesis": "observe the claim", "key_assumption_ids": [assumption["id"]]}, actor=ACTOR_PM)
    row = svc.create_valuation("TEST", {"bear_case": {}, "base_case": {"target_value": 100}, "bull_case": {}}, actor=ACTOR_PM)
    assert row["base_case"]["target_value"] == 100


def test_pm_does_not_copy_engine_strengthen_on_persistence() -> None:
    view = {
        "assumption_id": "rasm_1",
        "statement": "Recent revenue growth can persist over the next two years",
        "category": "demand",
        "proposed_status": "strengthen",
        "current_confidence": 0.62,
        "supporting_evidence": [
            {
                "id": "rev_1",
                "fact": "Latest print Jul 2026: revenue=29591000000.0, EPS=3.03",
                "link_relevance": "indirect",
                "link_strength": "weak",
            }
        ],
        "opposing_evidence": [],
        "unresolved_gaps": ["growth print needs demand and supply confirmation"],
    }
    ruling = adjudicate_assumption(view)
    assert ruling["final_status"] == "unchanged"
    assert ruling["engine_proposed_status"] == "strengthen"
    assert ruling["copied_engine"] is False
    assert "not adopted" in ruling["reasoning"] or "does not treat" in ruling["reasoning"]
    assert ruling["thesis_role"] == "monitoring"


def test_pm_strengthens_contract_execution_independently() -> None:
    view = {
        "assumption_id": "rasm_2",
        "statement": "Management can deliver the stated commitment: long-term contract for custom AI accelerators",
        "category": "execution",
        "proposed_status": "unchanged",
        "current_confidence": 0.5,
        "supporting_evidence": [
            {
                "id": "rev_2",
                "fact": "long-term contract for custom AI accelerators; recognized as revenue over 12 months",
                "link_relevance": "direct",
                "link_strength": "strong",
            }
        ],
        "opposing_evidence": [],
        "unresolved_gaps": [],
    }
    ruling = adjudicate_assumption(view)
    assert ruling["final_status"] == "strengthened"
    assert ruling["engine_proposed_status"] == "unchanged"
    assert ruling["thesis_role"] == "core"


def test_valuation_is_coarse_and_explains_multiple() -> None:
    cases = build_valuation_cases(_pack_with_price())
    base = cases["base_case"]
    assert base["target_value"] == round_target(base["target_value"])
    assert "." not in str(base["target_value"])
    assert str(base["target_display"]).startswith("~$")
    assert base["multiple_reason"]
    assert base["growth_assumptions"]["annual_rate"] < 0.90
    assert base["growth_assumptions"].get("origin") in {
        "observed",
        "derived",
        "assumption",
        "template_fallback",
        "management_guidance",
        "consensus",
        "historical_delivery",
        "evidence_derived",
        "fallback",
    }
    assert base["sensitivity"]
    assert cases["bear_case"]["target_value"] <= cases["base_case"]["target_value"] <= cases["bull_case"]["target_value"]
    energy = build_valuation_cases(_pack_with_price("energy"))
    assert energy["base_case"]["multiple"] <= 16


def test_quality_axes_and_transcript_gap() -> None:
    pack = {
        "earnings_history": [{"revenue": 1}],
        "guidance_history": [{"text": "outlook"}],
        "price_reaction_history": [{"post_1d_return_pct": -1}],
        "company_profile": {"eps_ttm": 4, "last_close": 80, "official_documents": [{"text": "10-Q"}]},
        "missing_fields": ["transcripts"],
    }
    axes = assess_research_quality_axes(pack, evidence=[{"fact": "contract"}])
    for key in QUALITY_AXES:
        assert axes[key] in {"sufficient", "partial", "insufficient"}
    assert axes["quality_for_discovery"] in {"sufficient", "partial"}


def test_thesis_append_only_and_diff() -> None:
    svc = ResearchService(InMemoryResearchStore())
    first = svc.create_thesis("TEST", {"core_thesis": "v1 text", "short_term_view": "cautious 1-3 months"}, actor=ACTOR_PM)
    second = svc.create_thesis("TEST", {"core_thesis": "v2 text", "short_term_view": "still cautious 1-3 months"}, actor=ACTOR_PM)
    assert first["version"] == 1
    assert second["version"] == 2
    assert svc.store.get_thesis(first["id"])["core_thesis"] == "v1 text"
    diff = thesis_diff(first, second, current_rulings=[], previous_rulings=[])
    assert diff["thesis_change"] == "core thesis text changed"
    assert len(svc.store.list_theses("TEST")) == 2


def test_sprint4_same_path_writes_horizons_and_invalidation() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24, adjudicate=True)
        snapshot = result["snapshot"]
        pm = result["pm_judge"]
        thesis = snapshot.get("thesis") or (pm or {}).get("thesis")
        assert pm and not pm.get("skipped")
        assert thesis
        assert thesis["actor"] == ACTOR_PM
        assert thesis["version"] >= 1
        assert "1–3 months" in thesis["short_term_view"] or "1-3 months" in thesis["short_term_view"]
        assert "3–12 months" in thesis["mid_term_view"] or "3-12 months" in thesis["mid_term_view"]
        assert "1–3 years" in thesis["long_term_view"] or "1-3 years" in thesis["long_term_view"]
        assert thesis["invalidation_conditions"]
        assert thesis["research_quality"]
        for key in QUALITY_AXES:
            assert thesis["research_quality"][key] in {"sufficient", "partial", "insufficient"}
        with pytest.raises(ResearchPermissionError):
            svc.create_thesis(ticker, {"core_thesis": "agent write"}, actor="industry")
        blob = json.dumps(thesis["core_thesis"], ensure_ascii=False).lower()
        assert "overweight" not in blob
        assert "price target" not in blob
        assert result["workflow_run"]["status"] in {"success", "partial"}


def test_record_pm_judgment_versions_and_valuation() -> None:
    svc = service_with_fixture("AVGO", "avgo.json")
    run_new_ticker_research(svc, "AVGO", max_depth=3, max_tasks=24, adjudicate=False)
    first = record_pm_judgment(svc, "AVGO")
    assert first["thesis"]["version"] == 1
    assert first["valuation"]["bear_case"]
    assert first["valuation"]["base_case"]
    assert first["valuation"]["bull_case"]
    second = record_pm_judgment(svc, "AVGO")
    assert second["thesis"]["version"] == 2
    assert svc.store.get_thesis(first["thesis"]["id"])["core_thesis"] == first["thesis"]["core_thesis"]
    assert second["thesis_diff"]["what_changed"]
    assert first["market_reaction"]["summary"]
    for key in QUALITY_AXES:
        assert first["research_quality"][key] in {"sufficient", "partial", "insufficient"}
