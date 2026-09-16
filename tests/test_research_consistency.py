from __future__ import annotations

from stock_pm.research.consistency import audit_pm_reasoning, customer_proof_class, valuation_stance
from stock_pm.research.pm_judge import build_pm_judgment
from tests.test_research_sprint55 import ScriptedCompleter


def test_ungrounded_top5_is_dropped() -> None:
    reasoning = {
        "top_thesis_changing_evidence": [
            {"evidence_id": "e1", "why_it_changes_thesis": "real print"},
            {"evidence_id": "invented", "why_it_changes_thesis": "from memory"},
        ]
    }
    evidence = [{"id": "e1", "fact": "custom silicon revenue 6.2B YoY 78%", "excerpt": "custom silicon revenue 6.2B", "source": "earnings_reports", "source_time": "2026-03-05", "source_type": "earnings_release"}]
    audit = audit_pm_reasoning(reasoning, evidence=evidence, valuation={"base_case": {"target_value": 165}})
    assert [row["evidence_id"] for row in reasoning["top_thesis_changing_evidence"]] == ["e1"]
    assert reasoning["top_thesis_changing_evidence"][0]["source"] == "earnings_reports"
    assert "invented" in str(audit["evidence_grounding"]["dropped"])
    assert audit["verdict"] == "FAIL"


def test_capacity_target_removed_without_evidence() -> None:
    reasoning = {"core_thesis": "The 30 gigawatt capacity plan is the long-term driver.", "top_thesis_changing_evidence": []}
    audit_pm_reasoning(reasoning, evidence=[{"id": "e1", "fact": "revenue grew", "source": "8-K"}], valuation={})
    assert "gigawatt" not in (reasoning["core_thesis"] or "").lower()
    reasoning2 = {
        "core_thesis": "The 30 gigawatt capacity plan is the long-term driver.",
        "top_thesis_changing_evidence": [],
    }
    evidence = [
        {
            "id": "e2",
            "fact": "Long-term we are targeting custom silicon capacity of 30 gigawatts as AI accelerator demand ramps.",
            "excerpt": "targeting custom silicon capacity of 30 gigawatts",
            "source": "earnings call",
            "source_url": "https://example.test/transcript/2026q1",
            "source_time": "2026-03-05T21:00:00+00:00",
            "source_type": "transcript",
        }
    ]
    audit = audit_pm_reasoning(reasoning2, evidence=evidence, valuation={})
    assert "30 gigawatt" in reasoning2["core_thesis"].lower()
    assert audit["evidence_grounding"]["capacity_target"]["grounded"] is True
    assert audit["evidence_grounding"]["capacity_target"]["evidence_ids"] == ["e2"]


def test_customer_capex_is_not_a_contract() -> None:
    row = {
        "id": "e3",
        "fact": "Customers increased capital expenditure plans for data-center deployments.",
        "excerpt": "Customers increased capital expenditure plans for data-center deployments.",
        "source": "sec",
        "source_url": "https://example.test/ex99-1",
        "source_type": "earnings_release",
    }
    assert customer_proof_class(row) == "A"
    reasoning = {
        "top_thesis_changing_evidence": [{"evidence_id": "e3", "why_it_changes_thesis": "customer capex"}],
        "market_disagreement": [],
    }
    audit = audit_pm_reasoning(reasoning, evidence=[row], valuation={"spot_price": None, "bull_case": {"target_value": 260}})
    assert audit["customer_evidence_boundary"][0]["proof_class"] == "A"
    assert "C" in audit["customer_evidence_boundary"][0]["may_not_promote_to"]


def test_spot_above_bull_cannot_claim_below_base() -> None:
    reasoning = {
        "market_disagreement": [
            {
                "pm_believes": "duration unproven",
                "market_appears_to_price": "implied growth below PM Base",
                "why_pm_differs": "the tape is cheap vs base",
            }
        ],
        "top_thesis_changing_evidence": [],
        "competing_hypotheses": [
            {"statement": "demand is a pull-forward or inventory build", "probability_band": "medium"}
        ],
    }
    valuation = {
        "spot_price": 345,
        "bear_case": {"target_value": 75},
        "base_case": {"target_value": 165},
        "bull_case": {"target_value": 260},
    }
    audit = audit_pm_reasoning(reasoning, evidence=[], valuation=valuation)
    assert audit["thesis_vs_valuation"]["code"] == "market_above_bull"
    assert audit["verdict"] == "FAIL"
    assert any("below Base" in item or "spot > bull" in item or "above Bull" in item for item in audit["unsupported_llm_claims"] + audit["warnings"])
    assert reasoning["competing_hypotheses"][0]["speculative_hypothesis"] is True
    assert reasoning["competing_hypotheses"][0]["grade"] == "SPECULATION"


def test_valuation_stance_below_base() -> None:
    stance = valuation_stance(100, {"bear": 70, "base": 165, "bull": 260})
    assert stance["code"] == "market_below_base"
    assert stance["spot_below_base"] is True


def test_llm_cannot_replace_python_targets() -> None:
    brief = {
        "ticker": "TEST",
        "pack": {
            "template_id": "generic_company",
            "company_profile": {"legal_name": "Test Co", "last_close": 10, "eps_ttm": 1, "pe_ttm": 10},
            "earnings_history": [],
        },
        "assumptions": [{"id": "a1", "statement": "demand persists", "status": "unverified"}],
        "engine_views": [
            {
                "assumption_id": "a1",
                "id": "a1",
                "statement": "demand persists",
                "proposed_status": "strengthen",
                "supporting_evidence": [],
                "opposing_evidence": [],
                "unresolved_gaps": [],
            }
        ],
        "evidence": [{"id": "e1", "fact": "revenue grew", "source": "8-K", "source_type": "earnings_release", "excerpt": "revenue grew"}],
        "industry_findings": [],
        "risk_findings": [],
        "quant_findings": [],
        "competing_hypotheses": [],
    }
    payload = {
        "core_contradiction": "print vs duration",
        "decisive_variables": [
            {
                "name": "demand duration",
                "why_decisive": "sets the path",
                "current_view": "unresolved",
                "evidence_ids": ["e1"],
                "supporting_evidence_ids": ["e1"],
                "opposing_evidence_ids": [],
                "missing_evidence": ["independent confirmation"],
            }
        ],
        "assumption_rulings": [{"assumption_id": "a1", "final_status": "unchanged", "thesis_role": "core", "reasoning": "a print is not duration", "key_supporting_evidence_ids": ["e1"]}],
        "conviction_hierarchy": ["duration"],
        "core_thesis": "Duration is the debate.",
        "short_term_view": "near term follows the print.",
        "mid_term_view": "delivery vs outlook.",
        "long_term_view": "needs duration.",
        "market_disagreement": [],
        "top_thesis_changing_evidence": [{"evidence_id": "e1", "why_it_changes_thesis": "only print"}],
        "looks_important_but_does_not_change_thesis": [],
        "strongest_evidence": {"evidence_id": "e1", "why": "official print"},
        "weakest_link": "no customer confirmation",
        "most_likely_wrong": "treating a print as duration",
        "next_information_to_seek": "customer capex",
        "what_would_change_my_mind": "independent capex",
        "thesis_invalidation": "capex cuts",
        "valuation_driver_judgment": "python cases are the map",
        "counterfactuals": [
            {"if": "capex delays", "thesis_impact": "weakens", "eps_or_valuation_direction": "lower", "what_to_recompute": "base"},
            {"if": "growth 70%", "thesis_impact": "shrinks", "eps_or_valuation_direction": "lower", "what_to_recompute": "base"},
            {"if": "margin lower", "thesis_impact": "eps", "eps_or_valuation_direction": "lower", "what_to_recompute": "eps"},
        ],
        "competing_hypotheses": [{"statement": "duration overstated", "probability_band": "medium", "supporting_evidence_ids": ["e1"]}],
        "golden_answers": {"core_contradiction": "print vs duration"},
    }
    python_only = build_pm_judgment(brief, completer=None)
    llm = build_pm_judgment(brief, completer=ScriptedCompleter([payload]))
    assert llm["valuation"]["bear_case"] == python_only["valuation"]["bear_case"]
    assert llm["pm_reasoning"]["top_thesis_changing_evidence"][0]["evidence_id"] == "e1"
    assert llm["pm_reasoning"]["consistency_audit"]["valuation_consistency"]["llm_replaced_numbers"] is False
