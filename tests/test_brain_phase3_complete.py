from __future__ import annotations

from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.expectation import compare_actual_to_expectation, expectation_from_event
from stock_pm.brain.hypothesis import hypotheses_from_event, is_unresolved_price, peer_pattern
from stock_pm.brain.layers import is_fast_layer, layer_speed
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import CONSTITUTION_RULES, NOW_CHAIN_QUESTIONS

from test_brain_phase2 import CLAIM_ID, STATE_ID, _seed_brain, _supported_path
from test_brain_phase3 import Phase3Completer


def _run(event: dict, *, store: BrainStore | None = None) -> tuple[BrainStore, dict]:
    brain = store or BrainStore()
    if store is None:
        _seed_brain(brain, edges=_supported_path())
    result = run_brain_update(
        ticker="AVGO",
        item=event,
        store=brain,
        completer=Phase3Completer("path"),
    )
    return brain, result


def _case1_event() -> dict:
    return {
        "kind": "news",
        "event_key": "ai_revenue_print",
        "subject": "AI revenue growth",
        "title": "AI revenue growth printed 40% while the market expected 50%",
        "fact": "AI revenue growth was 40%. The market expected 50%.",
        "event_type": "other",
        "actual": 40,
        "expected": 50,
        "expectation_name": "AI revenue growth",
        "confirmed": True,
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "entities": ["AVGO"],
    }


def _case2_event() -> dict:
    return {
        "kind": "news",
        "event_key": "avgo_solo_tape",
        "title": "AVGO shares move -7% while peers are unchanged",
        "fact": "AVGO -7%. MRVL 0%. SOX 0%.",
        "event_type": "other",
        "price_change_pct": -7.0,
        "peers": {"MRVL": 0.0, "SOX": 0.0},
        "confirmed": True,
        "fact_reliability": "direct_fact",
    }


def _case3_event() -> dict:
    return {
        "kind": "news",
        "event_key": "semi_group_tape",
        "title": "AVGO shares move -7% with semiconductor peers",
        "fact": "AVGO -7%. MRVL -6%. NVDA -5%. SOX -5%.",
        "event_type": "other",
        "price_change_pct": -7.0,
        "peers": {"MRVL": -6.0, "NVDA": -5.0, "SOX": -5.0},
        "confirmed": True,
        "fact_reliability": "direct_fact",
    }


def _case4_event() -> dict:
    return {
        "kind": "rumor",
        "event_key": "google_rumor_delay",
        "subject": "Google custom silicon volume",
        "title": "Unconfirmed rumor that Google may delay custom silicon volume",
        "fact": "An unconfirmed rumor says Google may delay custom silicon volume.",
        "event_type": "other",
        "confirmed": False,
        "confidence": "low",
        "fact_reliability": "rumor",
        "entities": ["Google"],
    }


def _case5_event(suffix: str = "a") -> dict:
    return {
        "kind": "news",
        "event_key": f"competing_tape_{suffix}",
        "title": f"Tape offers three explanations for AVGO ({suffix})",
        "fact": "Valuation, customer concentration, and AI demand are all candidate explanations.",
        "event_type": "other",
        "candidate_hypotheses": ["ai_demand", "customer_concentration", "valuation"],
        "confirmed": True,
        "fact_reliability": "direct_fact",
    }


def _case6_event() -> dict:
    return {
        "kind": "price",
        "event_key": "unexplained_tape",
        "title": "AVGO shares move -8% with no new filing",
        "fact": "Shares moved -8% without a new operating disclosure.",
        "event_type": "other",
        "price_change_pct": -8.0,
        "fact_reliability": "signal",
    }


def test_expectation_and_hypothesis_are_fast_market_objects() -> None:
    assert is_fast_layer("expectation")
    assert is_fast_layer("expectation_state")
    assert is_fast_layer("market_driver_hypothesis")
    assert layer_speed("expectation") == "fast"
    assert "price_cannot_modify_fundamental_state" in CONSTITUTION_RULES
    assert "market_hypothesis_is_not_fact" in CONSTITUTION_RULES
    assert NOW_CHAIN_QUESTIONS[-1] == "what_market_is_trading"


def test_unit_actual_vs_expected_and_peer_patterns() -> None:
    compared = compare_actual_to_expectation(40, 50)
    assert compared == {"comparison": "below", "trend": "falling"}
    row = expectation_from_event(_case1_event(), ticker="AVGO")
    assert row is not None
    assert row["comparison"] == "below"
    assert row["trend"] == "falling"
    assert peer_pattern(-7, {"MRVL": 0, "SOX": 0}) == "company_specific"
    assert peer_pattern(-7, {"MRVL": -6, "NVDA": -5, "SOX": -5}) == "sector_macro"
    assert is_unresolved_price(_case6_event(), expectation=None, peer=None) is True
    assert is_unresolved_price(_case2_event(), expectation=None, peer="company_specific") is False


def test_case1_positive_print_below_expectation_does_not_worsen_fundamental() -> None:
    store, result = _run(_case1_event())
    seeded_state = store.states[STATE_ID]["statement"]
    assert "elevated" in seeded_state.lower()
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["current_state_unchanged"] is True
    assert result["core_claims_unchanged"] is True
    rows = store.list_expectations("AVGO")
    assert rows
    assert rows[0]["comparison"] == "below"
    assert rows[0]["trend"] == "falling"
    assert rows[0]["actual"] == 40
    assert rows[0]["expected"] == 50
    chain = result["now_chain"]
    assert chain["what_market_is_trading"]["expectation"]["trend"] == "falling"
    assert "fell because" not in chain["answers"]["what_market_is_trading"].lower()
    stats = result["market_layer"]
    assert stats["expectation_changes"] >= 1
    assert stats["price_fundamental_violations"] == 0
    assert stats["price_claim_violations"] == 0


def test_case2_issuer_only_drop_supports_company_specific_hypothesis() -> None:
    store, result = _run(_case2_event())
    rows = store.list_hypotheses("AVGO")
    company = [row for row in rows if row.get("kind") == "company_specific"]
    assert company
    assert company[0]["status"] == "supported"
    assert any("peers" in item.lower() for item in company[0]["supporting_observations"])
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["market_layer"]["peer_observations_used"] >= 1
    assert result["market_layer"]["hypotheses_created"] >= 1
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_case3_sector_co_move_supports_macro_hypothesis() -> None:
    store, result = _run(_case3_event())
    rows = store.list_hypotheses("AVGO")
    sector = [row for row in rows if row.get("kind") == "sector_macro"]
    assert sector
    assert sector[0]["status"] == "supported"
    assert result["market_layer"]["peer_observations_used"] >= 1
    assert result["core_claims_unchanged"] is True
    assert store.states[STATE_ID]["statement"] == "Hyperscaler AI infrastructure deployment remains elevated."
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_case4_google_rumor_moves_market_layer_not_claim() -> None:
    store, result = _run(_case4_event())
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["core_claims_unchanged"] is True
    assert result["current_state_unchanged"] is True
    assert store.list_shadows("AVGO") or result["gate"]["shadows"]
    attentions = store.list_market_attentions("AVGO") or result["now_chain"]["what_market_is_trading"]["attentions"]
    assert attentions
    hyps = store.list_hypotheses("AVGO")
    assert hyps
    assert all(row.get("status") != "established" for row in hyps)
    assert any(row.get("confidence") == "low" for row in hyps)
    expectations = store.list_expectations("AVGO")
    assert expectations
    assert expectations[0]["confidence"] == "low"
    assert expectations[0]["trend"] == "falling"
    market = result["now_chain"]["what_market_is_trading"]["answer"].lower()
    assert "fell because" not in market
    assert "mispricing" not in market
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_case5_three_hypotheses_coexist_without_winner() -> None:
    from stock_pm.brain.market_layer import interpret_market_layer

    store, first = _run(_case5_event("a"))
    keys = {row.get("canonical_key") for row in store.list_hypotheses("AVGO")}
    assert {"ai_demand", "customer_concentration", "valuation"} <= keys
    assert first["market_layer"]["competing_hypotheses"] >= 3
    chain = first["now_chain"]["answers"]["what_market_is_trading"]
    assert "which driver dominates is not established" in chain.lower()
    assert all(row.get("status") != "established" for row in store.list_hypotheses("AVGO"))
    again = interpret_market_layer(
        _case5_event("b"),
        ticker="AVGO",
        existing_hypotheses=store.list_hypotheses("AVGO"),
    )
    assert again["stats"]["duplicates_prevented"] >= 3
    assert again["stats"]["hypotheses_updated"] >= 3
    assert len(store.list_hypotheses("AVGO")) >= 3
    assert first["market_layer"]["price_fundamental_violations"] == 0
    assert first["market_layer"]["price_claim_violations"] == 0
    assert first["core_claims_unchanged"] is True


def test_case6_unexplained_price_is_unresolved_research_question() -> None:
    store, result = _run(_case6_event())
    assert result["now_chain"]["what_market_is_trading"]["unresolved"] is True
    assert result["market_layer"]["unresolved_events"] >= 1
    questions = store.list_questions("AVGO")
    blob = " ".join(row.get("question") or "" for row in questions).lower()
    assert "market pricing" in blob or "does not explain" in blob
    unresolved = [row for row in store.list_hypotheses("AVGO") if row.get("status") == "unresolved"]
    assert unresolved
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    market = result["now_chain"]["answers"]["what_market_is_trading"].lower()
    assert "fell because" not in market
    assert "mispricing" not in market
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_price_cannot_write_fundamental_or_claim_and_hypothesis_is_not_fact() -> None:
    state_hits = constitution_violations(
        {
            "object_type": "company_state",
            "source_kind": "price",
            "to_payload": {"statement": "AI demand is broken because the stock fell."},
        }
    )
    assert any(row["rule"] == "price_cannot_modify_fundamental_state" for row in state_hits)
    claim_hits = constitution_violations(
        {
            "object_type": "core_claim",
            "source_kind": "price",
            "is_core": True,
            "from_payload": {"status": "strongly_supported", "is_core": True, "claim_type": "operating"},
            "to_payload": {"status": "challenged", "is_core": True, "claim_type": "operating"},
        }
    )
    assert any(row["rule"] == "price_cannot_modify_fundamental_claim" for row in claim_hits)
    hyp_hits = constitution_violations(
        {
            "object_type": "market_driver_hypothesis",
            "source_kind": "price",
            "to_payload": {"status": "established", "hypothesis": "This is the reason.", "is_fact": True},
        }
    )
    assert any(row["rule"] == "market_hypothesis_is_not_fact" for row in hyp_hits)
    created = hypotheses_from_event(_case5_event("a"), ticker="AVGO")
    again = hypotheses_from_event(_case5_event("a"), ticker="AVGO", existing=created["created"])
    assert again["duplicates_prevented"] >= 3
    assert again["updated"]


def collect_phase3_complete_metrics() -> dict:
    """Aggregate the required Phase 3 completion metrics across the six cases."""
    metrics = {
        "expectation_changes": 0,
        "hypotheses_created": 0,
        "hypotheses_updated": 0,
        "competing_hypotheses_per_event_max": 0,
        "hypothesis_strengthened": 0,
        "hypothesis_weakened": 0,
        "duplicates_prevented": 0,
        "unresolved_events": 0,
        "research_questions": 0,
        "peer_observations_used": 0,
        "price_fundamental_violations": 0,
        "price_claim_violations": 0,
    }
    store1, r1 = _run(_case1_event())
    store2, r2 = _run(_case2_event())
    store3, r3 = _run(_case3_event())
    store4, r4 = _run(_case4_event())
    store5, r5a = _run(_case5_event("a"))
    from stock_pm.brain.market_layer import interpret_market_layer

    r5b = interpret_market_layer(
        _case5_event("b"),
        ticker="AVGO",
        existing_hypotheses=store5.list_hypotheses("AVGO"),
    )
    store6, r6 = _run(_case6_event())
    extra_stats = [r5b.get("stats") or {}]
    for result in (r1, r2, r3, r4, r5a, r6):
        stats = result.get("market_layer") or {}
        metrics["expectation_changes"] += int(stats.get("expectation_changes") or 0)
        metrics["hypotheses_created"] += int(stats.get("hypotheses_created") or 0)
        metrics["hypotheses_updated"] += int(stats.get("hypotheses_updated") or 0)
        metrics["competing_hypotheses_per_event_max"] = max(
            metrics["competing_hypotheses_per_event_max"], int(stats.get("competing_hypotheses") or 0)
        )
        metrics["hypothesis_strengthened"] += int(stats.get("hypothesis_strengthened") or 0)
        metrics["hypothesis_weakened"] += int(stats.get("hypothesis_weakened") or 0)
        metrics["duplicates_prevented"] += int(stats.get("duplicates_prevented") or 0)
        metrics["unresolved_events"] += int(stats.get("unresolved_events") or 0)
        metrics["research_questions"] += int(stats.get("research_questions") or 0) + len(result.get("questions") or [])
        metrics["peer_observations_used"] += int(stats.get("peer_observations_used") or 0)
        metrics["price_fundamental_violations"] += int(stats.get("price_fundamental_violations") or 0)
        metrics["price_claim_violations"] += int(stats.get("price_claim_violations") or 0)
    for stats in extra_stats:
        metrics["hypotheses_updated"] += int(stats.get("hypotheses_updated") or 0)
        metrics["duplicates_prevented"] += int(stats.get("duplicates_prevented") or 0)
        metrics["competing_hypotheses_per_event_max"] = max(
            metrics["competing_hypotheses_per_event_max"], int(stats.get("competing_hypotheses") or 0)
        )
    metrics["persisted_expectations"] = len(store1.list_expectations("AVGO"))
    metrics["persisted_hypotheses_case5"] = len(store5.list_hypotheses("AVGO"))
    metrics["persisted_questions_case6"] = len(store6.list_questions("AVGO"))
    metrics["case4_claim_status"] = store4.claims[CLAIM_ID]["status"]
    metrics["case1_state"] = store1.states[STATE_ID]["statement"]
    return metrics
