#!/usr/bin/env python3
"""Phase 3 completion self-validation: Expectation + Market Driver Hypothesis."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from stock_pm.brain.now import build_now_chain
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import BRAIN_RUNTIME, NOW_CHAIN_QUESTIONS

from test_brain_phase0 import test_case1_unconfirmed_google_order_enters_shadow
from test_brain_phase2 import (
    Phase2Completer,
    _capex_event,
    _seed_brain,
    _supported_path,
    test_case1_supported_path_can_transmit,
    test_case2_candidate_edge_stops_downstream_writes,
)
from test_brain_phase3 import (
    test_case1_supported_path_answers_happened_why_and_path,
    test_case2_market_attention_persists_without_rewriting_claim,
    test_case4_unexplained_price_is_not_mispricing,
    test_case5_market_attention_cannot_say_mispricing,
)
from test_brain_phase3_complete import (
    collect_phase3_complete_metrics,
    test_case1_positive_print_below_expectation_does_not_worsen_fundamental,
    test_case2_issuer_only_drop_supports_company_specific_hypothesis,
    test_case3_sector_co_move_supports_macro_hypothesis,
    test_case4_google_rumor_moves_market_layer_not_claim,
    test_case5_three_hypotheses_coexist_without_winner,
    test_case6_unexplained_price_is_unresolved_research_question,
    test_price_cannot_write_fundamental_or_claim_and_hypothesis_is_not_fact,
)

OUT = Path("artifacts/brain_phase3_validation")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    for name, fn in (
        ("phase3_now_chain", test_case1_supported_path_answers_happened_why_and_path),
        ("phase3_market_attention_persist", test_case2_market_attention_persists_without_rewriting_claim),
        ("phase3_unexplained_price", test_case4_unexplained_price_is_not_mispricing),
        ("phase3_no_mispricing_attention", test_case5_market_attention_cannot_say_mispricing),
        ("phase3_expectation_below_print", test_case1_positive_print_below_expectation_does_not_worsen_fundamental),
        ("phase3_company_specific_hypothesis", test_case2_issuer_only_drop_supports_company_specific_hypothesis),
        ("phase3_sector_macro_hypothesis", test_case3_sector_co_move_supports_macro_hypothesis),
        ("phase3_google_rumor_market_only", test_case4_google_rumor_moves_market_layer_not_claim),
        ("phase3_competing_hypotheses", test_case5_three_hypotheses_coexist_without_winner),
        ("phase3_unresolved_research", test_case6_unexplained_price_is_unresolved_research_question),
        ("phase3_constitution_price_and_fact", test_price_cannot_write_fundamental_or_claim_and_hypothesis_is_not_fact),
        ("phase2_supported_path", test_case1_supported_path_can_transmit),
        ("phase2_candidate_stop", test_case2_candidate_edge_stops_downstream_writes),
        ("phase0_shadow", test_case1_unconfirmed_google_order_enters_shadow),
    ):
        try:
            fn()
            checks.append({"name": name, "ok": True, "error": None})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "error": f"{exc}\n{traceback.format_exc()}"})

    store = BrainStore()
    _seed_brain(store, edges=_supported_path())
    result = run_brain_update(ticker="AVGO", item=_capex_event(), store=store, completer=Phase2Completer("path"))
    chain = result["now_chain"]
    complete = collect_phase3_complete_metrics()
    metrics = {
        "now_chain_present": bool(chain),
        "questions": list(NOW_CHAIN_QUESTIONS),
        "answers": chain.get("answers") or {},
        "market_alignment": (chain.get("what_market_is_trading") or {}).get("alignment"),
        "cannot_conclude_mispricing": (chain.get("what_market_is_trading") or {}).get("cannot_conclude_mispricing"),
        "can_affect_claim": (chain.get("path_to_driver_claim") or {}).get("can_affect_claim"),
        "core_claims_unchanged": result.get("core_claims_unchanged"),
        "unsupported_jump_count": result.get("unsupported_jump_count"),
        "unexpected_claim_change_count": result.get("unexpected_claim_change_count"),
        "snapshot_full_brain": result["snapshot"]["full_brain"],
        "market_attentions_in_snapshot": len(result["snapshot"].get("market_attentions") or []),
        "causal_edges_in_snapshot": len(result["snapshot"].get("causal_edges") or []),
        "persisted_market_attentions": len(store.list_market_attentions("AVGO")),
        "expectation_changes": complete["expectation_changes"],
        "hypotheses_created": complete["hypotheses_created"],
        "hypotheses_updated": complete["hypotheses_updated"],
        "competing_hypotheses_per_event": complete["competing_hypotheses_per_event_max"],
        "hypothesis_strengthened": complete["hypothesis_strengthened"],
        "hypothesis_weakened": complete["hypothesis_weakened"],
        "duplicates_prevented": complete["duplicates_prevented"],
        "unresolved_events": complete["unresolved_events"],
        "research_questions": complete["research_questions"],
        "peer_observations_used": complete["peer_observations_used"],
        "price_fundamental_violations": complete["price_fundamental_violations"],
        "price_claim_violations": complete["price_claim_violations"],
    }
    dummy = build_now_chain(event={"title": "x"})
    checklist = {
        "now_chain_answers_four_questions": set((chain.get("answers") or {})) == set(NOW_CHAIN_QUESTIONS),
        "happened": bool((chain.get("answers") or {}).get("what_happened")),
        "why_company": bool((chain.get("why_it_affects_company") or {}).get("exposures") or (chain.get("answers") or {}).get("why_it_affects_company")),
        "causal_path": bool(chain.get("path_to_driver_claim")),
        "market_understands": bool((chain.get("answers") or {}).get("what_market_is_trading")),
        "market_cannot_conclude_mispricing": metrics["cannot_conclude_mispricing"] is True,
        "price_cannot_rewrite_claim": metrics["core_claims_unchanged"] is True,
        "unsupported_jump_zero": int(metrics["unsupported_jump_count"] or 0) == 0,
        "targeted_not_full_brain": metrics["snapshot_full_brain"] is False,
        "expectation_changes": metrics["expectation_changes"] >= 1,
        "market_driver_hypothesis_created": metrics["hypotheses_created"] >= 1,
        "existing_hypothesis_updated": metrics["hypotheses_updated"] >= 1,
        "competing_hypotheses_allowed": metrics["competing_hypotheses_per_event"] >= 3,
        "hypothesis_strengthened_or_weakened": (metrics["hypothesis_strengthened"] + metrics["hypothesis_weakened"]) >= 1,
        "duplicate_hypothesis_prevented": metrics["duplicates_prevented"] >= 1,
        "unresolved_events": metrics["unresolved_events"] >= 1,
        "research_questions": metrics["research_questions"] >= 1,
        "peer_sector_observations_used": metrics["peer_observations_used"] >= 1,
        "price_to_fundamental_violation_zero": metrics["price_fundamental_violations"] == 0,
        "price_to_claim_violation_zero": metrics["price_claim_violations"] == 0,
        "phase0_phase2_regression": all(row["ok"] for row in checks),
        "no_forced_winner_in_dummy": "fell because" not in str(dummy.get("answers") or {}).lower(),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brain_runtime": BRAIN_RUNTIME,
        "phase": "phase3",
        "metrics": metrics,
        "checklist": checklist,
        "regression": checks,
        "all_ok": all(checklist.values()) and all(row["ok"] for row in checks),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Brain v2 Phase 3 validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Runtime: `{BRAIN_RUNTIME}`",
        "",
        "## Now Chain",
        "",
        f"- 发生了什么: {metrics['answers'].get('what_happened')}",
        f"- 为什么会影响公司: {metrics['answers'].get('why_it_affects_company')}",
        f"- 通过什么路径影响 Driver / Claim: {metrics['answers'].get('path_to_driver_claim')}",
        f"- 市场现在怎么理解它: {metrics['answers'].get('what_market_is_trading')}",
        "",
        "## Completion metrics",
        "",
        f"- Expectation changes: {metrics['expectation_changes']}",
        f"- Market Driver Hypothesis created: {metrics['hypotheses_created']}",
        f"- Existing Hypothesis updated: {metrics['hypotheses_updated']}",
        f"- Competing hypotheses / event: {metrics['competing_hypotheses_per_event']}",
        f"- Hypothesis strengthened: {metrics['hypothesis_strengthened']}",
        f"- Hypothesis weakened: {metrics['hypothesis_weakened']}",
        f"- Duplicate hypothesis prevented: {metrics['duplicates_prevented']}",
        f"- Unresolved events: {metrics['unresolved_events']}",
        f"- Research Questions: {metrics['research_questions']}",
        f"- Peer / sector observations used: {metrics['peer_observations_used']}",
        f"- Price → Fundamental violation: {metrics['price_fundamental_violations']}",
        f"- Price → Claim violation: {metrics['price_claim_violations']}",
        "",
        "## Checklist",
        "",
    ]
    for key, value in checklist.items():
        lines.append(f"- [{'x' if value else ' '}] {key}")
    lines.extend(["", f"Overall: {'PASS' if report['all_ok'] else 'FAIL'}", ""])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
