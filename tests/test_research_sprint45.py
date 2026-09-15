from __future__ import annotations

import json
from pathlib import Path

from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pm_judge import record_pm_judgment, thesis_diff
from stock_pm.research.quality import assess_research_quality_axes
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import VALUATION_STATUSES
from stock_pm.research.valuation import (
    attribute_target_change,
    build_valuation_cases,
    map_assumption_to_driver,
)
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def _rich_pack(template_id: str = "semiconductor") -> dict:
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
            "operating_margin_pct": 38.0,
            "revenue_growth_yoy_pct": 90.0,
        },
        "earnings_history": [
            {
                "report_date": "2026-03-05",
                "revenue": 15000000000,
                "eps": 1.4,
                "earnings": 4500000000,
                "margin_pct": 30.0,
                "segments": [
                    {"name": "custom silicon", "revenue": 6200000000, "growth_yoy_pct": 78.0},
                    {"name": "networking", "revenue": 4100000000, "growth_yoy_pct": 18.0},
                ],
            },
            {"report_date": "2025-12-10", "revenue": 14100000000, "eps": 1.31, "earnings": 4100000000},
            {"report_date": "2025-09-08", "revenue": 13000000000, "eps": 1.18, "earnings": 3700000000},
            {"report_date": "2025-06-08", "revenue": 12100000000, "eps": 1.05, "earnings": 3300000000},
            {"report_date": "2025-03-07", "revenue": 10500000000, "eps": 0.90, "earnings": 2800000000},
        ],
        "guidance_history": [{"text": "raised full-year revenue guidance", "source": "earnings call"}],
        "price_reaction_history": [{"post_1d_return_pct": -1.75, "volume_vs_20d_avg": 2.9}],
        "missing_fields": [],
    }


def test_growth_is_not_the_template_cap() -> None:
    cases = build_valuation_cases(_rich_pack())
    base_g = cases["base_case"]["growth_assumptions"]["annual_rate"]
    assert base_g != 0.25
    assert base_g < 0.90
    assert cases["base_case"]["growth_assumptions"]["origin"] != "template_fallback" or cases["valuation_status"] != "usable"
    warnings = cases["base_case"]["growth_assumptions"].get("warnings") or []
    assert any("warning threshold" in item or "not used as the 2y" in item for item in warnings) or base_g < 0.90


def test_bear_base_bull_change_business_assumptions() -> None:
    assumptions = [
        {
            "id": "rasm_c",
            "statement": "Management can deliver the stated commitment: long-term contract for custom AI accelerators",
            "status": "strengthened",
            "category": "execution",
        },
        {
            "id": "rasm_p",
            "statement": "Recent revenue growth can persist over the next two years",
            "status": "unchanged",
            "category": "demand",
        },
    ]
    cases = build_valuation_cases(_rich_pack(), assumptions=assumptions)
    bear = cases["bear_case"]
    base = cases["base_case"]
    bull = cases["bull_case"]
    assert bear["growth_assumptions"]["annual_rate"] != base["growth_assumptions"]["annual_rate"]
    assert bull["growth_assumptions"]["annual_rate"] != base["growth_assumptions"]["annual_rate"]
    assert bear["margin_assumptions"]["net_margin_pct"] <= base["margin_assumptions"]["net_margin_pct"] <= bull["margin_assumptions"]["net_margin_pct"]
    assert bear["multiple"] < base["multiple"] < bull["multiple"]
    assert bear["revenue"] != base["revenue"] != bull["revenue"] or bear["eps"] != bull["eps"]
    assert "demand slows" in bear["case_narrative"] or "slips" in bear["case_narrative"]
    assert "converts" in base["case_narrative"] or "delivered" in base["case_narrative"]
    assert bear["target_value"] <= base["target_value"] <= bull["target_value"]


def test_assumption_maps_to_valuation_driver() -> None:
    row = {
        "id": "rasm_x",
        "statement": "long-term contract for custom AI accelerators entered this quarter",
        "status": "strengthened",
        "category": "execution",
    }
    mapped = map_assumption_to_driver(row, "semiconductor")
    assert mapped["driver"] == "contract_conversion"
    cases = build_valuation_cases(_rich_pack(), assumptions=[row])
    drivers = {item["assumption_id"]: item["driver"] for item in cases["driver_map"]}
    assert drivers["rasm_x"] == "contract_conversion"
    assert cases["base_case"]["eps_derivation"]
    assert cases["earnings_bridge"]["baseline"]["revenue_ttm"]["origin"] in {"observed", "derived", "missing"}


def test_multiple_has_anchors_and_decomposition() -> None:
    cases = build_valuation_cases(_rich_pack(), assumptions=[
        {"id": "a1", "statement": "largest customer accounted for 21 percent of revenue", "status": "unchanged", "category": "other"},
        {"id": "a2", "statement": "long-term contract for custom AI accelerators", "status": "strengthened", "category": "execution"},
    ])
    decomp = cases["base_case"]["multiple_decomposition"]
    assert decomp["starting_anchor"]["note"]
    assert "growth_premium" in decomp
    assert "why_not_cycle_floor" in decomp
    assert "why_not_cycle_ceiling" in decomp
    assert decomp["anchor_count_non_template"] >= 2
    reason = cases["base_case"]["multiple_reason"].lower()
    assert "template semiconductor band" not in reason or "not automatically" in reason
    assert "not" in reason


def test_quality_for_valuation_drops_without_drivers() -> None:
    pack = {
        "template_id": "semiconductor",
        "earnings_history": [{"revenue": 1, "eps": 0.2}],
        "company_profile": {"eps_ttm": 4, "last_close": 80, "pe_ttm": 20},
        "missing_fields": ["segment_growth", "fcf", "transcripts"],
    }
    axes = assess_research_quality_axes(pack, evidence=[{"fact": "print"}])
    assert axes["quality_for_valuation"] in {"partial", "insufficient"}
    assert axes["quality_for_valuation"] != "sufficient"


def test_cohr_like_spot_above_bull_is_explained() -> None:
    pack = {
        "template_id": "semiconductor",
        "company_profile": {
            "eps_ttm": 4.72,
            "last_close": 266.5,
            "pe_ttm": 56.46,
            "net_margin_pct": 8.0,
            "revenue_ttm": 5800000000,
        },
        "earnings_history": [{"revenue": 1520000000, "eps": 0.31, "margin_pct": 8.0}],
        "guidance_history": [{"text": "raised guidance", "move": "raised"}],
        "missing_fields": ["segment_growth", "fcf"],
    }
    assumptions = [
        {"id": "g", "statement": "Management can deliver the latest raised guidance", "status": "weakened", "category": "guidance_delivery"},
        {"id": "d", "statement": "acceleration in customer demand", "status": "weakened", "category": "demand"},
    ]
    cases = build_valuation_cases(pack, assumptions=assumptions)
    assert cases["valuation_status"] in VALUATION_STATUSES
    assert cases["valuation_status"] in {"provisional", "insufficient"}
    assert cases["valuation_confidence"] < 0.55
    market = cases["market_vs_model"]
    bull = cases["bull_case"]["target_value"]
    if bull is not None and bull < 266.5:
        assert market["spot_above_bull"] is True
        assert market["explanations"]
    axes = assess_research_quality_axes(pack, assumptions=assumptions, valuation=cases)
    assert axes["quality_for_valuation"] != "sufficient"


def test_energy_uses_normalized_earnings_not_pe_band_cagr() -> None:
    pack = {
        "template_id": "energy",
        "company_profile": {
            "eps_ttm": 7.8,
            "revenue_ttm": 340000000000,
            "fcf": 30000000000,
            "last_close": 110.0,
            "pe_ttm": 14.1,
            "net_margin_pct": 10.0,
            "revenue_growth_yoy_pct": -4.0,
        },
        "earnings_history": [
            {"eps": 1.90, "revenue": 81000000000, "earnings": 7600000000, "margin_pct": 9.4},
            {"eps": 2.00, "revenue": 83000000000, "earnings": 8000000000},
            {"eps": 2.20, "revenue": 89000000000, "earnings": 9000000000},
            {"eps": 1.80, "revenue": 80000000000, "earnings": 7000000000},
        ],
        "guidance_history": [{"text": "oil volume guidance is unchanged while capex stays within the stated range", "move": "maintained"}],
        "missing_fields": ["commodity_price"],
    }
    assumptions = [
        {"id": "cagr", "statement": "targeting a 13% CAGR in earnings by 2030", "status": "unchanged", "category": "demand"},
    ]
    cases = build_valuation_cases(pack, assumptions=assumptions)
    assert cases["method"] in {"normalized_earnings_pe", "fcf"}
    assert cases["base_case"]["growth_assumptions"]["annual_rate"] < 0.13
    assert abs(cases["base_case"]["growth_assumptions"]["annual_rate"] - 0.08) > 0.001
    decomp = cases["base_case"]["multiple_decomposition"]
    assert "normalized" in cases["base_case"]["multiple_reason"].lower() or "cycle" in cases["base_case"]["multiple_reason"].lower()
    assert decomp["starting_anchor"]
    assert cases["valuation_status"] in {"provisional", "usable"}
    assert any(row["driver"] in {"normalized_earnings", "production_volume", "commodity_price"} for row in cases["driver_map"])


def test_target_attribution_on_version_change() -> None:
    previous = {"base_case": {"eps": 10.0, "multiple": 20.0, "revenue": 100, "target_value": 200, "margin_assumptions": {"net_margin_pct": 20}}}
    current = {"base_case": {"eps": 12.0, "multiple": 22.0, "revenue": 110, "target_value": 264, "margin_assumptions": {"net_margin_pct": 22}}}
    attr = attribute_target_change(previous, current)
    assert attr["base_target"]["from"]
    assert attr["base_target"]["to"]
    kinds = {row["from"] for row in attr["parts"]}
    assert "multiple" in kinds
    diff = thesis_diff(
        {"core_thesis": "v1", "confidence": 0.4, "key_assumption_ids": []},
        {"core_thesis": "v2", "confidence": 0.5, "key_assumption_ids": []},
        previous_valuation=previous,
        current_valuation=current,
    )
    assert diff["valuation_change"]["attribution"]


def test_sprint45_same_path_persists_status() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24, adjudicate=True)
        pm = result["pm_judge"]
        valuation = pm["valuation"]
        status = valuation.get("valuation_status") or (valuation.get("calibration_json") or {}).get("valuation_status")
        assert status in VALUATION_STATUSES
        assert valuation["bear_case"]["case_narrative"]
        assert valuation["base_case"]["multiple_decomposition"]
        blob = json.dumps(valuation["base_case"], ensure_ascii=False).lower()
        assert "overweight" not in blob
        assert "price target" not in blob
    svc = service_with_fixture("AVGO", "avgo.json")
    run_new_ticker_research(svc, "AVGO", max_depth=2, max_tasks=16, adjudicate=False)
    first = record_pm_judgment(svc, "AVGO")
    assert first["valuation"]["bear_case"]
    second = record_pm_judgment(svc, "AVGO")
    assert second["thesis"]["version"] == 2
    assert second["thesis_diff"]["valuation_change"]["attribution"] is not None
