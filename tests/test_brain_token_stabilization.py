from __future__ import annotations

from stock_pm.brain.critic import proposal_critic_context
from stock_pm.brain.incremental import critic_is_needed, critic_should_expand
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.snapshot import build_snapshot
from stock_pm.brain.store import BrainStore

from test_brain_phase2 import CLAIM_ID, DRIVER_ID, STATE_ID, _seed_brain, _supported_path
from test_brain_phase3 import Phase3Completer
from test_brain_phase4 import _case3_sector_move, _case4_unexplained_drop


def test_snapshot_compacts_existing_objects_and_keeps_ids() -> None:
    shot = build_snapshot(
        event={
            "title": "AVGO isolated drop with no filing",
            "fact": "Shares moved -6% while peers were unchanged.",
            "entities": ["AVGO"],
            "price_change_pct": -6.0,
        },
        affected={
            "states": [
                {
                    "state_id": STATE_ID,
                    "name": "AI infrastructure deployment",
                    "statement": "Hyperscaler AI infrastructure deployment remains elevated and this sentence is long enough to be truncated in the compact snapshot.",
                    "evidence_ids": ["rev_exhibit"],
                }
            ],
            "drivers": [
                {
                    "driver_id": DRIVER_ID,
                    "canonical_key": "ai_semiconductor_demand_durability",
                    "name": "AI semiconductor demand durability",
                    "current_state": "Custom silicon demand remains strong.",
                    "evidence_ids": ["rev_exhibit"],
                }
            ],
            "claims": [
                {
                    "claim_id": CLAIM_ID,
                    "title": "AI revenue durability",
                    "statement": "AI revenue durability remains high.",
                    "status": "strongly_supported",
                    "is_core": True,
                }
            ],
            "exposures": [],
        },
        evidence=[{"id": "rev_exhibit", "title": "Exhibit 99.1", "fact": "AI accelerator demand continues to be very strong."}],
        causal_edges=[
            {
                "edge_id": "e17",
                "from_node": STATE_ID,
                "to_node": DRIVER_ID,
                "status": "supported",
                "confidence": "medium",
                "mechanism": "State of hyperscaler deployment lifts custom silicon demand through named ASIC exposure.",
                "support_evidence_ids": ["rev_exhibit", "old_1", "old_2"],
            }
        ],
        history=[
            {
                "history_id": "bhis_prior",
                "object_id": CLAIM_ID,
                "object_type": "core_claim",
                "reason": "prior review",
                "from_payload": {"statement": "a very long previous claim statement that must not be resent"},
                "to_payload": {"statement": "another very long claim statement"},
            }
        ],
    )
    assert shot["compacted"] is True
    assert shot["full_brain"] is False
    assert shot["states"][0]["state_id"] == STATE_ID
    assert shot["drivers"][0]["driver_id"] == DRIVER_ID
    assert shot["claims"][0]["claim_id"] == CLAIM_ID
    assert "support_evidence_ids" not in shot["causal_edges"][0]
    assert shot["history"][0]["history_id"] == "bhis_prior"
    assert "from_payload" not in shot["history"][0]
    assert "exhibit 99.1" in str(shot["evidence"][0].get("title") or "").lower() or "exhibit" in str(shot["evidence"][0])
    parts = shot["context_part_tokens"]
    assert set(parts) >= {"event", "state", "evidence", "causal", "market", "price", "history"}


def test_critic_skips_market_only_and_packs_high_value_proposals() -> None:
    assert critic_is_needed(proposals=[{"object_type": "market_attention", "to": {"statement": "tape"}}]) is False
    assert critic_is_needed(proposals=[{"object_type": "expectation", "to": {"trend": "falling"}}]) is False
    assert critic_is_needed(proposals=[{"object_type": "research_question", "to": {"question": "gap"}}]) is False
    assert critic_is_needed(proposals=[{"object_type": "price_fundamental_divergence", "to": {"status": "open"}}]) is False
    assert (
        critic_is_needed(
            proposals=[
                {
                    "object_type": "core_claim",
                    "object_id": CLAIM_ID,
                    "from": {"status": "strongly_supported", "statement": "Duration holds."},
                    "to": {"status": "challenged", "statement": "Duration is weaker."},
                }
            ]
        )
        is True
    )
    assert critic_should_expand(proposals=[{"object_type": "company_state"}]) is False
    scoped = proposal_critic_context(
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CLAIM_ID,
                "from": {"status": "strongly_supported"},
                "to": {"status": "challenged"},
                "reason": "test",
            }
        ],
        snapshot={"claims": [{"claim_id": CLAIM_ID, "status": "strongly_supported"}], "evidence": [{"id": "rev_exhibit"}]},
        event={"title": "x", "fact": "y"},
        transmission={"successful": [{"nodes": [STATE_ID, DRIVER_ID, CLAIM_ID]}]},
    )
    assert "states" not in scoped
    assert scoped["proposals"]
    assert scoped["relevant_causal_path"]


def test_open_research_questions_are_deduped() -> None:
    store = BrainStore()
    first = store.insert_question({"ticker": "AVGO", "question": "What is the market pricing that the current Brain does not explain?", "why_it_matters": "day1"})
    second = store.insert_question({"ticker": "AVGO", "question": "What is the market pricing that the current Brain does not explain?", "why_it_matters": "day2"})
    rows = store.list_questions("AVGO")
    assert len(rows) == 1
    assert first["question_id"] == second["question_id"]
    assert rows[0]["why_it_matters"] == "day2"


def test_price_only_event_skips_full_critic() -> None:
    store = BrainStore()
    _seed_brain(store, edges=_supported_path())
    result = run_brain_update(
        ticker="AVGO",
        item=_case4_unexplained_drop(),
        store=store,
        completer=Phase3Completer("path"),
    )
    assert result.get("critic_skipped") is True
    assert result.get("critic_called") is False
    sector = run_brain_update(
        ticker="AVGO",
        item=_case3_sector_move(),
        store=store,
        completer=Phase3Completer("path"),
    )
    assert sector.get("critic_skipped") is True
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0
