from __future__ import annotations

from stock_pm.research.pm_desk import build_pm_desk
from stock_pm.research.pm_judge import _clean_pm_payload


def _live_like_reasoning() -> dict:
    return {
        "source": "llm",
        "core_thesis": "Custom silicon is growing fast, but durability is unverified.",
        "core_contradiction": "Raised guidance versus no independent customer confirmation.",
        "decisive_variables": [
            {"name": "demand durability", "why_decisive": "it sets the path", "current_view": "unverified", "evidence_ids": ["e1"]},
            {"name": "mix/margin", "why_decisive": "earnings power", "current_view": "undisclosed"},
            {"name": "guidance delivery", "why_decisive": "short streak", "current_view": "4 of 5"},
            {"name": "should be dropped", "why_decisive": "cap is 3"},
        ],
        "market_disagreement": [
            {"pm_believes": "duration unproven", "market_appears_to_price": "a long runway", "why_pm_differs": "no customer confirmation"},
            {"pm_believes": "mix dilution", "market_appears_to_price": "stable margins", "why_pm_differs": "no segment margins"},
            {"pm_believes": "too many", "market_appears_to_price": "drop this"},
        ],
        "top_thesis_changing_evidence": [
            {"evidence_id": "e1", "why_it_changes_thesis": "core print", "fact": "custom silicon +78%"},
            {"evidence_id": "e2", "why_it_changes_thesis": "guidance raise", "fact": "raised full-year revenue"},
            {"evidence_id": "e3", "why_it_changes_thesis": "customer capex", "fact": "customers increased capex"},
            {"evidence_id": "e4", "why_it_changes_thesis": "supply cover", "fact": "foundry cover two years"},
            {"evidence_id": "e5", "why_it_changes_thesis": "power constraint", "fact": "power is a constraint"},
            {"evidence_id": "e6", "why_it_changes_thesis": "should be dropped"},
        ],
        "looks_important_but_does_not_change_thesis": [
            {"evidence_id": "e7", "why_not": "short beat streak", "fact": "EPS beat 4 of 5"}
        ],
        "competing_hypotheses": [
            {
                "statement": "demand is a pull-forward",
                "probability_band": "medium",
                "missing_evidence": list("Customer backlog"),
                "how_to_test": "capex revisions",
                "impact_if_true": "growth multiple compresses",
            }
        ],
        "what_could_make_me_wrong": "treating a beat streak as duration proof",
        "next_information_to_seek": "independent customer confirmation",
        "golden_answers": {
            "most_likely_error": "treating a beat streak as duration proof",
            "evidence_that_would_change_the_call": "signed multi-year customer supply",
        },
        "counterfactuals": [
            {"if": "customer capex is cut", "thesis_impact": "guidance fails", "eps_or_valuation_direction": "down"},
            {"if": "margins dilute", "thesis_impact": "EPS lags revenue", "eps_or_valuation_direction": "down"},
            {"if": "customers confirm", "thesis_impact": "duration holds", "eps_or_valuation_direction": "up"},
        ],
    }


def test_build_pm_desk_caps_and_aliases() -> None:
    raw = _live_like_reasoning()
    desk = build_pm_desk(
        thesis={"core_thesis": "ignored if reasoning has one", "research_quality": {"pm_reasoning": raw}},
        evidence=[{"id": "e1", "fact": "from store"}],
    )
    assert desk["source"] == "llm"
    assert desk["compressed"] is True
    assert len(desk["decisive_variables"]) == 3
    assert len(desk["top_thesis_changing_evidence"]) == 5
    assert len(desk["market_disagreement"]) == 2
    assert desk["top_thesis_changing_evidence"][0]["fact"] == "custom silicon +78%"
    assert desk["top_thesis_changing_evidence"][1]["fact"] == "raised full-year revenue"
    store_only = build_pm_desk(
        thesis={
            "research_quality": {
                "pm_reasoning": {
                    "source": "llm",
                    "decisive_variables": [{"name": "demand", "why_decisive": "path"}],
                    "top_thesis_changing_evidence": [{"evidence_id": "e1", "why_it_changes_thesis": "print"}],
                }
            }
        },
        evidence=[{"id": "e1", "fact": "from store"}],
    )
    assert store_only["top_thesis_changing_evidence"][0]["fact"] == "from store"
    assert desk["low_value_evidence"][0]["evidence_id"] == "e7"
    assert desk["non_thesis_changing_evidence"][0]["evidence_id"] == "e7"
    assert desk["most_likely_wrong"] == "treating a beat streak as duration proof"
    assert desk["what_would_change_my_mind"] == "signed multi-year customer supply"
    assert desk["competing_hypotheses"][0]["missing_evidence"] == ["Customer backlog"]
    assert desk["next_information_to_seek"]


def test_clean_pm_payload_emits_required_aliases() -> None:
    cleaned = _clean_pm_payload(
        _live_like_reasoning(),
        assumption_ids=set(),
        evidence_ids={"e1", "e2", "e3", "e4", "e5", "e7"},
    )
    for key in (
        "decisive_variables",
        "top_thesis_changing_evidence",
        "low_value_evidence",
        "non_thesis_changing_evidence",
        "competing_hypotheses",
        "most_likely_wrong",
        "market_disagreement",
        "next_information_to_seek",
        "counterfactuals",
        "what_would_change_my_mind",
    ):
        assert key in cleaned
    assert len(cleaned["decisive_variables"]) == 3
    assert len(cleaned["top_thesis_changing_evidence"]) == 5
    assert cleaned["most_likely_wrong"]
    assert cleaned["competing_hypotheses"][0]["missing_evidence"] == ["Customer backlog"]
