from __future__ import annotations

from datetime import datetime, timezone

from stock_pm.brain.claim_integrity import (
    check_pm_consistency,
    classify_source_relationship,
    default_counter_queries,
    derive_claim_identity,
    freeze_evidence_set,
    is_fact_restatement,
    is_material_change,
    links_from_reasoning,
    make_claim_key,
    match_existing_claim,
    news_is_duplicate,
    reconcile_status,
    reject_unknown_ids,
    strip_unbound_facts,
)
from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource

from test_brain_phase1 import FakeBrainCompleter, _pack, _seed_evidence, _service


STAMP = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc).isoformat()


def test_claim_cannot_cite_evidence_outside_frozen_set() -> None:
    allowed = {"rev_in_set"}
    kept, rejected = reject_unknown_ids(["rev_in_set", "rev_outside"], allowed)
    assert kept == ["rev_in_set"]
    assert rejected == ["rev_outside"]
    links, rejected_links = links_from_reasoning(
        {
            "evidence_links": [
                {
                    "evidence_id": "rev_outside",
                    "direction": "support",
                    "strength": "strong",
                    "relevance": "direct",
                    "proves": "x",
                    "does_not_prove": "y",
                }
            ]
        },
        claim={"claim_id": "bclm_1", "supporting_evidence_ids": ["rev_outside"]},
        evidence_by_id={},
        allowed=allowed,
        ticker="ZZZT",
        related_entities=[],
        run_id="brun_1",
        claim_version_id="bclv_1",
    )
    assert links == []
    assert "rev_outside" in rejected_links


def test_unsupported_number_downgrades_status() -> None:
    statement = "AI semiconductors reached $21.7B / +236% and that run-rate is durable."
    stripped = strip_unbound_facts(
        statement,
        [{"fact": "Management indicates further AI semiconductor acceleration", "excerpt": "further AI semiconductor acceleration"}],
    )
    assert stripped["stripped"] is True
    assert any("21.7" in token or "236" in token for token in stripped["unsupported_tokens"])
    recon = reconcile_status(
        claim={
            "proposed_status": "strongly_supported",
            "statement": stripped["statement"],
            "claim_dimension": "growth_duration",
        },
        links=[
            {
                "direction": "support",
                "strength": "strong",
                "relevance": "direct",
                "source_relationship": "issuer_primary",
                "proves": "management described acceleration",
                "does_not_prove": "the 21.7B figure",
            }
        ],
        evidence_by_id={"rev_1": {"source_relationship": "issuer_primary"}},
        unsupported_tokens=stripped["unsupported_tokens"],
    )
    assert recon["final_status"] in {"unverified", "partially_supported"}
    assert recon["final_status"] != "strongly_supported"


def test_no_counter_evidence_is_not_no_counter_search() -> None:
    queries = default_counter_queries(
        {"claim_subject": "ai_custom_silicon", "financial_driver": "revenue", "statement": "AI growth duration", "counter_research_questions": []},
        "AVGO",
    )
    assert len(queries) >= 2
    payload = {
        "counter_search_performed": True,
        "counter_queries": queries,
        "counter_evidence_found": False,
        "counter_evidence_ids": [],
    }
    assert payload["counter_search_performed"] is True
    assert payload["counter_evidence_found"] is False


def test_title_change_keeps_claim_id() -> None:
    first = derive_claim_identity(
        {
            "title": "AI custom silicon duration",
            "statement": "Custom silicon growth can persist into the medium term.",
            "claim_subject": "ai_custom_silicon",
            "financial_driver": "revenue",
            "claim_dimension": "growth_duration",
            "time_horizon": "medium",
        },
        ticker="AVGO",
    )
    second = derive_claim_identity(
        {
            "title": "Will AI ASICs keep growing?",
            "statement": "Custom silicon growth can persist into the medium term.",
            "claim_subject": "ai_custom_silicon",
            "financial_driver": "revenue",
            "claim_dimension": "growth_duration",
            "time_horizon": "medium",
        },
        ticker="AVGO",
    )
    assert first["claim_key"] == second["claim_key"]
    existing = [{"claim_id": "bclm_keep", "claim_key": first["claim_key"], "lifecycle": "core", "title": "old title", "statement": "Custom silicon growth can persist into the medium term.", "claim_subject": "ai_custom_silicon", "financial_driver": "revenue", "claim_dimension": "growth_duration"}]
    match = match_existing_claim({**second, "title": "Will AI ASICs keep growing?"}, existing)
    assert match["action"] == "update_existing"
    assert match["claim"]["claim_id"] == "bclm_keep"


def test_material_change_creates_new_version_duplicate_news_does_not() -> None:
    old = {
        "statement": "Demand duration remains the binding variable.",
        "status": "partially_supported",
        "confidence": "medium",
        "supporting_evidence_ids": ["rev_1"],
        "opposing_evidence_ids": [],
    }
    same = dict(old)
    same["statement"] = "Demand duration remains the binding variable for earnings."
    assert is_material_change(old, same)["material"] is False
    changed = dict(old)
    changed["status"] = "challenged"
    changed["opposing_evidence_ids"] = ["rev_counter"]
    assert is_material_change(old, changed)["material"] is True
    assert news_is_duplicate(
        {"title": "Demand remained strong", "snippet": "Management said demand remained strong in the latest quarter."},
        ["Management said demand remained strong in the latest quarter."],
    )


def test_pm_cannot_cite_unsupported_claim_fact() -> None:
    claims = [
        {
            "claim_id": "bclm_1",
            "final_status": "unverified",
            "status": "unverified",
            "statement": "Demand is the debate.",
            "reasoning": {"current_conclusion": "The $21.7B figure cannot be verified"},
        }
    ]
    check = check_pm_consistency(
        {
            "strongest_claim_id": "bclm_1",
            "weakest_claim_id": "bclm_1",
            "current_view": "AI revenue already printed $21.7B so the claim is strongest.",
        },
        claims,
        evidence_by_id={"rev_1": {"fact": "Management indicates further AI semiconductor acceleration"}},
    )
    assert check["passed"] is False
    assert check["status"] == "inconsistent"
    assert any("strongest claim" in row or "unbound" in row or "unsupported" in row for row in check["reasons"])


def test_source_relationship_is_independent_of_tier() -> None:
    assert classify_source_relationship({"source": "sec.companyfacts", "source_type": "earnings_release"}, ticker="AVGO") == "issuer_primary"
    assert classify_source_relationship({"source_url": "https://www.reuters.com/markets/avgo", "source": "reuters"}, ticker="AVGO") == "independent_media"
    assert classify_source_relationship({"source_url": "https://stockanalysis.com/avgo", "source": "stockanalysis"}, ticker="AVGO") == "aggregator"
    assert classify_source_relationship({"source_url": "https://www.sec.gov/Archives/edgar/data/meta-10q", "source": "sec.gov", "source_type": "sec_filing", "raw_reference": {"query_type": "related_entity", "entity": "Meta"}}, ticker="AVGO") in {"related_entity_primary", "issuer_primary"}
    assert classify_source_relationship({"source_url": "https://www.coherent.com/investors/10-q", "source_type": "sec_filing"}, ticker="LITE") in {"industry_peer", "related_entity_primary"}


def test_fact_restatement_is_not_core() -> None:
    assert is_fact_restatement("Revenue grew 12% in the latest quarter")
    assert not is_fact_restatement("Services earnings quality depends on App Store economics remaining intact.")


def test_claim_key_stable_across_wording() -> None:
    left = make_claim_key("AAPL", claim_subject="services_mix", financial_driver="revenue", claim_dimension="growth_duration", time_horizon="medium")
    right = make_claim_key("AAPL", claim_subject="services_mix", financial_driver="revenue", claim_dimension="growth_duration", time_horizon="medium")
    assert left == right
    other = make_claim_key("AAPL", claim_subject="hardware_demand", financial_driver="revenue", claim_dimension="growth_duration", time_horizon="medium")
    assert left != other


def test_frozen_set_rejects_full_store_dump() -> None:
    frozen = freeze_evidence_set(
        ticker="AAPL",
        intel={
            "evidence_set": {
                "top_primary_facts": [{"id": "rev_sec", "fact": "10-Q revenue", "source_url": "https://www.sec.gov/a"}],
            }
        },
        store_evidence=[
            {"id": "rev_sec", "fact": "10-Q revenue", "source_url": "https://www.sec.gov/a", "source": "sec.gov", "source_type": "sec_filing"},
            {"id": "rev_fmp", "fact": "FMP print", "source": "fmp", "source_url": "https://financialmodelingprep.com/aapl"},
        ],
    )
    assert "rev_sec" in frozen["reasoning_allowed_ids"]
    assert "rev_fmp" not in frozen["reasoning_allowed_ids"]


def test_pipeline_same_claim_id_across_runs_and_counter_search(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
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
                "query": kwargs.get("extra_queries")[0] if kwargs.get("extra_queries") else "ZZZT demand",
            }
        ],
    )
    store = BrainStore()
    first = run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    assert first["claims"]
    claim = first["claims"][0]
    assert claim.get("counter_search", {}).get("counter_search_performed") is True
    assert "counter_evidence_found" in (claim.get("counter_search") or {})
    assert claim.get("final_status") or claim.get("status")
    links = store.list_links(claim_id=claim["claim_id"])
    assert links
    assert all(row.get("proves") for row in links if row.get("direction") == "support")
    first_id = claim["claim_id"]
    first_versions = len(store.list_versions(first_id))
    second = run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    assert second["claims"][0]["claim_id"] == first_id
    assert second["claims"][0].get("match_action") in {"update_existing", "merge_into_existing"}
    assert len(store.list_versions(first_id)) == first_versions


class TitleChanger(FakeBrainCompleter):
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        result = super().complete_json(system=system, user=user, schema=schema)
        if "STEP_ID: core_claims" in system and result.get("payload"):
            result["payload"]["core"][0]["title"] = "Demand durability, not the print"
            result["payload"]["candidates"][0]["title"] = "Demand durability, not the print"
        return result


def test_pipeline_title_change_does_not_mint_new_claim(monkeypatch) -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    first_completer = FakeBrainCompleter()
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=first_completer)
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    first = run_brain(svc, "ZZZT", store=store, completer=first_completer, fetch_live=False)
    claim_id = first["claims"][0]["claim_id"]
    changer = TitleChanger()
    second = run_brain(svc, "ZZZT", store=store, completer=changer, fetch_live=False)
    assert second["claims"][0]["claim_id"] == claim_id
    assert second["claims"][0]["title"] == "Demand durability, not the print"


class MaterialChanger(FakeBrainCompleter):
    def __init__(self) -> None:
        super().__init__()
        self.core_calls = 0

    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        result = super().complete_json(system=system, user=user, schema=schema)
        if "STEP_ID: core_claims" in system and result.get("payload"):
            self.core_calls += 1
            if self.core_calls > 1:
                text = "Customer concentration now threatens the duration of demand, not just the latest print."
                result["payload"]["core"][0]["statement"] = text
                result["payload"]["candidates"][0]["statement"] = text
                result["payload"]["core"][0]["claim_dimension"] = "growth_duration"
                result["payload"]["core"][0]["claim_subject"] = "demand_duration"
        return result


def test_pipeline_material_change_adds_version(monkeypatch) -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    completer = MaterialChanger()
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=completer)
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    first = run_brain(svc, "ZZZT", store=store, completer=completer, fetch_live=False)
    claim_id = first["claims"][0]["claim_id"]
    before = len(store.list_versions(claim_id))
    second = run_brain(svc, "ZZZT", store=store, completer=completer, fetch_live=False)
    assert second["claims"][0]["claim_id"] == claim_id
    assert len(store.list_versions(claim_id)) == before + 1
    latest = store.list_versions(claim_id)[-1]
    assert latest.get("old_statement")
    assert latest.get("new_statement")
    assert latest.get("reason_for_change")


class UnsupportedPmCompleter(FakeBrainCompleter):
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        result = super().complete_json(system=system, user=user, schema=schema)
        if "STEP_ID: pm_synthesis" in system and result.get("payload"):
            result["payload"]["current_view"] = "Treat the unverified $21.7B / +236% print as the strongest fact."
        return result


def test_pipeline_pm_blocks_unsupported_number(monkeypatch) -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    completer = UnsupportedPmCompleter()
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=completer)
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    result = run_brain(svc, "ZZZT", store=BrainStore(), completer=completer, fetch_live=False)
    assert result["pm_synthesis"]["status"] == "inconsistent"
    assert result["pm_consistency"]["passed"] is False
    assert any(item.get("code") == "pm_inconsistency_blocked" for item in result["integrity_violations"])
