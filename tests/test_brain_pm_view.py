"""PM View / Investment Snapshot: read persisted Brain, no new LLM."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.pm_view import build_pm_view, pm_questions_answerable
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService

AVGO_ARTIFACT = Path("artifacts/brain_token_stabilization/after_run/final_brain.json")


def _seed_ticker(store: BrainStore, ticker: str, *, claim_title: str, support_fact: str, counter_fact: str) -> None:
    symbol = ticker.upper()
    store.insert_state(
        {
            "ticker": symbol,
            "state_id": f"bst_{symbol.lower()}_demand",
            "state_type": "company",
            "name": f"{symbol} demand state",
            "statement": f"{symbol} demand is elevated.",
            "confidence": "medium",
        }
    )
    store.insert_driver(
        {
            "ticker": symbol,
            "driver_id": f"bdrv_{symbol.lower()}_demand",
            "canonical_key": "demand_durability",
            "name": "Demand durability",
            "category": "demand",
            "current_state": f"{symbol} demand remains the live driver.",
            "related_claim_ids": [f"bclm_{symbol.lower()}_core"],
        }
    )
    store.insert_claim(
        {
            "ticker": symbol,
            "claim_id": f"bclm_{symbol.lower()}_core",
            "title": claim_title,
            "statement": f"{claim_title} is the live core claim.",
            "claim_type": "operating",
            "status": "challenged",
            "importance": "high",
            "confidence": "medium",
            "is_core": True,
            "why_it_matters": "This is the investment logic the PM must hold or kill.",
            "related_driver_ids": [f"bdrv_{symbol.lower()}_demand"],
        }
    )
    store.insert_claim(
        {
            "ticker": symbol,
            "claim_id": f"bclm_{symbol.lower()}_bg",
            "title": "Background tax claim",
            "statement": "Tax rate is not the live debate.",
            "status": "background",
            "is_core": False,
        }
    )
    store.upsert_evidence(
        {
            "id": f"rev_{symbol.lower()}_support",
            "ticker": symbol,
            "fact": support_fact,
            "source": "issuer",
        }
    )
    store.upsert_evidence(
        {
            "id": f"rev_{symbol.lower()}_counter",
            "ticker": symbol,
            "fact": counter_fact,
            "source": "independent",
        }
    )
    store.insert_link(
        {
            "claim_id": f"bclm_{symbol.lower()}_core",
            "evidence_id": f"rev_{symbol.lower()}_support",
            "direction": "support",
            "strength": "strong",
            "reason": "Primary support for the live claim.",
        }
    )
    store.insert_link(
        {
            "claim_id": f"bclm_{symbol.lower()}_core",
            "evidence_id": f"rev_{symbol.lower()}_counter",
            "direction": "oppose",
            "strength": "medium",
            "reason": "Strongest persisted counter.",
        }
    )
    store.insert_link(
        {
            "claim_id": f"bclm_{symbol.lower()}_core",
            "evidence_id": f"rev_{symbol.lower()}_support",
            "direction": "support",
            "strength": "weak",
            "reason": "Weaker echo of the same support.",
        }
    )
    store.insert_version(
        {
            "claim_id": f"bclm_{symbol.lower()}_core",
            "version": 1,
            "old_status": "strongly_supported",
            "new_status": "challenged",
            "status": "challenged",
            "reason_for_change": "Latest print challenged durability.",
            "created_at": "2026-09-04T00:00:00+00:00",
        }
    )
    store.insert_history(
        {
            "ticker": symbol,
            "object_type": "company_state",
            "object_id": f"bst_{symbol.lower()}_demand",
            "from_payload": {"name": f"{symbol} demand state", "statement": f"{symbol} demand is elevated.", "confidence": "low"},
            "to_payload": {"name": f"{symbol} demand state", "statement": f"{symbol} demand is elevated and named.", "confidence": "medium"},
            "reason": "State updated after the latest print.",
            "created_at": "2026-09-10T00:00:00+00:00",
        }
    )
    store.insert_history(
        {
            "ticker": symbol,
            "object_type": "value_driver",
            "object_id": f"bdrv_{symbol.lower()}_demand",
            "from_payload": {"name": "Demand durability", "current_state": "unclear"},
            "to_payload": {"name": "Demand durability", "current_state": f"{symbol} demand remains the live driver."},
            "reason": "Driver state rewritten from evidence.",
            "created_at": "2026-09-11T00:00:00+00:00",
        }
    )
    store.insert_history(
        {
            "ticker": symbol,
            "object_type": "expectation",
            "object_id": f"bexpc_{symbol.lower()}",
            "from_payload": {"name": "EPS vs consensus", "actual": "in line", "expected": "beat", "comparison": "in_line"},
            "to_payload": {"name": "EPS vs consensus", "actual": "miss", "expected": "beat", "comparison": "below"},
            "reason": "Print missed the number the market was trading.",
            "created_at": "2026-09-12T00:00:00+00:00",
        }
    )
    store.insert_history(
        {
            "ticker": symbol,
            "object_type": "core_claim",
            "object_id": f"bclm_{symbol.lower()}_core",
            "from_payload": {"title": claim_title, "status": "strongly_supported", "statement": "holds"},
            "to_payload": {"title": claim_title, "status": "challenged", "statement": f"{claim_title} is the live core claim."},
            "reason": "Claim status moved after the miss.",
            "created_at": "2026-09-13T00:00:00+00:00",
        }
    )
    store.insert_history(
        {
            "ticker": symbol,
            "object_type": "company_state",
            "object_id": f"bst_{symbol.lower()}_demand",
            "from_payload": {"statement": "same", "confidence": "medium", "updated_at": "t1"},
            "to_payload": {"statement": "same", "confidence": "medium", "updated_at": "t2"},
            "reason": "timestamp-only write must not appear as a real change.",
            "created_at": "2026-09-14T00:00:00+00:00",
        }
    )
    store.insert_event(
        {
            "ticker": symbol,
            "event_id": f"bev_{symbol.lower()}_latest",
            "event_type": "earnings",
            "title": f"{symbol} latest print missed EPS while revenue stayed strong.",
            "event_date": "2026-09-12",
            "fact_reliability": "reported",
            "materiality": "material",
            "transmission": {
                "successful": [
                    {
                        "nodes": [f"bst_{symbol.lower()}_demand", f"bdrv_{symbol.lower()}_demand", f"bclm_{symbol.lower()}_core"],
                    }
                ]
            },
        }
    )
    store.insert_exposure(
        {
            "ticker": symbol,
            "event_id": f"bev_{symbol.lower()}_latest",
            "subject": symbol,
            "object_name": "Named customer demand",
            "mechanism": f"{symbol} converts the print into the demand driver.",
            "related_driver_id": f"bdrv_{symbol.lower()}_demand",
            "related_claim_id": f"bclm_{symbol.lower()}_core",
            "can_affect_claim": True,
        }
    )
    store.upsert_expectation(
        {
            "ticker": symbol,
            "name": "EPS vs consensus",
            "actual": "miss",
            "expected": "beat",
            "comparison": "below",
            "trend": "deteriorating",
            "last_material_change": "EPS missed after the market had priced a beat.",
        }
    )
    store.upsert_hypothesis(
        {
            "ticker": symbol,
            "canonical_key": "duration_reprice",
            "hypothesis": "The tape is trading duration risk, not the revenue print.",
            "status": "active",
            "confidence": "medium",
        }
    )
    store.upsert_hypothesis(
        {
            "ticker": symbol,
            "canonical_key": "old_multiple",
            "hypothesis": "Retired multiple story.",
            "status": "retired",
        }
    )
    store.upsert_divergence(
        {
            "ticker": symbol,
            "signature": f"{symbol}-unexplained-drop",
            "status": "open",
            "explanation_grade": "largely_unexplained",
            "direction": "down",
            "price_change_pct": -5.1,
            "unresolved_question": "Why did price fall more than the EPS miss explains?",
            "as_of": "2026-09-12",
        }
    )
    store.insert_question(
        {
            "ticker": symbol,
            "question": f"Can we confirm whether {symbol} demand is duration or a pull-forward?",
            "why_it_matters": "This is the next fact that would hold or kill the core claim.",
            "priority": "high",
            "status": "open",
            "related_claim_id": f"bclm_{symbol.lower()}_core",
        }
    )
    store.insert_question(
        {
            "ticker": symbol,
            "question": "Closed question must not appear.",
            "status": "closed",
        }
    )


def test_empty_brain_does_not_invent_claims() -> None:
    snapshot = build_pm_view(BrainStore(), "LITE")
    assert snapshot["llm_invoked"] is False
    assert snapshot["source"] == "persisted_brain"
    assert snapshot["core_claims"] == []
    assert snapshot["what_changed"] == []
    assert snapshot["open_research_questions"] == []
    assert snapshot["market_view"]["active_hypotheses"] == []
    assert snapshot["now_chain"]["answers"]["what_happened"]


def test_pm_view_reads_persisted_brain_for_avgo_and_lite() -> None:
    store = BrainStore()
    _seed_ticker(
        store,
        "AVGO",
        claim_title="AI revenue durability",
        support_fact="AI accelerator demand continues to be very strong.",
        counter_fact="EPS missed consensus for a third quarter.",
    )
    _seed_ticker(
        store,
        "LITE",
        claim_title="Datacom transceiver ramp",
        support_fact="Cloud transceivers grew 40% sequentially.",
        counter_fact="GAAP EPS 1.50 missed 1.81.",
    )
    avgo = build_pm_view(store, "AVGO")
    lite = build_pm_view(store, "LITE")
    assert avgo["llm_invoked"] is False
    assert lite["llm_invoked"] is False
    assert [row["title"] for row in avgo["core_claims"]] == ["AI revenue durability"]
    assert [row["title"] for row in lite["core_claims"]] == ["Datacom transceiver ramp"]
    assert avgo["core_claims"][0]["status"] == "challenged"
    assert avgo["core_claims"][0]["strongest_support"]["fact"] == "AI accelerator demand continues to be very strong."
    assert avgo["core_claims"][0]["strongest_support"]["strength"] == "strong"
    assert avgo["core_claims"][0]["strongest_counter"]["fact"] == "EPS missed consensus for a third quarter."
    assert avgo["core_claims"][0]["recent_change"]["from_status"] == "strongly_supported"
    assert avgo["core_claims"][0]["recent_change"]["to_status"] == "challenged"
    families = {row["family"] for row in avgo["what_changed"]}
    assert families == {"State", "Driver", "Expectation", "Claim"}
    assert all(row["deltas"] for row in avgo["what_changed"])
    assert "timestamp-only" not in " ".join(row.get("reason") or "" for row in avgo["what_changed"])
    assert avgo["now_chain"]["answers"]["what_happened"].startswith("AVGO latest print")
    assert "demand driver" in avgo["now_chain"]["answers"]["why_it_affects_company"]
    assert avgo["market_view"]["expectations"][0]["comparison"] == "below"
    assert [row["canonical_key"] for row in avgo["market_view"]["active_hypotheses"]] == ["duration_reprice"]
    assert avgo["market_view"]["price_divergence"]["latest"]["status"] == "open"
    assert lite["open_research_questions"][0]["question"].startswith("Can we confirm whether LITE")
    assert "Closed question" not in " ".join(row["question"] for row in lite["open_research_questions"])
    assert all(pm_questions_answerable(avgo).values())
    assert all(pm_questions_answerable(lite).values())


def test_pm_view_does_not_call_run_brain(monkeypatch) -> None:
    store = BrainStore()
    _seed_ticker(
        store,
        "AVGO",
        claim_title="AI revenue durability",
        support_fact="AI accelerator demand continues to be very strong.",
        counter_fact="EPS missed consensus for a third quarter.",
    )

    def boom(*args, **kwargs):
        raise AssertionError("PM View must not re-run Brain")

    monkeypatch.setattr("stock_pm.brain.pipeline.run_brain", boom)
    monkeypatch.setattr("stock_pm.brain.runtime.run_brain_update", boom)
    snapshot = build_pm_view(store, "AVGO")
    assert snapshot["core_claims"]


def test_pm_view_http_and_page(monkeypatch) -> None:
    store = BrainStore()
    _seed_ticker(
        store,
        "AVGO",
        claim_title="AI revenue durability",
        support_fact="AI accelerator demand continues to be very strong.",
        counter_fact="EPS missed consensus for a third quarter.",
    )
    research = ResearchService(store=InMemoryResearchStore())
    brain_api._override = {"research": research, "store": store}
    client = TestClient(api.app)
    page = client.get("/brain/AVGO")
    assert page.status_code == 200
    assert "brain.js" in page.text
    assert "PM View" in page.text
    payload = client.get("/api/brain/AVGO/pm-view")
    assert payload.status_code == 200
    body = payload.json()
    assert body["source"] == "persisted_brain"
    assert body["llm_invoked"] is False
    assert body["core_claims"][0]["title"] == "AI revenue durability"
    assert body["can_answer"]["investment_logic"] is True
    lite = client.get("/api/brain/LITE/pm-view")
    assert lite.status_code == 200
    assert lite.json()["core_claims"] == []
    brain_api._override = None


def _hydrate_artifact(store: BrainStore, ticker: str, payload: dict) -> None:
    symbol = ticker.upper()
    for row in payload.get("states") or []:
        store.insert_state({**row, "ticker": symbol, "state_type": row.get("state_type") or "company"})
    for row in payload.get("drivers") or []:
        store.insert_driver({**row, "ticker": symbol})
    for row in payload.get("claims") or []:
        store.insert_claim({**row, "ticker": symbol})
    for row in payload.get("exposures") or []:
        store.insert_exposure({**row, "ticker": symbol})
    for row in payload.get("expectations") or []:
        store.upsert_expectation({**row, "ticker": symbol})
    for row in payload.get("hypotheses") or []:
        store.upsert_hypothesis({**row, "ticker": symbol})
    for row in payload.get("divergences") or []:
        store.upsert_divergence({**row, "ticker": symbol})
    for row in payload.get("questions") or []:
        store.insert_question({**row, "ticker": symbol, "status": row.get("status") or "open"})
    for row in payload.get("attentions") or []:
        store.upsert_market_attention({**row, "ticker": symbol})


def test_avgo_artifact_answers_four_pm_questions() -> None:
    payload = json.loads(AVGO_ARTIFACT.read_text())
    store = BrainStore()
    _hydrate_artifact(store, "AVGO", payload)
    snapshot = build_pm_view(store, "AVGO")
    assert snapshot["llm_invoked"] is False
    titles = [row["title"] for row in snapshot["core_claims"]]
    assert any("durability" in (title or "").lower() for title in titles)
    assert 3 <= len(snapshot["core_claims"]) <= 5
    assert snapshot["market_view"]["expectations"]
    assert snapshot["market_view"]["active_hypotheses"]
    assert any("AI" in (row["hypothesis"] or "") for row in snapshot["market_view"]["active_hypotheses"])
    assert snapshot["open_research_questions"]
    assert any("sustainable" in (row["question"] or "").lower() for row in snapshot["open_research_questions"])
    coverage = pm_questions_answerable(snapshot)
    assert coverage["investment_logic"] is True
    assert coverage["what_changed"] is True
    assert coverage["market"] is True
    assert coverage["next_verify"] is True
