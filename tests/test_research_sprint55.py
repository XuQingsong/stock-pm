from stock_pm.research.agents.fundamental import FundamentalAgent
from stock_pm.research.agents.industry import IndustryAgent
from stock_pm.research.agents.quant import QuantAgent
from stock_pm.research.agents.risk import RiskAgent
from stock_pm.research.agents.search_data import SearchDataAgent
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.llm_reason import unknown_citations
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pm_judge import build_pm_judgment
from stock_pm.research.service import ResearchService
from stock_pm.research.types import AgentInput


class ScriptedCompleter:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        payload = self.payloads.pop(0) if self.payloads else {}
        return {
            "status": "ok",
            "payload": payload,
            "model": "deepseek-chat",
            "provider": "openai",
            "llm_called": True,
            "llm_status": "ok",
            "prompt_hash": "abc",
            "latency_ms": 12,
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
            "fallback_used": False,
            "error": None,
        }


class MissingKeyCompleter:
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        return {
            "status": "missing_key",
            "payload": None,
            "model": "deepseek-chat",
            "provider": "openai",
            "llm_called": False,
            "llm_status": "skipped",
            "fallback_used": True,
            "error": "missing key",
        }


def _input() -> AgentInput:
    return AgentInput(
        ticker="TEST",
        task={"task_type": "industry_check", "title": "check demand", "required_data": []},
        research_pack={"template_id": "generic_company", "company_profile": {}, "missing_fields": []},
        assumptions=[{"id": "a1", "statement": "customer demand can persist", "status": "unverified"}],
        evidence=[
            {
                "id": "e1",
                "fact": "customer capital expenditures increased",
                "source": "10-Q",
                "source_time": "2026-09-01T00:00:00+00:00",
                "source_type": "sec_filing",
            }
        ],
    )


def test_search_plan_does_not_create_evidence() -> None:
    completer = ScriptedCompleter(
        [
            {
                "search_questions": ["Is customer capex still rising?"],
                "search_queries": ["hyperscaler capex guidance 10-Q"],
                "preferred_source_types": ["sec_filing"],
                "what_would_change_my_mind": ["customer capex cut"],
                "new_evidence": [
                    {
                        "evidence_type": "filing",
                        "fact": "Meta confirmed a fake contract",
                        "source": "hallucination",
                        "source_time": "2026-01-01T00:00:00+00:00",
                    }
                ],
            }
        ]
    )
    output = SearchDataAgent(completer=completer).run(_input())
    assert output.llm_audit["llm_called"] is True
    assert output.llm_audit["llm_status"] == "ok"
    assert output.model == "deepseek-chat"
    assert output.reasoning["search_plan"]["search_queries"] == ["hyperscaler capex guidance 10-Q"]
    assert output.new_evidence == []


def test_industry_llm_links_replace_keyword_fallback() -> None:
    completer = ScriptedCompleter(
        [
            {
                "assumption_links": [
                    {
                        "assumption_id": "a1",
                        "evidence_id": "e1",
                        "direction": "support",
                        "relevance": "direct",
                        "strength": "moderate",
                        "reason": "customer capex is a demand-side input to this persistence claim",
                        "causal_path": "end demand to capex, deployment still missing",
                        "independence_note": "independent customer family",
                    }
                ],
                "proposed_assumption_changes": [
                    {"assumption_id": "a1", "proposed_status": "unchanged", "reason": "duration still unproven"}
                ],
                "findings": ["capex is related but not duration proof"],
                "new_evidence": [],
                "confidence": 0.6,
            }
        ]
    )
    output = IndustryAgent(completer=completer).run(_input())
    assert output.reasoning["linking"] == "llm"
    assert output.assumption_links[0]["evidence_id"] == "e1"
    assert "Causal path:" in output.assumption_links[0]["reason"]
    assert output.new_evidence == [] or all("Meta confirmed" not in str(item.get("fact")) for item in output.new_evidence)


def test_hypothesis_missing_evidence_does_not_split_strings() -> None:
    from stock_pm.research.llm_reason import clean_hypotheses

    rows = clean_hypotheses(
        [
            {
                "statement": "demand duration is overstated",
                "probability_band": "medium",
                "supporting_evidence_ids": ["e1"],
                "missing_evidence": "Customer capex guidance from the next 10-Q",
            }
        ],
        evidence_ids={"e1"},
    )
    assert rows[0]["missing_evidence"] == ["Customer capex guidance from the next 10-Q"]


def test_unknown_evidence_id_is_rejected() -> None:
    payload = {"assumption_links": [{"assumption_id": "a1", "evidence_id": "does-not-exist"}]}
    assert unknown_citations(payload, {"a1", "e1"}) == ["does-not-exist"]
    payload = {"assumption_links": [{"assumption_id": "a1", "evidence_id": "does-not-exist"}]}
    assert unknown_citations(payload, {"a1", "e1"}) == ["does-not-exist"]


def test_risk_emits_competing_hypotheses() -> None:
    completer = ScriptedCompleter(
        [
            {
                "competing_hypotheses": [
                    {
                        "statement": "demand duration is overstated",
                        "probability_band": "medium",
                        "supporting_evidence_ids": ["e1"],
                        "opposing_evidence_ids": [],
                        "missing_evidence": ["named customer capex"],
                        "how_to_test": "read next customer 10-Q capex guide",
                        "impact_if_true": "growth persistence stays unresolved",
                    }
                ],
                "assumption_links": [],
                "proposed_assumption_changes": [
                    {"assumption_id": "a1", "proposed_status": "unchanged", "reason": "未发现足够反证"}
                ],
                "findings": ["no hard counter located"],
                "confidence": 0.4,
            }
        ]
    )
    output = RiskAgent(completer=completer).run(_input())
    assert output.reasoning["competing_hypotheses"][0]["probability_band"] == "medium"
    assert output.llm_audit["model"] == "deepseek-chat"


def test_fundamental_economic_drivers_and_quant_interpretation() -> None:
    fund = FundamentalAgent(
        completer=ScriptedCompleter(
            [
                {
                    "key_economic_drivers": [
                        {
                            "driver": "volume vs mix",
                            "why_it_matters": "headline growth may not map to EPS",
                            "evidence_ids": [],
                            "duration": "unknown",
                            "confidence": "medium",
                            "valuation_channel": "margin",
                        }
                    ],
                    "findings": ["growth quality is the question"],
                    "new_assumptions": [],
                    "confidence": 0.5,
                }
            ]
        )
    ).run(_input())
    assert fund.reasoning["key_economic_drivers"][0]["driver"] == "volume vs mix"
    quant = QuantAgent(
        completer=ScriptedCompleter(
            [
                {
                    "competing_interpretations": [
                        {
                            "statement": "valuation compression after a strong print",
                            "classification": "supported_inference",
                            "evidence_ids": [],
                            "why": "python tape is negative while print is positive",
                        }
                    ],
                    "findings": [],
                    "confidence": 0.5,
                }
            ]
        )
    ).run(_input())
    assert quant.reasoning["competing_interpretations"][0]["classification"] == "supported_inference"
    assert quant.new_evidence or quant.findings


def test_missing_key_is_recorded_not_silent() -> None:
    output = IndustryAgent(completer=MissingKeyCompleter()).run(_input())
    assert output.llm_audit["llm_called"] is False
    assert output.llm_audit["llm_status"] == "skipped"
    assert output.llm_audit["fallback_used"] is True
    assert output.reasoning["linking"] == "deterministic_fallback"


def test_pm_llm_owns_thesis_and_keeps_python_valuation() -> None:
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
        "evidence": [
            {
                "id": "e1",
                "fact": "revenue grew",
                "source": "8-K",
                "source_type": "earnings_release",
            }
        ],
        "industry_findings": [],
        "risk_findings": [],
        "quant_findings": [],
        "competing_hypotheses": [{"statement": "duration overstated", "probability_band": "medium"}],
    }
    completer = ScriptedCompleter(
        [
            {
                "core_contradiction": "print strength versus duration doubt",
                "decisive_variables": [
                    {
                        "name": "demand duration",
                        "why_decisive": "it sets the earnings path",
                        "current_view": "unresolved",
                        "evidence_ids": ["e1"],
                        "sensitivity": "if duration fails, base case fails",
                        "next_check": "next customer capex",
                    }
                ],
                "assumption_rulings": [
                    {
                        "assumption_id": "a1",
                        "final_status": "unchanged",
                        "thesis_role": "core",
                        "reasoning": "a print is not duration",
                        "key_supporting_evidence_ids": ["e1"],
                        "key_opposing_evidence_ids": [],
                    }
                ],
                "conviction_hierarchy": ["duration is the binding variable"],
                "core_thesis": "The core debate is duration, not the last print.",
                "short_term_view": "near term follows the last print.",
                "mid_term_view": "delivery versus outlook.",
                "long_term_view": "earnings power needs duration.",
                "market_disagreement": [
                    {
                        "pm_believes": "duration is unproven",
                        "market_appears_to_price": "a long growth runway",
                        "why_pm_differs": "customer confirmation is thin",
                        "evidence_that_would_prove_market_right": "independent multi-year capex",
                    }
                ],
                "top_thesis_changing_evidence": [{"evidence_id": "e1", "why_it_changes_thesis": "it is the only print"}],
                "looks_important_but_does_not_change_thesis": [],
                "strongest_evidence": {"evidence_id": "e1", "why": "official print"},
                "weakest_link": "no independent customer confirmation",
                "what_could_make_me_wrong": "duration is real",
                "next_information_to_seek": "customer capex",
                "thesis_invalidation": "customer capex cuts",
                "valuation_driver_judgment": "python base case is a map, not a target to replace",
                "counterfactuals": [
                    {"if": "customer capex delays one year", "thesis_impact": "duration claim weakens", "eps_or_valuation_direction": "lower", "what_to_recompute": "base target"},
                    {"if": "growth is 70% of base", "thesis_impact": "upside shrinks", "eps_or_valuation_direction": "lower", "what_to_recompute": "base target"},
                    {"if": "margin 300bps lower", "thesis_impact": "EPS elasticity shows up", "eps_or_valuation_direction": "lower", "what_to_recompute": "eps"},
                ],
                "golden_answers": {"core_contradiction": "print vs duration"},
            }
        ]
    )
    python_only = build_pm_judgment(brief, completer=None)
    llm = build_pm_judgment(brief, completer=completer)
    assert python_only["llm_audit"]["llm_status"] == "skipped"
    assert "researched under" in python_only["thesis"]["core_thesis"]
    assert llm["llm_audit"]["llm_status"] == "ok"
    assert llm["thesis"]["core_thesis"] == "The core debate is duration, not the last print."
    assert len(llm["pm_reasoning"]["decisive_variables"]) == 1
    assert len(llm["pm_reasoning"]["market_disagreement"]) == 1
    assert len(llm["pm_reasoning"]["counterfactuals"]) == 3
    assert llm["valuation"]["bear_case"] == python_only["valuation"]["bear_case"]
    assert llm["pm_reasoning"]["top_thesis_changing_evidence"][0]["evidence_id"] == "e1"


def test_get_service_injects_completer() -> None:
    import inspect

    from stock_pm.research import api as research_api
    from stock_pm.research.agents.base import SettingsCompleter

    source = inspect.getsource(research_api.get_service)
    assert "SettingsCompleter" in source
    assert ResearchService(InMemoryResearchStore(), completer=SettingsCompleter()).completer is not None


def test_workflow_records_llm_audit_columns() -> None:
    store = InMemoryResearchStore()
    svc = ResearchService(store)
    run = store.insert_agent_run({"ticker": "TEST", "agent_name": "industry", "status": "running"})
    completed = store.complete_agent_run(
        run["id"],
        status="success",
        output_json={"findings": ["x"], "llm_audit": {"llm_status": "ok"}},
        model="deepseek-chat",
        llm_called=True,
        llm_status="ok",
        llm_provider="openai",
        prompt_hash="abc",
        latency_ms=20,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        fallback_used=False,
    )
    assert completed["model"] == "deepseek-chat"
    assert completed["llm_called"] is True
    assert completed["llm_status"] == "ok"
    assert completed["total_tokens"] == 15
    assert completed["fallback_used"] is False
