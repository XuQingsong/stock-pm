"""One-shot research → brain_* materialize. No GLM. Idempotent. Page paths stay read-only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.materialize_from_research import (
    GAPS,
    MARKET_THEME_LABELS,
    SOURCE_KIND,
    _classify_market_theme,
    _extract_theme_copy,
    _is_company_specific_trigger,
    materialize_from_research,
    parse_tickers,
)
from stock_pm.brain.pm_view import build_pm_view
from stock_pm.brain.product_read import EMPTY_DOMINANT, build_market_overview
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService


class _SpyCompleter:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("materialize and page paths must not call an LLM completer")


class _Market:
    def __init__(self, snapshots: list[dict] | None = None, events: list[dict] | None = None) -> None:
        self.environment_snapshots = list(snapshots or [])
        self._events = list(events or [])

    def market_events(self, symbol: str, limit: int = 25) -> list[dict]:
        rows = [row for row in self._events if str(row.get("symbol") or "").upper() == symbol.upper()]
        return rows[:limit]


def _seed_avgo(store: InMemoryResearchStore) -> None:
    store.upsert_pack(
        {
            "ticker": "AVGO",
            "company_profile": {"legal_name": "Broadcom Inc.", "sector": "Semiconductors"},
            "industry_context": {
                "summary": "Hyperscaler AI capex and custom silicon demand remain the industry variable.",
                "cycle": "semiconductor cycle is still AI-capex led",
            },
            "major_events": [
                {"id": "meta_capex", "title": "Meta raises AI capital expenditure", "event_type": "capex", "date": "2026-09-10"}
            ],
            "earnings_history": [
                {"fiscal_period": "Q3 FY26", "eps": 1.69, "eps_estimate": 1.55},
            ],
        }
    )
    assumption = store.insert_assumption(
        {
            "id": "rasm_avgo_ai",
            "ticker": "AVGO",
            "category": "demand",
            "statement": "AI capex expectations and custom silicon demand stay the live market variable.",
            "status": "strengthened",
            "importance": "high",
            "thesis_role": "core",
            "confidence": 0.8,
            "next_verification": "Next hyperscaler capex print",
            "invalidation_condition": "Named hyperscalers cut AI capex.",
        }
    )
    evidence = store.insert_evidence(
        {
            "id": "rev_avgo_ai",
            "ticker": "AVGO",
            "evidence_type": "filing",
            "fact": "Management cited AI demand and custom silicon backlog.",
            "source": "10-Q",
            "source_time": "2026-09-01T00:00:00+00:00",
            "retrieved_at": "2026-09-01T00:00:00+00:00",
            "importance": "high",
            "direction": "support",
        }
    )
    store.insert_link(
        {
            "assumption_id": assumption["id"],
            "evidence_id": evidence["id"],
            "direction": "support",
            "strength": "strong",
        }
    )
    store.insert_thesis(
        {
            "id": "ith_avgo_1",
            "ticker": "AVGO",
            "version": 1,
            "core_thesis": "AVGO remains a core way to own durable AI infrastructure demand.",
            "key_assumption_ids": [assumption["id"]],
            "core_assumption_ids": [assumption["id"]],
            "key_risks": ["Customer concentration if one hyperscaler pauses"],
            "invalidation_conditions": ["A named customer cuts AI spend."],
            "monitoring_items": ["Watch the next AI capex guide"],
            "confidence": 0.72,
            "actor": "pm_judge",
        }
    )
    store.insert_valuation(
        {
            "id": "val_avgo_1",
            "ticker": "AVGO",
            "thesis_id": "ith_avgo_1",
            "horizon": "2y",
            "base_case": {"narrative": "Base case uses the existing 2y horizon only."},
            "bear_case": {},
            "bull_case": {},
            "spot_price": 180.0,
        }
    )
    store.insert_snapshot(
        {
            "ticker": "AVGO",
            "pack_payload": store.get_pack("AVGO"),
            "assumption_payload": [assumption],
            "competing_hypotheses": [
                {
                    "statement": "Optical names are also trading AI capex expectations, not one print.",
                    "probability_band": "medium",
                    "supporting_evidence_ids": [evidence["id"]],
                    "how_to_test": "Compare AVGO vs optical peers on the next capex print.",
                }
            ],
            "economic_drivers": [
                {
                    "driver": "AI demand durability",
                    "why_it_matters": "Custom silicon converts AI capex expectations into revenue.",
                    "valuation_channel": "Revenue duration through custom silicon.",
                    "evidence_ids": [evidence["id"]],
                    "confidence": "high",
                }
            ],
            "is_fixture": False,
        }
    )


def _inventory(store: BrainStore) -> dict[str, object]:
    return {
        "hypotheses": sorted(
            (row.get("ticker"), row.get("canonical_key"), row.get("hypothesis")) for row in store.list_all_hypotheses()
        ),
        "attentions": sorted((row.get("ticker"), row.get("name")) for row in store.list_all_market_attentions()),
        "expectations": sorted((row.get("ticker"), row.get("name")) for row in store.list_all_expectations()),
        "states": sorted((row.get("ticker") or "", row.get("state_key"), row.get("statement")) for row in store.list_all_states()),
        "claims": sorted((row.get("ticker"), row.get("claim_key"), row.get("statement")) for row in store.list_active_claims("AVGO") + store.list_active_claims("LITE")),
        "theses": sorted((row.get("ticker"), row.get("current_thesis")) for row in (store.list_theses("AVGO") + store.list_theses("LITE"))),
        "drivers": sorted((row.get("ticker"), row.get("canonical_key")) for row in store.list_all_drivers()),
        "events": sorted((row.get("ticker"), row.get("fingerprint") or row.get("title")) for row in store.list_all_events()),
        "questions": sorted((row.get("ticker"), row.get("question")) for row in store.list_questions("AVGO") + store.list_questions("LITE")),
        "valuation": (store.latest_valuation_state("AVGO") or {}).get("supporting_data"),
        "history": len(store.list_all_history()),
        "gaps": GAPS,
    }


def test_parse_tickers_dedupes_and_uppercases() -> None:
    assert parse_tickers("avgo, LITE,AVGO") == ["AVGO", "LITE"]
    assert parse_tickers(["lite", "avgo"]) == ["LITE", "AVGO"]


def test_materialize_maps_existing_research_without_llm() -> None:
    research = InMemoryResearchStore()
    _seed_avgo(research)
    brain = BrainStore()
    market = _Market(
        snapshots=[
            {
                "id": 1,
                "scope": "market",
                "one_liner": "Tape is still trading AI capex expectations across semis.",
                "row_thesis": "AI capex remains the cross-asset variable.",
                "publishState": "published",
            }
        ],
        events=[
            {
                "symbol": "AVGO",
                "event_type": "capex",
                "title": "Meta raises AI capital expenditure",
                "event_time": "2026-09-10T00:00:00+00:00",
                "severity": "high",
                "details": {},
            }
        ],
    )
    result = materialize_from_research(["AVGO", "LITE"], research=research, brain=brain, market=market)
    assert result["llm_invoked"] is False
    assert result["scheduled"] is False
    assert result["source_kind"] == SOURCE_KIND
    by_ticker = {row["ticker"]: row for row in result["results"]}
    assert by_ticker["AVGO"]["status"] == "written"
    assert by_ticker["AVGO"]["llm_invoked"] is False
    assert by_ticker["LITE"]["status"] == "empty"
    assert by_ticker["LITE"]["written"]["claims"] == 0
    assert by_ticker["LITE"]["reason"]
    hyps = brain.list_hypotheses("AVGO")
    assert hyps
    assert any(row.get("kind") == "ai_demand" for row in hyps)
    assert any(row.get("source_kind") == SOURCE_KIND for row in hyps)
    assert brain.latest_thesis("AVGO")["current_thesis"].startswith("AVGO remains")
    claims = brain.list_active_claims("AVGO")
    assert any(not row.get("is_core") and "AI capex" in (row.get("statement") or "") for row in claims)
    assert build_pm_view(brain, "AVGO")["core_claims"] == []
    assert any(row.get("what_would_invalidate") for row in claims)
    assert brain.list_expectations("AVGO")
    assert any(row.get("state_type") == "industry" for row in brain.list_states("AVGO"))
    assert any(row.get("state_type") == "macro" for row in brain.list_all_states())
    overview = build_market_overview(brain)
    assert overview["llm_invoked"] is False
    assert overview["empty_state"] is None
    assert overview["dominant_drivers"]
    assert any(row.get("category") == "ai_capex_expectations" for row in overview["dominant_drivers"])
    snapshot = build_pm_view(brain, "AVGO")
    assert snapshot["llm_invoked"] is False
    assert snapshot["thesis"]["empty"] is False
    lite = build_pm_view(brain, "LITE")
    assert lite["llm_invoked"] is False
    assert lite["core_claims"] == []


def test_materialize_is_idempotent() -> None:
    research = InMemoryResearchStore()
    _seed_avgo(research)
    brain = BrainStore()
    market = _Market(
        snapshots=[{"scope": "market", "one_liner": "Hyperscaler AI capex still sets the tape.", "publishState": "published"}]
    )
    first = materialize_from_research("AVGO,LITE", research=research, brain=brain, market=market)
    inv1 = _inventory(brain)
    second = materialize_from_research(["AVGO", "LITE"], research=research, brain=brain, market=market)
    inv2 = _inventory(brain)
    assert first["llm_invoked"] is False
    assert second["llm_invoked"] is False
    assert inv1 == inv2
    assert len(brain.list_theses("AVGO")) == 1
    assert len(brain.list_hypotheses("AVGO")) == len(inv1["hypotheses"])


def test_lite_without_research_stays_honestly_empty() -> None:
    research = InMemoryResearchStore()
    brain = BrainStore()
    result = materialize_from_research("LITE", research=research, brain=brain)
    row = result["results"][0]
    assert row["status"] == "empty"
    assert row["written"] == {
        "hypotheses": 0,
        "attentions": 0,
        "expectations": 0,
        "states": 0,
        "claims": 0,
        "claim_links": 0,
        "thesis": 0,
        "drivers": 0,
        "events": 0,
        "questions": 0,
        "valuation": 0,
        "exposures": 0,
    }
    overview = build_market_overview(brain)
    assert overview["dominant_drivers"] == []
    assert overview["empty_state"] == EMPTY_DOMINANT
    assert overview["llm_invoked"] is False


def test_does_not_invent_missing_downstream_fields() -> None:
    research = InMemoryResearchStore()
    research.upsert_pack(
        {
            "ticker": "AVGO",
            "company_profile": {"legal_name": "Broadcom Inc."},
        }
    )
    research.insert_assumption(
        {
            "ticker": "AVGO",
            "statement": "Gross margin stays in a known band.",
            "thesis_role": "supporting",
            "status": "unverified",
        }
    )
    brain = BrainStore()
    materialize_from_research("AVGO", research=research, brain=brain)
    claim = brain.list_active_claims("AVGO")[0]
    assert claim.get("what_would_invalidate") in {"", None}
    assert brain.list_causal_edges("AVGO") == []
    assert brain.list_divergences("AVGO") == []
    overview = build_market_overview(brain)
    assert overview["cross_asset_summary"] == []
    assert overview["sector_summary"] == []
    assert "causal_edges" in GAPS


def test_materialize_and_page_paths_never_invoke_llm(monkeypatch) -> None:
    research_store = InMemoryResearchStore()
    _seed_avgo(research_store)
    spy = _SpyCompleter()
    research = ResearchService(store=research_store, completer=spy)
    brain = BrainStore()

    def boom(*args, **kwargs):
        raise AssertionError("must not re-run research or Brain LLM paths")

    monkeypatch.setattr("stock_pm.brain.pipeline.run_brain", boom)
    monkeypatch.setattr("stock_pm.brain.runtime.run_brain_update", boom)
    monkeypatch.setattr("stock_pm.brain.bootstrap.bootstrap_brain", boom)
    monkeypatch.setattr("stock_pm.llm.complete_json", boom)
    materialize_from_research("AVGO,LITE", research=research, brain=brain)
    assert spy.calls == 0
    brain_api._override = {"research": research, "store": brain}
    try:
        client = TestClient(api.app)
        market = client.get("/api/market/overview")
        company = client.get("/api/brain/AVGO/pm-view")
        lite = client.get("/api/brain/LITE/pm-view")
        claim_id = brain.list_active_claims("AVGO")[0]["claim_id"]
        claim = client.get(f"/api/brain/AVGO/claims/{claim_id}")
    finally:
        brain_api._override = None
    assert spy.calls == 0
    assert market.status_code == 200
    assert company.status_code == 200
    assert lite.status_code == 200
    assert claim.status_code == 200
    assert market.json()["llm_invoked"] is False
    assert company.json()["llm_invoked"] is False
    assert lite.json()["llm_invoked"] is False
    assert claim.json()["llm_invoked"] is False
    assert market.json()["dominant_drivers"] == []
    assert market.json()["market_state"] == "empty"
    assert lite.json()["core_claims"] == []


def test_classify_skips_issuer_triggers_but_keeps_market_framed_themes() -> None:
    assert _is_company_specific_trigger({"title": "Meta raises AI capital expenditure", "event_type": "capex"}) is True
    assert _classify_market_theme("Meta raises AI capital expenditure") is None
    assert _classify_market_theme("Gross margin stays in a known band.") is None
    assert (
        _classify_market_theme(
            "The tape is trading AI capex expectations after Meta raised capital expenditure."
        )
        == "ai_capex_expectations"
    )
    assert _classify_market_theme("Real yields and treasury rates are the live market variable.") == "real_yields"
    assert _classify_market_theme("盘面：趋势健康；消息：非农强于预期 → 降息预期降温。") == "real_yields"
    assert _classify_market_theme("收益率与利率仍是跨资产主轴") == "real_yields"
    assert _classify_market_theme("盘面仍在交易AI资本开支预期") == "ai_capex_expectations"
    assert _classify_market_theme("Management can deliver AI accelerators against current guidance.") is None


def test_agent_run_findings_write_market_hyp_and_attention() -> None:
    research = InMemoryResearchStore()
    research.upsert_pack({"ticker": "AVGO", "company_profile": {"legal_name": "Broadcom Inc."}})
    research.insert_assumption(
        {
            "ticker": "AVGO",
            "statement": "Gross margin stays in a known band.",
            "thesis_role": "core",
            "status": "unchanged",
        }
    )
    research.insert_agent_run(
        {
            "ticker": "AVGO",
            "agent_name": "industry",
            "status": "success",
            "output_json": {
                "findings": [
                    "Hyperscaler AI capex remains the industry demand variable.",
                    "customer or industry capex language is present",
                    "EPS beat 4 of last 6 estimated prints",
                ],
                "reasoning": {},
            },
        }
    )
    research.insert_agent_run(
        {
            "ticker": "AVGO",
            "agent_name": "pm_judge",
            "status": "success",
            "output_json": {
                "findings": [],
                "pm_reasoning": {
                    "decisive_variables": ["AI capex expectations across hyperscalers"],
                    "competing_hypotheses": [],
                },
                "reasoning": {},
            },
        }
    )
    research.insert_agent_run(
        {
            "ticker": "AVGO",
            "agent_name": "fundamental",
            "status": "success",
            "output_json": {
                "findings": ["latest revenue beat versus consensus"],
                "reasoning": {
                    "key_economic_drivers": [
                        {
                            "driver": "AI infrastructure spend",
                            "why_it_matters": "Custom silicon converts AI capex expectations into revenue.",
                            "confidence": "high",
                        }
                    ]
                },
            },
        }
    )
    brain = BrainStore()
    result = materialize_from_research("AVGO", research=research, brain=brain)
    assert result["llm_invoked"] is False
    hyps = brain.list_hypotheses("AVGO")
    assert hyps
    assert all(row.get("kind") in {"ai_demand", "sector_macro", "real_yields"} for row in hyps)
    assert any(row.get("kind") == "ai_demand" for row in hyps)
    assert not any("Meta raises" in (row.get("hypothesis") or "") for row in hyps)
    attentions = brain.list_market_attentions("AVGO")
    assert attentions
    assert any("AI capex" in (row.get("name") or "") for row in attentions)
    overview = build_market_overview(brain)
    # one ticker + no macro yet: cluster must not invent a global driver
    assert overview["llm_invoked"] is False
    assert overview["dominant_drivers"] == []


def test_environment_struct_macro_helps_promote_overview() -> None:
    research = InMemoryResearchStore()
    research.upsert_pack({"ticker": "AVGO", "company_profile": {"legal_name": "Broadcom Inc."}})
    research.insert_assumption(
        {
            "ticker": "AVGO",
            "statement": "The tape is trading AI capex expectations after Meta raised capital expenditure.",
            "thesis_role": "supporting",
            "status": "strengthened",
            "confidence": 0.7,
        }
    )
    research.insert_assumption(
        {
            "ticker": "AVGO",
            "statement": "Meta raises AI capital expenditure",
            "thesis_role": "none",
            "status": "unchanged",
        }
    )
    brain = BrainStore()
    market = _Market(
        snapshots=[
            {
                "id": 9,
                "scope": "market",
                "one_liner": "环境信息暂缺，当前判断置信度有限。",
                "row_thesis": "环境信息暂缺，当前判断置信度有限。",
                "publishState": "published",
                "struct": {
                    "news": {
                        "macro": {
                            "clause": "盘面仍在交易AI资本开支预期",
                            "headline": "AI capex remains the cross-asset variable",
                            "themes": ["semis"],
                        }
                    },
                    "synthesis": "Tape is still trading AI capex expectations across semis.",
                },
            }
        ]
    )
    result = materialize_from_research("AVGO,COHR,XOM", research=research, brain=brain, market=market)
    assert result["llm_invoked"] is False
    assert result["market_environment"]["states_written"] >= 1
    macros = [row for row in brain.list_all_states() if row.get("state_type") == "macro"]
    assert macros
    assert any(row.get("state_key") == "ai_capex_expectations" for row in macros)
    assert any(row.get("ticker") in {None, ""} for row in macros)
    hyps = brain.list_hypotheses("AVGO")
    assert hyps
    assert any(row.get("kind") == "ai_demand" for row in hyps)
    assert not any("Meta raises AI capital expenditure" == (row.get("hypothesis") or "") for row in hyps)
    overview = build_market_overview(brain)
    assert overview["llm_invoked"] is False
    assert overview["empty_state"] is None
    assert overview["dominant_drivers"]
    assert any(row.get("category") == "ai_capex_expectations" for row in overview["dominant_drivers"])


def test_two_tickers_from_agent_findings_promote_without_env() -> None:
    research = InMemoryResearchStore()
    for symbol in ("AVGO", "COHR"):
        research.upsert_pack({"ticker": symbol, "company_profile": {"legal_name": symbol}})
        research.insert_assumption(
            {
                "ticker": symbol,
                "statement": f"{symbol} gross margin stays in a known band.",
                "thesis_role": "supporting",
                "status": "unchanged",
            }
        )
        research.insert_agent_run(
            {
                "ticker": symbol,
                "agent_name": "industry",
                "status": "success",
                "output_json": {
                    "findings": ["Optical and ASIC names are trading hyperscaler AI capex expectations, not one print."],
                    "reasoning": {},
                },
            }
        )
    brain = BrainStore()
    materialize_from_research("AVGO,COHR,XOM", research=research, brain=brain)
    assert brain.list_hypotheses("AVGO")
    assert brain.list_hypotheses("COHR")
    assert brain.list_hypotheses("XOM") == []
    overview = build_market_overview(brain)
    assert overview["llm_invoked"] is False
    assert overview["dominant_drivers"]
    assert any(row.get("category") == "ai_capex_expectations" for row in overview["dominant_drivers"])
    tickers = set()
    for row in overview["dominant_drivers"]:
        tickers.update(row.get("affected_tickers") or [])
    assert {"AVGO", "COHR"} <= tickers


LIVE_CHINESE_DESK = (
    "盘面：趋势健康；消息：非农强于预期 → 降息预期降温，利空高估值成长；"
    "因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。"
)
AVGO_ACCELERATOR_ASSUMPTION = "Management can deliver AI accelerators against current guidance."


def _live_prod_fixture(research: InMemoryResearchStore) -> _Market:
    research.upsert_pack({"ticker": "AVGO", "company_profile": {"legal_name": "Broadcom Inc.", "sector": "Semiconductors"}})
    research.insert_assumption(
        {
            "id": "rasm_avgo_accel",
            "ticker": "AVGO",
            "category": "execution",
            "statement": AVGO_ACCELERATOR_ASSUMPTION,
            "status": "unchanged",
            "importance": "high",
            "thesis_role": "core",
            "confidence": 0.7,
        }
    )
    return _Market(
        snapshots=[
            {
                "id": 42,
                "scope": "market",
                "one_liner": LIVE_CHINESE_DESK,
                "row_thesis": LIVE_CHINESE_DESK,
                "synthesis": LIVE_CHINESE_DESK,
                "publishState": "published",
            }
        ]
    )


def test_chinese_desk_env_uses_canonical_keys_not_raw_sentence() -> None:
    name, statement = _extract_theme_copy([LIVE_CHINESE_DESK], "real_yields")
    assert "降息" in name
    assert "降息" in statement
    assert "macro_env_" not in name
    assert LIVE_CHINESE_DESK.startswith("盘面")

    research = InMemoryResearchStore()
    market = _live_prod_fixture(research)
    brain = BrainStore()
    first = materialize_from_research("AVGO,LITE", research=research, brain=brain, market=market)
    assert first["llm_invoked"] is False
    assert first["market_environment"]["states_written"] >= 1

    macros = [row for row in brain.list_all_states() if row.get("state_type") == "macro"]
    assert macros
    assert all(row.get("state_key") in MARKET_THEME_LABELS for row in macros)
    assert any(row.get("state_key") == "real_yields" for row in macros)
    assert not any(str(row.get("state_key") or "").startswith("macro_env_") for row in macros)
    assert not any("盘面" in str(row.get("state_key") or "") for row in macros)
    rates = next(row for row in macros if row.get("state_key") == "real_yields")
    assert rates.get("ticker") in {None, ""}
    assert "降息" in (rates.get("name") or "") or "降息" in (rates.get("statement") or "")
    assert (rates.get("subject") or "") == MARKET_THEME_LABELS["real_yields"]

    claims = brain.list_active_claims("AVGO")
    assert any(AVGO_ACCELERATOR_ASSUMPTION in (row.get("statement") or "") for row in claims)
    hyps = brain.list_hypotheses("AVGO")
    assert not hyps  # Global environment observations do not create ticker hypotheses.
    assert not any("accelerator" in (row.get("hypothesis") or "").lower() for row in hyps)
    assert not any(AVGO_ACCELERATOR_ASSUMPTION == (row.get("hypothesis") or "") for row in hyps)
    attentions = brain.list_market_attentions("AVGO")
    assert not attentions

    lite = next(row for row in first["results"] if row["ticker"] == "LITE")
    assert lite["status"] == "empty"
    assert lite["written"]["hypotheses"] == 0
    assert lite["written"]["attentions"] == 0
    assert brain.list_hypotheses("LITE") == []

    overview = build_market_overview(brain)
    assert overview["llm_invoked"] is False
    assert overview["empty_state"] is None
    assert any(row.get("category") == "real_yields" for row in overview["dominant_drivers"])
    assert overview["assessment_basis"] == "global_environment"

    inv1 = _inventory(brain)
    second = materialize_from_research(["AVGO", "LITE"], research=research, brain=brain, market=market)
    assert second["llm_invoked"] is False
    assert _inventory(brain) == inv1
