from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.header import company_header
from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.quality import assess_brain_quality
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource


STAMP = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc).isoformat()


def _pack() -> dict:
    return {
        "ticker": "ZZZT",
        "template_id": "semiconductor",
        "is_fixture": True,
        "source": "fixture",
        "company_profile": {
            "legal_name": "Test Co",
            "sector": "半导体",
            "revenue_ttm": 10_000_000_000,
            "eps_ttm": 2.5,
            "last_close": 40.0,
            "pe_ttm": 16.0,
            "market_cap": 80_000_000_000,
            "gross_margin_pct": 60.0,
            "operating_margin_pct": 30.0,
            "net_margin_pct": 20.0,
            "recent_closes": [{"session_date": "2026-09-15", "close": 40.0}],
        },
        "earnings_history": [
            {"report_date": "2026-09-01", "revenue": 3_000_000_000, "eps": 0.7, "gross_margin_pct": 61, "operating_margin_pct": 31, "source": "sec.companyfacts"},
            {"report_date": "2026-06-01", "revenue": 2_800_000_000, "eps": 0.6},
            {"report_date": "2026-03-01", "revenue": 2_600_000_000, "eps": 0.55},
            {"report_date": "2025-12-01", "revenue": 2_400_000_000, "eps": 0.5},
            {"report_date": "2025-09-01", "revenue": 2_200_000_000, "eps": 0.45},
        ],
        "guidance_history": [{"text": "expects continued demand", "source": "transcript"}],
        "missing_fields": ["fcf", "segment_growth"],
    }


class FakeBrainCompleter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        text = user.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            payload, _end = json.JSONDecoder().raw_decode(text[start:])
        self.calls.append("company_understanding" if "STEP_ID: company_understanding" in system else system.split("STEP_ID:")[-1].split()[0] if "STEP_ID:" in system else "unknown")
        evidence = payload.get("evidence") or []
        eids = [str(row.get("id")) for row in evidence if row.get("id")]
        news = payload.get("news") or []
        claims = payload.get("claims") or payload.get("core_claims") or []
        if "STEP_ID: company_understanding" in system:
            body = {
                "how_company_makes_money": "Sells semiconductor products.",
                "largest_growth_driver": "Demand durability in the current cycle.",
                "largest_operating_risk": "Mix and margin.",
                "value_variables_1to3y": ["demand duration"],
                "candidate_questions": ["Does demand persist?"],
                "search_questions_last_7d": ["ZZZT demand"],
                "states": [
                    {
                        "name": "demand",
                        "statement": "Demand is the binding variable",
                        "direction": "watch",
                        "confidence": "medium",
                        "state_type": "company",
                        "evidence_ids": eids[:1],
                    }
                ],
                "coverage_gaps": ["fcf"],
                "cannot_conclude": [],
            }
        elif "STEP_ID: core_claims" in system:
            eid = eids[0] if eids else None
            body = {
                "candidates": [
                    {
                        "title": "Demand duration",
                        "statement": "Near-term demand remains the binding earnings variable.",
                        "claim_type": "operating",
                        "why_it_matters": "It changes the 1-3y earnings path.",
                        "supporting_evidence_ids": [eid] if eid else [],
                        "opposing_evidence_ids": [],
                        "missing_evidence": ["independent customer confirmation"],
                        "value_impact": "high",
                        "uncertainty": "high",
                        "valuation_relevance": "high",
                        "persistence": "medium",
                        "testability": "high",
                    }
                ],
                "core": [
                    {
                        "title": "Demand duration",
                        "statement": "Near-term demand remains the binding earnings variable.",
                        "claim_type": "operating",
                        "status": "partially_supported",
                        "importance": "high",
                        "confidence": "medium",
                        "time_horizon": "medium",
                        "why_it_matters": "It changes the 1-3y earnings path.",
                        "why_core": "Highest value impact times uncertainty.",
                        "uncertainty": "high",
                        "valuation_relevance": "high",
                        "supporting_evidence_ids": [eid] if eid else [],
                        "opposing_evidence_ids": [],
                        "missing_evidence": ["independent customer confirmation"],
                    }
                ],
                "rejected": [{"title": "headline noise", "why_not_core": "not persistent"}],
                "insufficient_reason": None if eid else "no evidence",
            }
        elif "STEP_ID: news_interpretation" in system:
            claim_id = (claims[0] or {}).get("claim_id") if claims else None
            news0 = news[0] if news else {}
            body = {
                "items": [
                    {
                        "news_index": 0,
                        "evidence_id": news0.get("evidence_id"),
                        "layer": "material",
                        "new_fact": "A high-quality source reported a demand update.",
                        "source_credibility": "high",
                        "novelty": "new",
                        "affected_claim_id": claim_id,
                        "impact": "support",
                        "changes_claim_status": True,
                        "financial_impact": "qualitative_positive",
                        "quantifiable": False,
                        "quantifiable_reason": "no units",
                        "reason": "The item is new and maps to the demand claim.",
                        "new_research_question": "Is the demand incremental to existing contracts?",
                    }
                ]
            }
        elif "STEP_ID: claim_reasoning" in system:
            claim = payload.get("claim") or {}
            eids = [str(row.get("id")) for row in (payload.get("evidence") or []) if row.get("id")]
            body = {
                "claim_id": claim.get("claim_id"),
                "current_conclusion": claim.get("statement"),
                "why_important": "It binds earnings power.",
                "strongest_support_evidence_ids": eids[:1],
                "strongest_opposing_evidence_ids": [],
                "evidence_boundary": {"proves": "sourced demand language exists", "does_not_prove": "a named incremental contract"},
                "competing_hypotheses": [{"statement": "The print was a pull-forward", "status": "speculative", "evidence_ids": []}],
                "missing_evidence": ["independent customer confirmation"],
                "what_strengthens": ["customer 10-Q naming the issuer"],
                "what_weakens": ["guidance cut"],
                "what_invalidates": ["contract cancellation"],
                "next_research_question": "Which customer 10-Q, if any, names this issuer?",
            }
        elif "STEP_ID: pm_synthesis" in system:
            ids = [str(row.get("claim_id")) for row in claims if row.get("claim_id")]
            body = {
                "current_view": "Demand duration is the live debate; FCF is still missing.",
                "core_claim_ids": ids,
                "decisive_variables": [{"name": "demand duration", "why": "binds earnings", "evidence_ids": eids[:1]}],
                "strongest_claim_id": ids[0] if ids else "",
                "weakest_claim_id": ids[0] if ids else "",
                "what_changed_last_7d": ["material demand update"],
                "most_likely_wrong": "Treating industry demand as issuer-specific.",
                "next_information_to_seek": "named customer confirmation",
                "short_view": "next print vs outlook",
                "mid_view": "whether demand converts",
                "long_view": "duration after the current wave",
                "cannot_conclude": [],
            }
        else:
            body = {}
        return {
            "status": "ok",
            "payload": body,
            "model": "fake-brain",
            "provider": "test",
            "llm_called": True,
            "llm_status": "ok",
            "fallback_used": False,
            "input_tokens": 10,
            "output_tokens": 20,
            "latency_ms": 5,
        }


class SilentCompleter:
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        return {"status": "missing_key", "payload": None, "llm_called": False, "llm_status": "skipped", "error": "missing key"}


def _service() -> ResearchService:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=FakeBrainCompleter())
    svc.store.upsert_pack(_pack())
    return svc


def _seed_evidence(svc: ResearchService) -> str:
    row = svc.create_evidence(
        "ZZZT",
        {
            "evidence_type": "filing",
            "fact": "Management said demand remained strong in the latest quarter.",
            "excerpt": "demand remained strong",
            "source": "sec.gov",
            "source_url": "https://www.sec.gov/Archives/test",
            "source_time": STAMP,
            "retrieved_at": STAMP,
            "source_type": "sec_filing",
        },
        actor="test",
    )
    return str(row["id"])


def test_header_numbers_come_from_pack_not_llm() -> None:
    header = company_header(_pack())
    assert header["price"]["value"] == 40.0
    assert header["price"]["origin"] == "reported"
    assert header["growth"]["revenue_ttm"]["value"] == 10_000_000_000
    assert header["forward"]["consensus"]["origin"] == "unavailable"
    assert header["latest_quarter"]["fcf"]["origin"] == "unavailable"


def test_brain_run_calls_llm_and_grounds_claims(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    eid = _seed_evidence(svc)
    monkeypatch.setattr(
        "stock_pm.brain.pipeline.search_recent_news",
        lambda *args, **kwargs: [
            {
                "title": "Demand update",
                "url": "https://www.reuters.com/test-demand",
                "snippet": "A high-quality source reported a demand update.",
                "source": "reuters.com",
                "published_at": STAMP,
                "query": "ZZZT demand",
            }
        ],
    )
    store = BrainStore()
    result = run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    assert result["audit"]["llm_invoked"] is True
    assert result["audit"]["core_claim_count"] == 1
    claim = result["claims"][0]
    links = store.list_links(claim_id=claim["claim_id"])
    support_ids = [row["evidence_id"] for row in links if row["direction"] == "support"]
    assert eid in support_ids or any(item.startswith("rev_") for item in support_ids)
    assert all(row.get("evidence_id") for row in links)
    news = result["news"]
    assert news
    assert news[0]["layer"] == "material"
    assert news[0].get("evidence_id")
    versions = store.list_versions(claim["claim_id"])
    assert len(versions) >= 2
    assert news[0]["claim_version_changed"] is True
    assert result["pm_synthesis"]["current_view"]
    assert result["quality"]["axes"]["llm_reasoning"] in {"Good", "Partial"}


def test_missing_llm_does_not_invent_core_claims(monkeypatch) -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=SilentCompleter())
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT", legal_name="Test Co")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    result = run_brain(svc, "ZZZT", store=BrainStore(), completer=SilentCompleter(), fetch_live=False)
    assert result["claims"] == []
    assert result["quality"]["axes"]["llm_reasoning"] == "Poor"
    assert any("BRAIN QUALITY WARNING" in str(item) for item in result["quality"]["warnings"])
    assert result["pm_synthesis"]["current_view"].startswith("LLM")


def test_unknown_evidence_ids_cannot_become_core(monkeypatch) -> None:
    class InventingCompleter(FakeBrainCompleter):
        def complete_json(self, *, system: str, user: str, schema=None) -> dict:
            result = super().complete_json(system=system, user=user, schema=schema)
            if "STEP_ID: core_claims" in system:
                result["payload"]["core"][0]["supporting_evidence_ids"] = ["rev_does_not_exist"]
                result["payload"]["candidates"][0]["supporting_evidence_ids"] = ["rev_does_not_exist"]
            return result

    source = DictPackSource.from_mapping("ZZZT", _pack())
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=InventingCompleter())
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    result = run_brain(svc, "ZZZT", store=BrainStore(), completer=InventingCompleter(), fetch_live=False)
    assert result["claims"] == []


def test_quality_poor_when_no_news_or_llm() -> None:
    header = company_header(_pack())
    quality = assess_brain_quality(header=header, evidence=[], news=[], claims=[], llm_calls=[], pack=_pack())
    assert quality["axes"]["llm_reasoning"] == "Poor"
    assert quality["axes"]["news_coverage"] == "Poor"


def test_quality_partial_when_only_undated_sec_index() -> None:
    header = company_header(_pack())
    quality = assess_brain_quality(
        header=header,
        evidence=[{"id": "rev_1", "source": "sec.gov", "source_url": "https://www.sec.gov/x", "fact": "10-Q"}],
        news=[{"title": "10-Q", "url": "https://www.sec.gov/Archives/test", "source": "sec"}],
        claims=[],
        llm_calls=[],
        pack=_pack(),
    )
    assert quality["axes"]["news_coverage"] == "Poor"
    assert any("Reuters" in str(item.get("reason")) or "last-7-day" in str(item.get("reason")) for item in quality["warnings"])


def test_uninterpreted_news_keeps_evidence_id(monkeypatch) -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=SilentCompleter())
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT")
    _seed_evidence(svc)
    monkeypatch.setattr(
        "stock_pm.brain.pipeline.search_recent_news",
        lambda *args, **kwargs: [
            {
                "title": "Demand update",
                "url": "https://www.reuters.com/test-demand",
                "snippet": "A high-quality source reported a demand update.",
                "source": "reuters.com",
                "published_at": STAMP,
                "query": "ZZZT demand",
            }
        ],
    )
    result = run_brain(svc, "ZZZT", store=BrainStore(), completer=SilentCompleter(), fetch_live=False)
    assert result["news"]
    assert result["news"][0].get("evidence_id")
    assert result["news"][0]["layer"] == "uninterpreted"


def test_brain_pages_and_json(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    store = BrainStore()
    monkeypatch.setattr(
        "stock_pm.brain.pipeline.search_recent_news",
        lambda *args, **kwargs: [
            {
                "title": "Demand update",
                "url": "https://www.reuters.com/test-demand",
                "snippet": "A high-quality source reported a demand update.",
                "source": "reuters.com",
                "published_at": STAMP,
                "query": "ZZZT demand",
            }
        ],
    )
    run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    brain_api._override = {"research": svc, "store": store}
    client = TestClient(api.app)
    page = client.get("/brain/ZZZT")
    assert page.status_code == 200
    assert "brain.js" in page.text
    payload = client.get("/api/brain/ZZZT")
    assert payload.status_code == 200
    body = payload.json()
    assert body["header"]["growth"]["revenue_ttm"]["value"] == 10_000_000_000
    assert body["core_claims"]
    claim_id = body["core_claims"][0]["claim_id"]
    detail = client.get(f"/api/brain/ZZZT/claims/{claim_id}")
    assert detail.status_code == 200
    assert detail.json()["history"]
    ev_id = body["core_claims"][0]["support_evidence"][0]["id"]
    evidence = client.get(f"/api/brain/ZZZT/evidence/{ev_id}")
    assert evidence.status_code == 200
    claim_page = client.get(f"/brain/ZZZT/claims/{claim_id}")
    assert claim_page.status_code == 200
    brain_api._override = None
