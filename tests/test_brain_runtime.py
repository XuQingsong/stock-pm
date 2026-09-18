from __future__ import annotations

import json

from stock_pm.brain.critic import critic_context, incremental_critic_context
from stock_pm.brain.incremental import critic_should_expand, full_review_reason, should_full_review
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import DEFAULT_RUN_MODE

from test_brain_phase1 import FakeBrainCompleter


class RuntimeFakeCompleter(FakeBrainCompleter):
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        text = user.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            payload, _end = json.JSONDecoder().raw_decode(text[start:])
        if "STEP_ID: event_extract" in system:
            self.calls.append("event_extract")
            item = payload.get("item") or {}
            blob = f"{item.get('title') or ''} {item.get('fact') or ''}".lower()
            rumor = any(token in blob for token in ("unconfirmed", "may reduce", "rumor", "possible"))
            low = any(token in blob for token in ("t-shirt", "no new information", "recap", "appointed"))
            customer = any(token in blob for token in ("customer", "order", "google"))
            body = {
                "fact": item.get("fact") or item.get("title") or "",
                "event": item.get("title") or "",
                "entities": ["Google"] if "google" in blob else ["AVGO"],
                "event_type": "customer" if customer or rumor else item.get("event_type") or "other",
                "novelty": "none" if low else "new",
                "confidence": "low" if rumor else "medium",
                "fact_reliability": "rumor" if rumor else "derived_fact",
                "material": False if low else True,
                "possible_affected": ["google_customer_exposure", "ai_demand", "customer_concentration", "ai_revenue_durability"]
                if customer or rumor
                else [],
                "reason": "fixture extract",
            }
            return _ok(body)
        if "STEP_ID: change_proposals" in system:
            self.calls.append("change_proposals")
            event = payload.get("event") or {}
            snapshot = payload.get("snapshot") or {}
            blob = f"{event.get('title') or ''} {event.get('fact') or ''}".lower()
            rumor = any(token in blob for token in ("unconfirmed", "may reduce", "rumor", "possible")) or str(event.get("fact_reliability") or "") == "rumor"
            claims = snapshot.get("claims") or []
            claim_id = (claims[0] or {}).get("claim_id") if claims else ""
            if rumor:
                body = {
                    "proposals": [
                        {
                            "object_type": "shadow_state",
                            "source_kind": "rumor",
                            "to": {
                                "name": "possible_google_order_reduction",
                                "statement": event.get("fact") or event.get("title"),
                                "confidence": "low",
                                "materiality_if_true": "high",
                            },
                            "reason": "Unconfirmed customer event.",
                        },
                        {
                            "object_type": "research_question",
                            "source_kind": "rumor",
                            "to": {"question": "Can we confirm a Google order reduction?"},
                            "reason": "Need confirmation before touching Current State.",
                        },
                        {
                            "object_type": "company_state",
                            "source_kind": "news",
                            "to": {"statement": "Google is cutting AVGO orders.", "confidence": "low"},
                            "reason": "Invalid direct state write from rumor.",
                        },
                        {
                            "object_type": "core_claim",
                            "object_id": claim_id,
                            "source_kind": "news",
                            "is_core": True,
                            "from": {"status": "strongly_supported", "is_core": True, "statement": "Duration holds."},
                            "to": {"status": "challenged", "is_core": True, "statement": "Duration is broken."},
                            "reason": "Invalid claim jump from rumor.",
                        },
                    ],
                    "questions": [{"question": "Can we confirm a Google order reduction?", "reason": "unconfirmed", "related_objects": ["possible_google_order_reduction"]}],
                }
            else:
                body = {
                    "proposals": [
                        {
                            "object_type": "market_attention",
                            "source_kind": "news",
                            "to": {"statement": "Market attention on Google customer exposure."},
                            "reason": "Material customer event.",
                            "evidence_ids": event.get("evidence_ids") or [],
                        },
                        {
                            "object_type": "core_claim",
                            "object_id": claim_id,
                            "source_kind": "news",
                            "is_core": True,
                            "from": {"status": "strongly_supported", "is_core": True, "statement": "Duration holds."},
                            "to": {"status": "challenged", "is_core": True, "statement": "Duration challenged by customer event."},
                            "reason": "Proposal only; Phase 0 must decide.",
                        },
                    ],
                    "questions": [],
                }
            return _ok(body)
        return super().complete_json(system=system, user=user, schema=schema)


def _ok(body: dict) -> dict:
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


def _seed_brain(store: BrainStore) -> None:
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_id": "bst_google_exposure",
            "state_type": "company",
            "name": "Google customer exposure",
            "statement": "Google is a named custom-silicon customer.",
            "confidence": "medium",
        }
    )
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_id": "bst_unrelated",
            "state_type": "macro",
            "name": "Rates backdrop",
            "statement": "Rates are a background macro state.",
            "confidence": "medium",
        }
    )
    store.insert_driver(
        {
            "ticker": "AVGO",
            "driver_id": "bdrv_concentration",
            "canonical_key": "customer_concentration",
            "name": "Customer concentration",
            "category": "customer_concentration",
            "current_state": "Hyperscaler concentration is high.",
        }
    )
    store.insert_driver(
        {
            "ticker": "AVGO",
            "driver_id": "bdrv_unrelated",
            "canonical_key": "accounting_quality",
            "name": "Accounting quality",
            "category": "accounting_quality",
            "current_state": "Not the live debate.",
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_duration",
            "title": "AI revenue durability",
            "statement": "Custom silicon demand remains durable.",
            "claim_type": "operating",
            "status": "strongly_supported",
            "is_core": True,
        }
    )
    store.insert_claim(
        {
            "ticker": "AVGO",
            "claim_id": "bclm_unrelated",
            "title": "Tax rate stability",
            "statement": "Tax rate is not the live debate.",
            "claim_type": "operating",
            "status": "background",
            "is_core": False,
        }
    )


def test_default_mode_is_incremental() -> None:
    assert DEFAULT_RUN_MODE == "incremental"
    assert should_full_review(prior_drivers=[{"driver_id": "d1"}], prior_claims=[{"claim_id": "c1"}], mode="incremental") is False
    assert should_full_review(prior_drivers=[], prior_claims=[], mode="incremental") is True
    assert full_review_reason(event={"title": "AVGO reports fiscal Q3 earnings", "event_type": "earnings"}) == "earnings"
    assert full_review_reason(event={"title": "Google signed a networking order"}) is None


def test_case1_duplicate_news_stops_at_l0() -> None:
    store = BrainStore()
    fake = RuntimeFakeCompleter()
    first = {
        "kind": "news",
        "event_key": "meta_ai_capex_raise",
        "subject": "meta_ai_capex_raise",
        "title": "Meta raises 2026 AI capex",
        "fact": "Meta raised 2026 AI capital expenditure.",
        "url": "https://example.com/reuters/meta-capex",
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "confirmed": True,
    }
    store.insert_news({"ticker": "AVGO", "title": first["title"], "new_fact": first["fact"], "url": first["url"]})
    result = run_brain_update(
        ticker="AVGO",
        item={**first, "url": "https://example.com/bloomberg/meta-capex"},
        store=store,
        completer=fake,
    )
    assert result["path"] == "l0_stop"
    assert result["duplicate"] is True
    assert result["glm53_called"] is False
    assert "event_extract" not in fake.calls
    assert "change_proposals" not in fake.calls
    trace = result["trace"]
    assert trace["duplicate"] is True
    assert trace["glm53_called"] is False
    assert trace["full_review_triggered"] is False
    assert "latency_ms" in trace
    assert "token_usage" in trace
    assert "proposal_decisions" in trace


def test_case2_non_material_news_skips_glm53() -> None:
    store = BrainStore()
    fake = RuntimeFakeCompleter()
    result = run_brain_update(
        ticker="AVGO",
        item={
            "kind": "news",
            "title": "AVGO launches new branded T-shirt merch with no new information",
            "fact": "Analyst recap of a product promo. No operating update.",
            "url": "https://example.com/recap/tshirt",
        },
        store=store,
        completer=fake,
    )
    assert result["path"] == "observation_memory"
    assert result["material"] is False
    assert result["glm52_called"] is True
    assert result["glm53_called"] is False
    assert "change_proposals" not in fake.calls
    assert store.list_observations("AVGO")


def test_case3_material_customer_event_uses_targeted_snapshot() -> None:
    store = BrainStore()
    _seed_brain(store)
    fake = RuntimeFakeCompleter()
    result = run_brain_update(
        ticker="AVGO",
        item={
            "kind": "news",
            "title": "Google confirmed a Broadcom custom-silicon order update",
            "fact": "Google, a named AVGO customer, changed a networking order.",
            "event_type": "customer",
            "entities": ["Google"],
            "confidence": "high",
            "fact_reliability": "direct_fact",
            "confirmed": True,
        },
        store=store,
        completer=fake,
    )
    assert result["path"] == "incremental"
    assert result["run_mode"] == "incremental"
    assert result["full_review"] is False
    assert result["material"] is True
    assert result["glm52_called"] is True
    assert result["glm53_called"] is True
    assert "event_extract" in fake.calls
    assert "change_proposals" in fake.calls
    snapshot = result["snapshot"]
    assert snapshot["targeted"] is True
    assert snapshot["full_brain"] is False
    claim_ids = {row.get("claim_id") for row in snapshot["claims"]}
    assert "bclm_duration" in claim_ids
    assert "bclm_unrelated" not in claim_ids
    assert result["proposals"]
    assert result["gate"] is not None
    assert store.claims["bclm_duration"]["status"] == "strongly_supported"


def test_case4_material_rumor_cannot_write_current_state() -> None:
    store = BrainStore()
    _seed_brain(store)
    fake = RuntimeFakeCompleter()
    result = run_brain_update(
        ticker="AVGO",
        item={
            "kind": "news",
            "title": "Unconfirmed: Google may reduce AVGO orders",
            "fact": "Rumor that Google may reduce Broadcom orders.",
            "confidence": "low",
            "fact_reliability": "rumor",
        },
        store=store,
        completer=fake,
    )
    assert result["material"] is True
    assert result["glm53_called"] is True
    assert result["current_state_unchanged"] is True
    assert result["core_claims_unchanged"] is True
    assert store.list_shadows("AVGO")
    assert store.list_current_states("AVGO")
    assert all("reducing" not in str(row.get("statement") or "").lower() for row in store.list_current_states("AVGO"))
    assert store.claims["bclm_duration"]["status"] == "strongly_supported"
    questions = store.list_questions("AVGO")
    assert questions


def test_case5_earnings_may_enter_full_review() -> None:
    fake = RuntimeFakeCompleter()
    result = run_brain_update(
        ticker="AVGO",
        item={"title": "Broadcom reports fiscal Q3 earnings", "event_type": "earnings", "fact": "Quarterly results released."},
        completer=fake,
    )
    assert result["path"] == "full_review"
    assert result["full_review"] is True
    assert result["full_review_reason"] == "earnings"
    assert result["glm53_called"] is False
    assert fake.calls == []


def test_incremental_critic_does_not_reload_whole_brain() -> None:
    base = critic_context(
        states=[{"state_id": "s1", "name": "demand"}, {"state_id": "s2", "name": "rates"}],
        drivers=[{"driver_id": "d1", "canonical_key": "demand_durability"}, {"driver_id": "d2", "canonical_key": "tax"}],
        claims=[{"claim_id": "c1"}, {"claim_id": "c2"}],
        events=[{"event_id": "e1"}],
        transmissions=[{"event_id": "e1", "affected_claims": ["c1"], "affected_drivers": ["d1"]}],
        financial_impacts=[{"object_id": "c1"}],
        evidence=[{"id": "ev1"}, {"id": "ev2"}],
    )
    scoped = incremental_critic_context(base, affected_ids={"s1", "d1", "c1", "e1", "ev1"}, expand=False)
    assert [row["state_id"] for row in scoped["states"]] == ["s1"]
    assert [row["claim_id"] for row in scoped["claims"]] == ["c1"]
    assert scoped["scope"] == "incremental"
    assert critic_should_expand(proposals=[{"object_type": "company_state"}]) is False
    assert critic_should_expand(proposals=[{"object_type": "core_claim"}, {"object_type": "core_claim"}]) is True


def test_context_miss_records_related_objects_not_in_snapshot() -> None:
    from stock_pm.brain.context_miss import find_context_misses

    misses = find_context_misses(
        event={"title": "Google custom ASIC order", "fact": "Google expanded a Broadcom ASIC order.", "entities": ["Google"]},
        snapshot={"states": [], "drivers": [], "claims": [], "evidence": [], "history": [], "causal_edges": []},
        brain={
            "states": [{"state_id": "bst_google", "name": "Google customer exposure", "statement": "Google is an ASIC customer."}],
            "drivers": [{"driver_id": "bdrv_conc", "canonical_key": "customer_concentration", "name": "Hyperscaler concentration"}],
            "claims": [{"claim_id": "bclm_x", "title": "Tax rate", "statement": "Tax is not the debate."}],
            "evidence": [{"id": "rev_google", "fact": "Google confirmed a Broadcom custom ASIC order."}],
            "history": [],
            "causal_edges": [],
        },
    )
    kinds = {row["kind"] for row in misses}
    assert "state" in kinds
    assert "evidence" in kinds
    assert all(row["kind"] != "claim" for row in misses)
