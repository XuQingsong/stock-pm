from __future__ import annotations

import json
from pathlib import Path

from stock_pm.research.deep_case import (
    build_assumption_tree,
    build_causal_chain,
    build_commitment_ledger,
    build_delivery_history,
    build_revenue_bridge,
    classify_market_reaction,
    evidence_side,
    golden_answers,
    market_implied_case,
    reaction_window,
    search_queries_for,
    synthesize_deep_case,
)
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pm_judge import build_pm_judgment
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.types import VALUATION_STATUSES
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def _semi_pack() -> dict:
    return {
        "ticker": "TEST",
        "template_id": "semiconductor",
        "company_profile": {
            "legal_name": "Example Semi",
            "eps_ttm": 8.0,
            "revenue_ttm": 80000000000,
            "last_close": 320.0,
            "pe_ttm": 40.0,
            "pe_forward": 32.0,
            "revenue_growth_yoy_pct": 18.0,
            "gross_margin_pct": 70.0,
            "operating_margin_pct": 50.0,
            "net_margin_pct": 40.0,
        },
        "earnings_history": [
            {
                "fiscal_period": "2026Q3",
                "report_date": "2026-09-04",
                "revenue": 16000000000,
                "revenue_estimate": 15500000000,
                "eps": 1.80,
                "eps_estimate": 1.70,
                "earnings": 6500000000,
                "post_1d_return_pct": -4.2,
                "volume_vs_20d_avg": 1.8,
                "segments": [
                    {"name": "AI semiconductor", "revenue": 6200000000, "growth_yoy_pct": 60.0},
                    {"name": "infrastructure software", "revenue": 5800000000, "growth_yoy_pct": 22.0},
                    {"name": "networking", "revenue": 4000000000, "growth_yoy_pct": 30.0},
                ],
            },
            {
                "fiscal_period": "2026Q2",
                "report_date": "2026-06-05",
                "revenue": 15000000000,
                "revenue_estimate": 14900000000,
                "eps": 1.62,
                "eps_estimate": 1.60,
            },
            {
                "fiscal_period": "2026Q1",
                "report_date": "2026-03-06",
                "revenue": 14100000000,
                "revenue_estimate": 14500000000,
                "eps": 1.40,
                "eps_estimate": 1.48,
            },
            {
                "fiscal_period": "2025Q4",
                "report_date": "2025-12-12",
                "revenue": 13000000000,
                "revenue_estimate": 12800000000,
                "eps": 1.28,
                "eps_estimate": 1.25,
            },
        ],
        "guidance_history": [
            {
                "text": "We raised full-year revenue guidance. Over the next three years we remain committed to the AI semiconductor capacity plan.",
                "move": "raised",
                "source": "earnings call",
                "source_time": "2026-09-04",
                "fiscal_period": "2026Q3",
            }
        ],
        "price_reaction_history": [{"post_1d_return_pct": -4.2, "volume_vs_20d_avg": 1.8}],
        "missing_fields": ["fcf"],
    }


def _evidence() -> list[dict]:
    return [
        {
            "id": "rev_issuer",
            "fact": "Management said a multi-year custom accelerator contract is on track and revenue will be recognized over the next 12 months.",
            "source": "earnings call transcript",
            "source_type": "transcript",
            "source_time": "2026-09-04",
            "source_url": "https://example.test/transcript",
        },
        {
            "id": "rev_customer",
            "fact": "A customer 10-Q states capital expenditure for data-center AI deployments will increase next year and custom accelerator racks are being deployed.",
            "source": "customer 10-Q",
            "source_type": "sec_filing",
            "source_time": "2026-08-01",
            "source_url": "https://example.test/customer-10q",
            "evidence_side": "independent_customer",
        },
        {
            "id": "rev_power",
            "fact": "Official project notice: data-center power procurement remains the binding constraint on the deployment timeline.",
            "source": "utility project announcement",
            "source_type": "press_release",
            "source_time": "2026-07-15",
            "source_url": "https://example.test/power",
        },
        {
            "id": "rev_foundry",
            "fact": "Supply agreements with foundry and packaging partners cover the next two years of wafer starts.",
            "source": "10-Q",
            "source_type": "sec_filing",
            "source_time": "2026-06-15",
            "source_url": "https://example.test/10q",
        },
        {
            "id": "rev_conc",
            "fact": "The largest customer accounted for 21 percent of revenue.",
            "source": "10-K",
            "source_type": "sec_filing",
            "source_time": "2026-01-10",
            "source_url": "https://example.test/10k",
        },
    ]


def test_issuer_transcript_url_is_not_customer_confirmation() -> None:
    row = {
        "ticker": "AVGO",
        "fact": "we expect these deployments to drive our Q4 AI revenue to $21 billion",
        "source": "web_search",
        "source_type": "transcript",
        "source_url": "https://www.fool.com/earnings/call-transcripts/2026/09/09/broadcom-avgo-q3-2026-earnings-call-transcript/",
        "evidence_side": "independent_customer",
    }
    assert evidence_side(row, ticker="AVGO") == "issuer_management"


def test_issuer_and_customer_evidence_are_separate_families() -> None:
    rows = _evidence()
    assert evidence_side(rows[0]) == "issuer_management"
    assert evidence_side(rows[1]) == "independent_customer"
    assert evidence_side(rows[0]) != evidence_side(rows[1])
    rows = _evidence()
    assert evidence_side(rows[0]) == "issuer_management"
    assert evidence_side(rows[1]) == "independent_customer"
    assert evidence_side(rows[0]) != evidence_side(rows[1])


def test_commitment_ledger_tracks_promised_claims() -> None:
    ledger = build_commitment_ledger(_semi_pack(), _evidence())
    assert ledger
    row = ledger[0]
    for key in (
        "commitment",
        "date",
        "source",
        "time_horizon",
        "metric",
        "stated_value_or_range",
        "current_status",
        "supporting_evidence",
        "counter_evidence",
        "next_check",
    ):
        assert key in row
    assert any(item.get("current_status") in {"promised", "externally_noted"} for item in ledger)


def test_delivery_history_keeps_prints_not_just_a_score() -> None:
    history = build_delivery_history(_semi_pack())
    assert history["prints_scored"] >= 3
    assert history["history"]
    outcomes = {row["outcome"] for row in history["history"]}
    assert "beat" in outcomes
    assert "missed" in outcomes
    assert history["beat_rate"] is not None
    assert history["miss_rate"] is not None
    assert "note" in history


def test_revenue_bridge_uses_segment_mix_when_present() -> None:
    bridge = build_revenue_bridge(_semi_pack())
    assert bridge["mode"] == "segment_mix"
    families = {row["family"] for row in bridge["lines"]}
    assert "growth_end_market" in families
    assert "software_recurring" in families
    assert "networking" in families
    assert all(row["origin"] == "observed" for row in bridge["lines"])


def test_revenue_bridge_labels_missing_mix_as_estimated() -> None:
    pack = {"template_id": "semiconductor", "company_profile": {"revenue_ttm": 10}, "earnings_history": [{}]}
    bridge = build_revenue_bridge(pack)
    assert bridge["mode"] == "top_down_range"
    assert bridge["origin"] == "estimated"
    assert all(row["origin"] == "estimated" for row in bridge["lines"])


def test_causal_chain_names_weakest_link() -> None:
    chain = build_causal_chain(_semi_pack(), _evidence())
    assert chain["weakest_link"]
    layers = {row["layer"] for row in chain["layers"]}
    assert "customer_demand" in layers
    assert "foundry_packaging" in layers
    assert "issuer_revenue" in layers
    for row in chain["layers"]:
        assert "evidence" in row
        assert "confidence" in row
        assert "bottleneck" in row
        assert "unresolved" in row


def test_market_implied_is_a_fourth_column() -> None:
    from stock_pm.research.valuation import build_valuation_cases

    pack = _semi_pack()
    cases = build_valuation_cases(pack)
    implied = market_implied_case(pack, cases)
    assert implied["case"]["valuation_method"] == "market_implied"
    assert implied["market_doubts"]
    assert implied["case"]["target_value"] == 320.0
    columns = {
        "bear": cases["bear_case"],
        "market_implied": implied["case"],
        "base": cases["base_case"],
        "bull": cases["bull_case"],
    }
    assert list(columns.keys()) == ["bear", "market_implied", "base", "bull"]


def test_reaction_window_prefers_high_volume_selloff() -> None:
    pack = {
        "company_profile": {"revenue_growth_yoy_pct": 40.0, "pe_ttm": 38.0},
        "price_reaction_history": [
            {"fiscal_period": "later", "post_1d_return_pct": 0.3, "volume_vs_20d_avg": 0.8},
            {"fiscal_period": "print", "post_1d_return_pct": -3.1, "volume_vs_20d_avg": 2.9},
        ],
    }
    window = reaction_window(pack)
    assert window["fiscal_period"] == "print"
    classified = classify_market_reaction(pack, [{"fact": "largest customer is 21 percent of revenue"}])
    assert classified["applicable"] is True
    assert classified["confirmed"]
    assert classified["unresolved"] or classified["plausible_unconfirmed"]
    classified = classify_market_reaction(_semi_pack(), _evidence(), quant_findings=["tension is valuation"])
    assert classified["applicable"] is True
    assert "confirmed" in classified
    assert "plausible_unconfirmed" in classified
    assert "unresolved" in classified
    assert classified["confirmed"] or classified["plausible_unconfirmed"] or classified["unresolved"]


def test_assumption_tree_has_demand_execution_economics_market() -> None:
    rulings = [
        {
            "assumption_id": "a1",
            "statement": "End demand is customer-confirmed",
            "kind": "demand_visibility",
            "final_status": "unchanged",
            "final_confidence": 0.5,
            "thesis_role": "core",
        },
        {
            "assumption_id": "a2",
            "statement": "Contracts convert on schedule",
            "kind": "execution",
            "final_status": "strengthened",
            "final_confidence": 0.7,
            "thesis_role": "core",
        },
        {
            "assumption_id": "a3",
            "statement": "Margins hold as mix shifts",
            "kind": "margin",
            "final_status": "unchanged",
            "final_confidence": 0.4,
            "thesis_role": "monitoring",
        },
        {
            "assumption_id": "a4",
            "statement": "Customer concentration does not cap duration",
            "kind": "concentration",
            "final_status": "unchanged",
            "final_confidence": 0.35,
            "thesis_role": "monitoring",
            "unresolved_gaps": ["independent confirmation of duration"],
        },
    ]
    tree = build_assumption_tree(rulings)
    titles = [row["title"] for row in tree["branches"]]
    assert titles[:4] == ["Demand", "Execution", "Economics", "Market"]
    answers = golden_answers(
        pack=_semi_pack(),
        rulings=rulings,
        valuation={},
        artifacts={"market_implied": {"summary": "tape doubts duration"}, "causal_chain": {"weakest_link": "site_power"}, "delivery_history": {"summary": "mixed"}},
    )
    assert answers["core_thesis"]
    assert len(answers["top_assumptions"]) == 3
    assert answers["strongest_assumption"]["assumption_id"] == "a2"
    assert answers["fragile_assumption"]
    assert answers["market_worry"]
    assert answers["thesis_events"]["strengthen"]
    assert answers["thesis_events"]["weaken"]
    assert answers["thesis_events"]["break"]
    assert len(answers["monitor"]) == 5


def test_search_queries_are_template_generic() -> None:
    semi = search_queries_for("ZZZZ", {"template_id": "semiconductor"}, ["customer_confirmation"])
    energy = search_queries_for("ZZZZ", {"template_id": "energy"}, ["customer_confirmation"])
    blob = " ".join(semi + energy).lower()
    assert "30gw" not in blob
    assert "broadcom" not in blob
    assert "vmware" not in blob
    assert any("customer" in item.lower() for item in semi)
    assert any("production" in item.lower() or "offtake" in item.lower() for item in energy)


def test_synthesize_deep_case_pack() -> None:
    from stock_pm.research.valuation import build_valuation_cases

    pack = _semi_pack()
    cases = build_valuation_cases(pack)
    deep = synthesize_deep_case(
        pack,
        evidence=_evidence(),
        rulings=[
            {
                "assumption_id": "a1",
                "statement": "Demand is real",
                "kind": "demand_visibility",
                "final_status": "unchanged",
                "final_confidence": 0.5,
                "thesis_role": "core",
            }
        ],
        valuation=cases,
        mapping=[],
        quant_findings=[],
        reaction={"summary": "tape sold the print", "applicable": True},
    )
    assert deep["commitment_ledger"]
    assert deep["delivery_history"]["history"]
    assert deep["customer_side_evidence"]["independent_confirmation_present"] is True
    assert deep["revenue_bridge"]["lines"]
    assert deep["causal_chain"]["weakest_link"]
    assert deep["market_implied"]["case"]
    assert deep["assumption_tree"]["branches"]
    assert deep["golden_answers"]["monitor"]
    assert list(deep["case_columns"].keys()) == ["bear", "market_implied", "base", "bull"]


def test_pm_judgment_persists_deep_case() -> None:
    brief = {
        "ticker": "TEST",
        "pack": _semi_pack(),
        "assumptions": [],
        "engine_views": [
            {
                "assumption_id": "rasm_1",
                "statement": "The company signed a multi-year custom AI accelerator contract; about 25 percent will be recognized as revenue over the next 12 months",
                "category": "execution",
                "proposed_status": "strengthen",
                "current_confidence": 0.55,
                "supporting_evidence": [
                    {
                        "id": "rev_issuer",
                        "fact": "The company signed a multi-year custom AI accelerator contract; about 25 percent will be recognized as revenue over the next 12 months",
                        "link_relevance": "direct",
                        "link_strength": "strong",
                    }
                ],
                "opposing_evidence": [],
                "unresolved_gaps": ["customer is not independently named"],
            }
        ],
        "evidence": _evidence(),
        "quant_findings": ["tension is valuation"],
        "tasks": [],
    }
    judgment = build_pm_judgment(brief)
    deep = judgment["deep_case"]
    cal = judgment["valuation"]["calibration_json"]
    assert cal["deep_case"]
    assert cal["case_columns"]["market_implied"]
    assert judgment["thesis"]["research_quality"]["golden_answers"]
    assert judgment["thesis"]["research_quality"]["management_delivery"]["history"]
    assert judgment["market_reaction"]["confirmed"] or judgment["market_reaction"]["unresolved"]
    blob = json.dumps(judgment, default=str).lower()
    assert "if ticker" not in blob
    assert "30gw" not in blob


def test_sprint5_same_path_avgo_cohr_xom() -> None:
    for ticker, fixture in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, fixture)
        result = run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24, adjudicate=True)
        pm = result["pm_judge"]
        valuation = pm["valuation"]
        status = valuation.get("valuation_status") or (valuation.get("calibration_json") or {}).get("valuation_status")
        assert status in VALUATION_STATUSES
        cal = valuation.get("calibration_json") or {}
        deep = cal.get("deep_case") or pm.get("deep_case") or {}
        assert deep.get("commitment_ledger") is not None
        assert deep.get("delivery_history")
        assert deep.get("revenue_bridge")
        assert deep.get("causal_chain", {}).get("weakest_link")
        assert deep.get("assumption_tree", {}).get("branches")
        answers = deep.get("golden_answers") or (pm["thesis"].get("research_quality") or {}).get("golden_answers")
        assert answers
        assert answers.get("core_thesis")
        assert answers.get("top_assumptions")
        assert answers.get("monitor")
        columns = cal.get("case_columns") or deep.get("case_columns") or {}
        assert "bear" in columns and "base" in columns and "bull" in columns and "market_implied" in columns
        blob = json.dumps(result, default=str).lower()
        assert "if ticker == " not in blob
        if ticker == "XOM":
            assert valuation.get("method") in {"normalized_earnings_pe", "fcf"}
            assert deep["causal_chain"]["template_id"] == "energy"
        if ticker in {"AVGO", "COHR"}:
            assert deep["causal_chain"]["template_id"] == "semiconductor"
            families = {row.get("family") for row in deep["revenue_bridge"].get("lines") or []}
            assert families
