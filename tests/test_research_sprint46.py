from __future__ import annotations

import json
from pathlib import Path

from stock_pm.research.financials import GROWTH_ORIGINS, resolve_diluted_shares, separate_margins
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.quality import assess_research_quality_axes
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import VALUATION_STATUSES
from stock_pm.research.valuation import build_valuation_cases
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def _avgo_like_pack() -> dict:
    return {
        "template_id": "semiconductor",
        "company_profile": {
            "legal_name": "Example Semi",
            "eps_ttm": 8.57,
            "revenue_ttm": 87000000000,
            "last_close": 345.0,
            "pe_ttm": 40.22,
            "gross_margin_pct": 77.0,
            "operating_margin_pct": 53.92,
            "revenue_growth_yoy_pct": 97.2,
        },
        "earnings_history": [
            {
                "fiscal_period": "Q3",
                "revenue": 15950000000,
                "eps": 1.69,
                "earnings": 4300000000,
                "operating_margin_pct": 53.92,
                "gross_margin_pct": 77.0,
                "segments": [
                    {"name": "AI semiconductor", "revenue": 5100000000, "growth_yoy_pct": 63.0},
                    {"name": "infrastructure software", "revenue": 6700000000, "growth_yoy_pct": 26.0},
                    {"name": "non-AI semiconductor", "revenue": 4150000000, "growth_yoy_pct": 12.0},
                ],
            },
            {"revenue": 14100000000, "eps": 1.42, "earnings": 3600000000},
            {"revenue": 13000000000, "eps": 1.20, "earnings": 3100000000},
            {"revenue": 12100000000, "eps": 1.05, "earnings": 2700000000},
        ],
        "guidance_history": [{"text": "raised full-year revenue guidance", "source": "earnings call"}],
        "missing_fields": ["fcf"],
    }


def test_operating_income_is_not_used_to_imply_shares() -> None:
    pack = {
        "template_id": "semiconductor",
        "company_profile": {
            "eps_ttm": 4.0,
            "revenue_ttm": 50000000000,
            "last_close": 100.0,
            "operating_margin_pct": 40.0,
            "gross_margin_pct": 70.0,
        },
        "earnings_history": [{"revenue": 12000000000, "eps": 1.0, "operating_margin_pct": 40.0}],
        "guidance_history": [{"text": "outlook unchanged"}],
    }
    cases = build_valuation_cases(pack)
    shares = cases["earnings_bridge"]["baseline"]["diluted_shares"]
    blob = json.dumps(cases, ensure_ascii=False).lower()
    assert "implied shares" not in blob
    assert "revenue × margin / eps" not in blob
    assert "revenue × operating" not in blob
    implied_from_oi = (50000000000 * 0.40) / 4.0
    if shares.get("value") is not None:
        assert abs(float(shares["value"]) - implied_from_oi) > 1.0
        assert "operating" in str(shares.get("note") or "").lower() and "not operating" in str(shares.get("note") or "").lower() or shares.get("origin") != "derived"
    assert shares.get("origin") in {"market_cap_price", "missing", "derived_ni_eps", "earnings_release", "companyfacts", "sec_10q", "sec_10k"}
    assert cases["financial_lineage"]["net_margin"]["value"] is None or cases["financial_lineage"]["net_margin"]["origin"] != "observed"
    assert cases["base_case"]["margin_assumptions"]["net_margin_pct"] is None
    assert cases["valuation_status"] in {"provisional", "insufficient"}
    assert "operating income is not converted" in blob or cases["eps_bridge"]["operating_only"] is True or cases["eps_method"] in {"forward_eps_anchor", "eps_runway", "operating_only", "insufficient"}


def test_net_operating_gross_margins_stay_separate() -> None:
    pack = _avgo_like_pack()
    split = separate_margins(pack)
    assert split["operating_margin"]["value"] == 53.92
    assert split["gross_margin"]["value"] == 77.0
    assert split["net_margin"]["value"] is not None
    assert abs(float(split["net_margin"]["value"]) - 53.92) > 0.5
    cases = build_valuation_cases(pack)
    lineage = cases["financial_lineage"]
    assert lineage["gross_margin"]["value"] == 77.0
    assert lineage["operating_margin"]["value"] == 53.92
    net_v = lineage["net_margin"]["value"]
    assert net_v is not None
    assert abs(float(net_v) - 53.92) > 0.5
    assert abs(float(net_v) - 77.0) > 0.5
    notes = json.dumps(cases["base_case"]["margin_assumptions"], ensure_ascii=False)
    assert "52.92" not in notes


def test_base_growth_is_not_trailing_yoy_times_fade() -> None:
    pack = _avgo_like_pack()
    cases = build_valuation_cases(pack)
    base_g = cases["base_case"]["growth_assumptions"]["annual_rate"]
    faded = 0.972 * 0.40
    assert abs(base_g - faded) > 0.002
    assert abs(base_g - 0.389) > 0.002
    blob = json.dumps(cases, ensure_ascii=False).lower()
    assert "keep 40% of trailing" not in blob
    assert "0.40" not in blob or "persist unproven" not in blob
    origin = cases["base_case"]["growth_assumptions"]["origin"]
    assert origin in GROWTH_ORIGINS
    assert origin != "template_fallback" or cases["valuation_status"] != "usable"
    display = cases["base_case"]["growth_assumptions"].get("display") or ""
    assert "~" in display
    assert cases["forward_revenue_bridge"]
    assert cases["forward_revenue_bridge"].get("mode") in {"segment_mix", "top_down_range", "management_guidance", "historical_delivery"}


def test_quality_does_not_treat_operating_as_net() -> None:
    pack = {
        "template_id": "semiconductor",
        "earnings_history": [{"revenue": 10, "eps": 0.2}],
        "guidance_history": [{"text": "raised guidance"}],
        "company_profile": {
            "eps_ttm": 4,
            "last_close": 80,
            "pe_ttm": 20,
            "operating_margin_pct": 40.0,
            "gross_margin_pct": 70.0,
        },
        "missing_fields": ["segment_growth", "fcf", "net_margin"],
    }
    axes = assess_research_quality_axes(pack, evidence=[{"fact": "print"}])
    assert axes["quality_for_valuation"] != "sufficient"


def test_lineage_is_present_on_valuation() -> None:
    pack = _avgo_like_pack()
    cases = build_valuation_cases(pack)
    lineage = cases["financial_lineage"]
    for key in ("diluted_shares", "gross_margin", "operating_margin", "net_margin", "forward_growth"):
        assert key in lineage
        assert "origin" in lineage[key]
        assert "quality" in lineage[key]
    shares = resolve_diluted_shares(pack)
    assert shares["origin"] in {"derived_ni_eps", "earnings_release", "companyfacts", "sec_10q", "sec_10k", "market_cap_price"}
    assert "operating income" not in str(shares.get("note") or "").lower() or "not operating" in str(shares.get("note") or "").lower()
    assert cases["eps_bridge"]["method"]
    assert cases["valuation_status"] in VALUATION_STATUSES


def test_missing_net_and_shares_stays_provisional() -> None:
    pack = {
        "template_id": "semiconductor",
        "company_profile": {
            "eps_ttm": 2.0,
            "revenue_ttm": 10000000000,
            "last_close": 50.0,
            "operating_margin_pct": 22.0,
        },
        "earnings_history": [{"revenue": 2500000000, "eps": 0.4}],
        "guidance_history": [{"text": "maintained outlook"}],
        "missing_fields": ["segment_growth", "fcf", "net_margin", "diluted_shares"],
    }
    cases = build_valuation_cases(pack)
    assert cases["valuation_status"] in {"provisional", "insufficient"}
    assert cases["financial_lineage"]["net_margin"]["value"] is None or cases["eps_method"] != "complete_bridge"


def test_sprint46_same_path_avgo_cohr_xom() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24, adjudicate=True)
        valuation = result["pm_judge"]["valuation"]
        status = valuation.get("valuation_status") or (valuation.get("calibration_json") or {}).get("valuation_status")
        assert status in VALUATION_STATUSES
        blob = json.dumps(valuation, ensure_ascii=False).lower()
        assert "keep 40% of trailing" not in blob
        assert "implied shares" not in blob
        lineage = valuation.get("financial_lineage") or (valuation.get("calibration_json") or {}).get("financial_lineage") or {}
        assert lineage.get("diluted_shares")
        growth_origin = ((valuation.get("base_case") or {}).get("growth_assumptions") or {}).get("origin")
        assert growth_origin in GROWTH_ORIGINS
        if ticker == "XOM":
            assert valuation.get("method") in {"normalized_earnings_pe", "fcf"}
            bridge = valuation.get("forward_revenue_bridge") or {}
            assert bridge.get("mode") in {None, "normalized_earnings_fcf", "top_down_range", "historical_delivery", "management_guidance"}
            assert abs(((valuation.get("base_case") or {}).get("growth_assumptions") or {}).get("annual_rate") or 0) < 0.13
