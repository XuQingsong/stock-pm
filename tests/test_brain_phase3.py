from __future__ import annotations

import json

from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.market import align_market_with_path, normalize_market_attention
from stock_pm.brain.now import build_now_chain
from stock_pm.brain.phase0 import evaluate_brain_changes
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import BRAIN_RUNTIME, MARKET_ALIGNMENTS, NOW_CHAIN_QUESTIONS
from stock_pm.migrate import discover_migrations

from test_brain_phase2 import (
    CLAIM_ID,
    DRIVER_ID,
    EXPOSURE_ID,
    Phase2Completer,
    _capex_event,
    _seed_brain,
    _supported_path,
)


class Phase3Completer(Phase2Completer):
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        if "STEP_ID: change_proposals" in system and self.mode == "mispricing":
            self.calls.append("change_proposals")
            return {
                "status": "ok",
                "payload": {
                    "proposals": [
                        {
                            "object_type": "market_attention",
                            "source_kind": "price",
                            "to": {"statement": "AVGO is mispricing AI duration.", "name": "mispricing_call"},
                            "reason": "Price fell so the stock is mispriced.",
                        },
                        {
                            "object_type": "core_claim",
                            "object_id": CLAIM_ID,
                            "source_kind": "price",
                            "is_core": True,
                            "from": {"status": "strongly_supported", "is_core": True, "statement": "Duration holds."},
                            "to": {"status": "challenged", "is_core": True, "statement": "Duration is mispriced."},
                            "reason": "Tape proves the claim is wrong.",
                        },
                    ],
                    "questions": [],
                },
                "model": "fake-brain",
                "provider": "test",
                "llm_called": True,
                "llm_status": "ok",
                "fallback_used": False,
                "input_tokens": 8,
                "output_tokens": 8,
                "latency_ms": 3,
            }
        return super().complete_json(system=system, user=user, schema=schema)


def test_phase3_runtime_and_now_chain_questions() -> None:
    assert BRAIN_RUNTIME == "phase4"
    assert NOW_CHAIN_QUESTIONS == (
        "what_happened",
        "why_it_affects_company",
        "path_to_driver_claim",
        "what_market_is_trading",
    )
    assert "aligned" in MARKET_ALIGNMENTS
    names = [item.filename for item in discover_migrations()]
    assert "migrations/0023_brain_phase3_market.sql" in names
    assert "migrations/0024_brain_phase3_expectation.sql" in names


def test_case1_supported_path_answers_happened_why_and_path() -> None:
    store = BrainStore()
    _seed_brain(store, edges=_supported_path())
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase3Completer("path"),
    )
    chain = result["now_chain"]
    assert chain["answers"]["what_happened"]
    assert "exposed" in chain["answers"]["why_it_affects_company"].lower() or chain["why_it_affects_company"]["exposures"]
    assert chain["path_to_driver_claim"]["can_affect_claim"] is True
    assert "supported path" in chain["answers"]["path_to_driver_claim"].lower() or chain["path_to_driver_claim"]["successful"]
    assert chain["what_market_is_trading"]["alignment"] in MARKET_ALIGNMENTS
    assert chain["what_market_is_trading"]["cannot_conclude_mispricing"] is True
    assert result["core_claims_unchanged"] is True
    assert result["snapshot"]["full_brain"] is False
    assert len(result["snapshot"].get("market_attentions") or []) <= 3


def test_case2_market_attention_persists_without_rewriting_claim() -> None:
    store = BrainStore()
    _seed_brain(store, edges=_supported_path())
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase3Completer("path"),
    )
    attentions = store.list_market_attentions("AVGO")
    assert attentions
    assert "mispricing" not in str(attentions[0].get("statement") or "").lower()
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["now_chain"]["what_market_is_trading"]["attentions"] or attentions


def test_case3_blocked_path_cannot_change_claim_but_market_can_move() -> None:
    store = BrainStore()
    _seed_brain(store, edges=_supported_path(middle_status="candidate"))
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase3Completer("path"),
    )
    chain = result["now_chain"]
    assert chain["path_to_driver_claim"]["can_affect_claim"] is False
    assert result["core_claims_unchanged"] is True
    assert store.list_market_attentions("AVGO") or chain["what_market_is_trading"]["alignment"] in MARKET_ALIGNMENTS


def test_case4_unexplained_price_is_not_mispricing() -> None:
    event = {
        "kind": "price",
        "title": "AVGO drops 4% with no new filing",
        "fact": "Shares fell 4% without a new operating disclosure.",
        "price_change_pct": -4.0,
        "fact_reliability": "signal",
    }
    chain = build_now_chain(
        event=event,
        exposures=[],
        transmission={"successful": [], "blocked": [], "successful_count": 0, "blocked_count": 0},
        causal_gaps=[{"question": "What is the market pricing that the current Brain does not explain?"}],
        material=True,
    )
    assert chain["what_market_is_trading"]["alignment"] == "unexplained"
    assert chain["what_market_is_trading"]["cannot_conclude_mispricing"] is True
    assert "mispricing" not in chain["answers"]["what_market_is_trading"].lower() or "not mispricing" in chain["answers"]["what_market_is_trading"].lower()
    result = evaluate_brain_changes(
        ticker="AVGO",
        observations=[event],
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CLAIM_ID,
                "source_kind": "price",
                "is_core": True,
                "from_payload": {"status": "strongly_supported", "is_core": True, "claim_type": "operating", "statement": "Duration holds."},
                "to_payload": {"status": "challenged", "is_core": True, "claim_type": "operating", "statement": "AVGO is mispriced."},
                "reason": "Unexplained price move implies mispricing.",
            }
        ],
        store=BrainStore(),
    )
    rules = {row["rule"] for item in result["rejected"] for row in item.get("rules") or []}
    assert "price_cannot_modify_fundamental_claim" in rules or "unexplained_price_is_not_mispricing" in rules
    assert result["core_claims_unchanged"] is True
    assert result["questions"]


def test_case5_market_attention_cannot_say_mispricing() -> None:
    hits = constitution_violations(
        {
            "object_type": "market_attention",
            "source_kind": "price",
            "to_payload": {"statement": "This is mispricing of AI duration."},
            "reason": "Down day.",
        }
    )
    assert any(row["rule"] == "unexplained_price_is_not_mispricing" for row in hits)
    store = BrainStore()
    _seed_brain(store, edges=_supported_path())
    result = run_brain_update(
        ticker="AVGO",
        item={**_capex_event(), "kind": "price", "price_change_pct": -3.2},
        store=store,
        completer=Phase3Completer("mispricing"),
    )
    assert result["core_claims_unchanged"] is True
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    stored = store.list_market_attentions("AVGO")
    assert all("mispricing" not in str(row.get("statement") or "").lower() for row in stored)


def test_case6_now_chain_is_targeted_not_full_brain() -> None:
    store = BrainStore()
    _seed_brain(store)
    for idx in range(8):
        store.upsert_market_attention(
            normalize_market_attention({"name": f"noise_{idx}", "statement": f"Unrelated tape {idx}"}, ticker="AVGO")
        )
    result = run_brain_update(
        ticker="AVGO",
        item=_capex_event(),
        store=store,
        completer=Phase3Completer("path"),
    )
    snapshot = result["snapshot"]
    assert snapshot["targeted"] is True
    assert snapshot["full_brain"] is False
    assert len(snapshot.get("market_attentions") or []) <= 3
    assert len(snapshot.get("causal_edges") or []) <= 8
    answers = result["now_chain"]["answers"]
    assert set(answers) == set(NOW_CHAIN_QUESTIONS)


def test_alignment_unknown_without_tape() -> None:
    aligned = align_market_with_path(
        event={"title": "Meta raises AI capex", "kind": "news"},
        attentions=[],
        transmission={"successful_count": 1, "blocked_count": 0, "successful": [{"nodes": [EXPOSURE_ID, DRIVER_ID, CLAIM_ID]}]},
    )
    assert aligned["alignment"] == "unknown"
    assert aligned["cannot_conclude_mispricing"] is True
    explained = align_market_with_path(
        event={"title": "Meta raises AI capex", "kind": "news"},
        attentions=[{"statement": "Tape focused on hyperscaler ASIC exposure", "related_objects": [EXPOSURE_ID]}],
        transmission={"successful_count": 1, "blocked_count": 0, "successful": [{"nodes": [EXPOSURE_ID, DRIVER_ID, CLAIM_ID]}]},
    )
    assert explained["alignment"] in {"aligned", "partial"}
    json.dumps(build_now_chain(event=_capex_event(), exposures=[{"subject": "AVGO", "object_name": "ASIC", "mechanism": "named customer"}]))
