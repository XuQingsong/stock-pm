from __future__ import annotations

from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.divergence import (
    UNRESOLVED_PRICE_QUESTION,
    apply_divergence_lifecycle,
    explain_price_move,
    price_as_evidence_forbidden,
    repeated_divergence_gaps,
)
from stock_pm.brain.layers import is_fast_layer, object_layer
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import (
    BRAIN_RUNTIME,
    DIVERGENCE_STATUSES,
    EXPLANATION_GRADES,
    NOW_CHAIN_QUESTIONS,
)
from stock_pm.migrate import discover_migrations

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


def _case1_guidance_cut() -> dict:
    return {
        "kind": "news",
        "event_key": "fy_guidance_cut",
        "event_type": "guidance",
        "title": "Company cuts FY guidance sharply",
        "fact": "Management lowered full-year guidance and the stock fell 10%.",
        "price_change_pct": -10.0,
        "confirmed": True,
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "entities": ["AVGO"],
        "as_of": "2026-06-10",
    }


def _case2_print_below_expectation() -> dict:
    return {
        "kind": "news",
        "event_key": "ai_revenue_below_expectation",
        "event_type": "earnings",
        "subject": "AI revenue growth",
        "title": "AI revenue growth printed 40% while the market expected 50%",
        "fact": "AI revenue growth was 40%. The market expected 50%. Shares fell.",
        "actual": 40,
        "expected": 50,
        "expectation_name": "AI revenue growth",
        "price_change_pct": -5.0,
        "confirmed": True,
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "entities": ["AVGO"],
        "as_of": "2026-06-12",
    }


def _case3_sector_move() -> dict:
    return {
        "kind": "price",
        "event_key": "sector_tape_down",
        "title": "AVGO shares move -6% with semiconductor peers",
        "fact": "AVGO -6%. SOX -5%. MRVL -5%. NVDA -5.5%.",
        "event_type": "other",
        "price_change_pct": -6.0,
        "peers": {"SOX": -5.0, "MRVL": -5.0, "NVDA": -5.5},
        "confirmed": True,
        "fact_reliability": "signal",
        "as_of": "2026-06-14",
    }


def _case4_unexplained_drop(*, suffix: str = "a", as_of: str = "2026-06-01", pct: float = -6.0) -> dict:
    titles = {
        "a": "AVGO drops 6% while peers stay quiet and no filing appears",
        "day1": "AVGO sells off 6% on June 1 with no operating disclosure",
        "r1": "AVGO falls 6 percent alone while SOX is flat",
        "r2": "Another AVGO-only selloff: shares lose 7.2 percent, no 8-K",
        "m4": "Company-specific AVGO decline of 6% versus stable peers",
        "m5": "June 1 tape: AVGO -6% and no new customer news",
        "m6a": "July 1 isolated AVGO decline without a fundamental update",
        "m6b": "July 8 second lone AVGO drawdown still lacks an 8-K",
    }
    facts = {
        "a": "AVGO -6%. MRVL 0.2%. NVDA 0.1%. SOX 0.0%. No new filing.",
        "day1": "June 1 close showed AVGO down 6% with MRVL and SOX unchanged.",
        "r1": "SOX was unchanged while Broadcom lost 6 percent. No 8-K.",
        "r2": "A week later Broadcom lost 7.2 percent. Nvidia and Marvell did not follow.",
        "m4": "Peer semiconductors were flat as AVGO lost 6%.",
        "m5": "AVGO printed -6% on June 1. No customer filing that day.",
        "m6a": "First lone July drawdown: AVGO -6% and no fundamental update.",
        "m6b": "Second lone July drawdown: AVGO -7.2% still without an 8-K.",
    }
    return {
        "kind": "price",
        "event_key": f"unexplained_company_drop_{suffix}",
        "title": titles.get(suffix, f"AVGO isolated move {suffix} {pct}% {as_of}"),
        "fact": facts.get(suffix, f"On {as_of} AVGO printed {pct}%. No filing {suffix}."),
        "event_type": "other",
        "price_change_pct": pct,
        "peers": {"MRVL": 0.2, "NVDA": 0.1, "SOX": 0.0},
        "confirmed": True,
        "fact_reliability": "signal",
        "as_of": as_of,
        "published_at": as_of,
    }


def _case5_later_evidence() -> dict:
    return {
        "kind": "news",
        "event_key": "customer_weakness_confirmed",
        "event_type": "customer",
        "title": "Company confirms customer demand weakness",
        "fact": "The company confirmed customer demand weakness at a major account.",
        "confirmed": True,
        "confidence": "high",
        "fact_reliability": "direct_fact",
        "entities": ["Google"],
        "as_of": "2026-06-05",
    }


def test_phase4_runtime_and_now_chain_stay_four_questions() -> None:
    assert BRAIN_RUNTIME == "phase4"
    assert NOW_CHAIN_QUESTIONS == (
        "what_happened",
        "why_it_affects_company",
        "path_to_driver_claim",
        "what_market_is_trading",
    )
    assert DIVERGENCE_STATUSES == ("open", "partially_explained", "resolved", "expired")
    assert "well_explained" in EXPLANATION_GRADES
    assert is_fast_layer("price_fundamental_divergence")
    assert object_layer("price_fundamental_divergence") == "market"
    names = [item.filename for item in discover_migrations()]
    assert "migrations/0025_brain_phase4_divergence.sql" in names


def test_case1_guidance_cut_is_well_explained() -> None:
    store, result = _run(_case1_guidance_cut())
    assert result["explanation"]["grade"] == "well_explained"
    assert result["explanation"]["should_create_divergence"] is False
    assert result["market_layer"]["divergences_created"] == 0
    strong = [row for row in store.list_divergences("AVGO") if row.get("status") == "open"]
    assert not strong
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0
    assert result["market_layer"]["price_established_edge_violations"] == 0
    chain = result["now_chain"]["what_market_is_trading"]
    assert chain["explanation_grade"] == "well_explained"
    assert "price feedback" in result["now_chain"]["answers"]["what_market_is_trading"].lower()


def test_case2_positive_print_below_expectation_explains_price_not_claim() -> None:
    store, result = _run(_case2_print_below_expectation())
    assert result["explanation"]["checks"]["expectation_changed"] is True
    assert result["explanation"]["grade"] in {"well_explained", "partially_explained"}
    assert result["explanation"]["should_create_divergence"] is False
    assert result["current_state_unchanged"] is True
    assert result["core_claims_unchanged"] is True
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert "elevated" in store.states[STATE_ID]["statement"].lower()
    rows = store.list_expectations("AVGO")
    assert rows
    assert rows[0]["comparison"] == "below"
    assert rows[0]["trend"] == "falling"
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0


def test_case3_sector_move_is_not_company_specific_divergence() -> None:
    store, result = _run(_case3_sector_move())
    assert result["explanation"]["checks"]["peer_sector_explains"] is True
    assert result["explanation"]["grade"] == "well_explained"
    assert result["explanation"]["should_create_divergence"] is False
    company = [row for row in store.list_divergences("AVGO") if "company_specific" in str(row.get("signature") or "")]
    assert not company
    hyps = store.list_hypotheses("AVGO")
    assert any(row.get("kind") == "sector_macro" for row in hyps)
    assert result["core_claims_unchanged"] is True
    assert result["market_layer"]["price_fundamental_violations"] == 0


def test_case4_company_specific_drop_opens_divergence_and_research_question() -> None:
    store, result = _run(_case4_unexplained_drop())
    assert result["explanation"]["grade"] == "largely_unexplained"
    assert result["explanation"]["should_create_divergence"] is True
    rows = store.list_divergences("AVGO")
    assert rows
    assert rows[0]["status"] == "open"
    assert rows[0]["kind"] == "price_fundamental_divergence"
    assert rows[0]["price_is_not_evidence_for_resolution"] is True
    questions = " ".join(row.get("question") or "" for row in store.list_questions("AVGO")).lower()
    assert "market pricing" in questions or "does not explain" in questions
    unresolved = [row for row in store.list_hypotheses("AVGO") if row.get("status") == "unresolved"]
    assert unresolved
    chain = result["now_chain"]["what_market_is_trading"]
    assert chain["divergence"]["status"] == "open"
    assert chain["unresolved"] is True
    assert "price feedback" in result["now_chain"]["answers"]["what_market_is_trading"].lower()
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0
    assert result["market_layer"]["price_established_edge_violations"] == 0


def test_case5_later_evidence_resolves_without_hindsight() -> None:
    store, day1 = _run(_case4_unexplained_drop(suffix="day1", as_of="2026-06-01"))
    opened = store.list_divergences("AVGO")
    assert opened
    assert opened[0]["status"] == "open"
    assert opened[0]["opened_as_of"] == "2026-06-01"
    known = dict(opened[0].get("known_at_open") or {})
    assert known.get("known_event_explains") is False
    day1_price_id = opened[0]["opened_by_event_id"]
    store, day3 = _run(_case5_later_evidence(), store=store)
    rows = store.list_divergences("AVGO")
    assert rows
    assert rows[0]["status"] in {"resolved", "partially_explained"}
    assert rows[0]["opened_as_of"] == "2026-06-01"
    assert rows[0]["known_at_open"] == known
    assert rows[0]["price_is_not_evidence_for_resolution"] is True
    assert day1_price_id not in (rows[0].get("resolution_evidence_ids") or [])
    claim = store.claims[CLAIM_ID]
    evidence = list((claim.get("reasoning") or {}).get("evidence_ids") or claim.get("evidence_ids") or [])
    assert day1_price_id not in evidence
    assert "unexplained_company_drop_day1" not in evidence
    assert store.claims[CLAIM_ID]["status"] == "strongly_supported"
    assert day3["market_layer"]["price_fundamental_violations"] == 0
    assert day3["market_layer"]["price_claim_violations"] == 0
    assert day1["explanation"]["grade"] == "largely_unexplained"


def test_case6_repeated_unexplained_proposes_brain_gap_not_edge() -> None:
    store, first = _run(_case4_unexplained_drop(suffix="r1", as_of="2026-07-01", pct=-6.0))
    store, second = _run(_case4_unexplained_drop(suffix="r2", as_of="2026-07-08", pct=-7.2), store=store)
    gaps = repeated_divergence_gaps(store.list_divergences("AVGO"), ticker="AVGO")
    assert gaps["patterns"]
    blob = " ".join(row.get("question") or "" for row in store.list_questions("AVGO")).lower()
    assert "missing market driver" in blob or "missing causal edge" in blob or "missing exposure" in blob
    assert all(row.get("status") != "established" for row in store.list_hypotheses("AVGO"))
    approved_edges = [
        row
        for row in (second.get("gate") or {}).get("approved") or []
        if str(row.get("object_type") or "") in {"causal_edge", "causal_relationship"}
        and str((row.get("to_payload") or {}).get("status") or "") == "established"
    ]
    assert not approved_edges
    assert second["market_layer"]["price_established_edge_violations"] == 0
    assert first["core_claims_unchanged"] is True
    assert second["core_claims_unchanged"] is True


def test_price_cannot_write_fundamental_claim_or_established_edge() -> None:
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
    edge_hits = constitution_violations(
        {
            "object_type": "causal_edge",
            "source_kind": "price",
            "to_payload": {"from_node": "price", "to_node": CLAIM_ID, "status": "established"},
        }
    )
    assert any(row["rule"] == "price_cannot_create_established_causal_edge" for row in edge_hits)
    assert price_as_evidence_forbidden(["price:day1_drop"], price_observation_ids=["price:day1_drop"]) is True
    assert price_as_evidence_forbidden(["customer_weakness_confirmed"]) is False


def test_unit_explanation_check_and_lifecycle() -> None:
    explained = explain_price_move(
        _case1_guidance_cut(),
        ticker="AVGO",
        expectation=None,
        hypotheses=[],
    )
    assert explained["grade"] == "well_explained"
    unexplained = explain_price_move(
        _case4_unexplained_drop(),
        ticker="AVGO",
        expectation=None,
        hypotheses=[],
    )
    assert unexplained["grade"] == "largely_unexplained"
    opened = apply_divergence_lifecycle(unexplained, ticker="AVGO", event=_case4_unexplained_drop())
    assert opened["created"]
    later = explain_price_move(_case5_later_evidence(), ticker="AVGO")
    resolved = apply_divergence_lifecycle(later, ticker="AVGO", event=_case5_later_evidence(), existing=opened["created"])
    assert resolved["resolved"] or resolved["partially_explained"]
    assert resolved["resolved"][0]["known_at_open"] == opened["created"][0]["known_at_open"]
    assert opened["created"][0]["opened_by_event_id"] not in (resolved["resolved"][0].get("resolution_evidence_ids") or [])
    assert UNRESOLVED_PRICE_QUESTION in {row.get("question") for row in opened["questions"]}


def collect_phase4_metrics() -> dict:
    metrics = {
        "price_observations": 0,
        "material_abnormal_price_events": 0,
        "divergences_created": 0,
        "divergences_resolved": 0,
        "divergences_partially_explained": 0,
        "divergences_still_open": 0,
        "repeated_divergence_patterns": 0,
        "research_questions_from_price": 0,
        "hypotheses_updated_from_price": 0,
        "expectation_updates_from_price_context": 0,
        "price_fundamental_violations": 0,
        "price_claim_violations": 0,
        "price_established_edge_violations": 0,
    }
    events = [
        _case1_guidance_cut(),
        _case2_print_below_expectation(),
        _case3_sector_move(),
        _case4_unexplained_drop(suffix="m4"),
    ]
    store_r = None
    results = []
    for event in events:
        store, result = _run(event)
        results.append(result)
        if event is events[-1]:
            store_r = store
    store5, day1 = _run(_case4_unexplained_drop(suffix="m5", as_of="2026-06-01"))
    store5, day3 = _run(_case5_later_evidence(), store=store5)
    store6, r6a = _run(_case4_unexplained_drop(suffix="m6a", as_of="2026-07-01"))
    store6, r6b = _run(_case4_unexplained_drop(suffix="m6b", as_of="2026-07-08"), store=store6)
    for event, result in zip(events, results):
        if event.get("price_change_pct") is not None:
            metrics["price_observations"] += 1
        if (result.get("explanation") or {}).get("abnormal"):
            metrics["material_abnormal_price_events"] += 1
        stats = result.get("market_layer") or {}
        metrics["divergences_created"] += int(stats.get("divergences_created") or 0)
        metrics["divergences_still_open"] += int(stats.get("divergences_still_open") or 0)
        metrics["research_questions_from_price"] += int(stats.get("research_questions_from_price") or 0)
        metrics["price_fundamental_violations"] += int(stats.get("price_fundamental_violations") or 0)
        metrics["price_claim_violations"] += int(stats.get("price_claim_violations") or 0)
        metrics["price_established_edge_violations"] += int(stats.get("price_established_edge_violations") or 0)
        if event.get("kind") == "price":
            metrics["hypotheses_updated_from_price"] += int(stats.get("hypotheses_created") or 0) + int(stats.get("hypotheses_updated") or 0)
        if (result.get("explanation") or {}).get("checks", {}).get("expectation_changed"):
            metrics["expectation_updates_from_price_context"] += 1
    for result in (day1, day3, r6a, r6b):
        stats = result.get("market_layer") or {}
        metrics["price_observations"] += 1
        if (result.get("explanation") or {}).get("abnormal"):
            metrics["material_abnormal_price_events"] += 1
        metrics["divergences_created"] += int(stats.get("divergences_created") or 0)
        metrics["divergences_resolved"] += int(stats.get("divergences_resolved") or 0)
        metrics["divergences_partially_explained"] += int(stats.get("divergences_partially_explained") or 0)
        metrics["divergences_still_open"] += int(stats.get("divergences_still_open") or 0)
        metrics["repeated_divergence_patterns"] += int(stats.get("repeated_divergence_patterns") or 0)
        metrics["research_questions_from_price"] += int(stats.get("research_questions_from_price") or 0)
        metrics["price_fundamental_violations"] += int(stats.get("price_fundamental_violations") or 0)
        metrics["price_claim_violations"] += int(stats.get("price_claim_violations") or 0)
        metrics["price_established_edge_violations"] += int(stats.get("price_established_edge_violations") or 0)
    metrics["open_after_case4"] = len([row for row in (store_r.list_divergences("AVGO") if store_r else []) if row.get("status") == "open"])
    metrics["resolved_after_case5"] = len([row for row in store5.list_divergences("AVGO") if row.get("status") in {"resolved", "partially_explained"}])
    metrics["brain_gap_questions_case6"] = len(
        [row for row in store6.list_questions("AVGO") if "missing" in str(row.get("question") or "").lower()]
    )
    metrics["context_parts_case4"] = dict((results[-1].get("token_usage") or {}).get("context_parts") or {})
    return metrics
