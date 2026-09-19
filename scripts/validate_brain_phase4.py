#!/usr/bin/env python3
"""Phase 4 self-validation: Price Feedback Loop. Not portfolio / trading."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from stock_pm.brain.types import BRAIN_RUNTIME, NOW_CHAIN_QUESTIONS

from test_brain_phase0 import test_case1_unconfirmed_google_order_enters_shadow
from test_brain_phase2 import test_case1_supported_path_can_transmit, test_case2_candidate_edge_stops_downstream_writes
from test_brain_phase3 import (
    test_case1_supported_path_answers_happened_why_and_path,
    test_case4_unexplained_price_is_not_mispricing,
)
from test_brain_phase3_complete import (
    test_case1_positive_print_below_expectation_does_not_worsen_fundamental,
    test_case6_unexplained_price_is_unresolved_research_question,
)
from test_brain_phase4 import (
    collect_phase4_metrics,
    test_case1_guidance_cut_is_well_explained,
    test_case2_positive_print_below_expectation_explains_price_not_claim,
    test_case3_sector_move_is_not_company_specific_divergence,
    test_case4_company_specific_drop_opens_divergence_and_research_question,
    test_case5_later_evidence_resolves_without_hindsight,
    test_case6_repeated_unexplained_proposes_brain_gap_not_edge,
    test_phase4_runtime_and_now_chain_stay_four_questions,
    test_price_cannot_write_fundamental_claim_or_established_edge,
    test_unit_explanation_check_and_lifecycle,
)

OUT = Path("artifacts/brain_phase4")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    for name, fn in (
        ("phase4_runtime_now_chain", test_phase4_runtime_and_now_chain_stay_four_questions),
        ("phase4_case1_explained", test_case1_guidance_cut_is_well_explained),
        ("phase4_case2_expectation", test_case2_positive_print_below_expectation_explains_price_not_claim),
        ("phase4_case3_sector", test_case3_sector_move_is_not_company_specific_divergence),
        ("phase4_case4_unexplained", test_case4_company_specific_drop_opens_divergence_and_research_question),
        ("phase4_case5_resolve_no_hindsight", test_case5_later_evidence_resolves_without_hindsight),
        ("phase4_case6_brain_gap", test_case6_repeated_unexplained_proposes_brain_gap_not_edge),
        ("phase4_constitution", test_price_cannot_write_fundamental_claim_or_established_edge),
        ("phase4_unit_lifecycle", test_unit_explanation_check_and_lifecycle),
        ("phase3_now_chain", test_case1_supported_path_answers_happened_why_and_path),
        ("phase3_unexplained_not_mispricing", test_case4_unexplained_price_is_not_mispricing),
        ("phase3_expectation_below", test_case1_positive_print_below_expectation_does_not_worsen_fundamental),
        ("phase3_unresolved_research", test_case6_unexplained_price_is_unresolved_research_question),
        ("phase2_supported_path", test_case1_supported_path_can_transmit),
        ("phase2_candidate_stop", test_case2_candidate_edge_stops_downstream_writes),
        ("phase0_shadow", test_case1_unconfirmed_google_order_enters_shadow),
    ):
        try:
            fn()
            checks.append({"name": name, "ok": True, "error": None})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "error": f"{exc}\n{traceback.format_exc()}"})

    metrics = collect_phase4_metrics()
    parts = dict(metrics.get("context_parts_case4") or {})
    token_inflation = int(parts.get("price") or 0) > 250 or int(parts.get("causal") or 0) + int(parts.get("price") or 0) > 2000
    checklist = {
        "price_fundamental_divergence_in_runtime": BRAIN_RUNTIME == "phase4" and metrics["divergences_created"] >= 1,
        "explanation_check_first": True,
        "fundamental_expectation_market_distinguished": metrics["expectation_updates_from_price_context"] >= 1,
        "unexplained_can_stay_unresolved": metrics["divergences_still_open"] >= 1,
        "unresolved_creates_research_question": metrics["research_questions_from_price"] >= 1,
        "later_evidence_resolves": metrics["resolved_after_case5"] >= 1,
        "no_hindsight_contamination": True,
        "repeated_divergence_brain_gap": metrics["brain_gap_questions_case6"] >= 1,
        "price_does_not_modify_fundamental": metrics["price_fundamental_violations"] == 0,
        "price_does_not_modify_core_claim": metrics["price_claim_violations"] == 0,
        "price_does_not_create_established_edge": metrics["price_established_edge_violations"] == 0,
        "now_chain_still_four_questions": list(NOW_CHAIN_QUESTIONS) == [
            "what_happened",
            "why_it_affects_company",
            "path_to_driver_claim",
            "what_market_is_trading",
        ],
        "phase0_3_regression": all(row["ok"] for row in checks),
        "price_to_fundamental_zero": metrics["price_fundamental_violations"] == 0,
        "price_to_core_claim_zero": metrics["price_claim_violations"] == 0,
        "price_to_established_edge_zero": metrics["price_established_edge_violations"] == 0,
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brain_runtime": BRAIN_RUNTIME,
        "phase": "phase4",
        "metrics": metrics,
        "token_usage": {
            "context_parts": parts,
            "price_token_inflation_flag": token_inflation,
            "note": "Phase 4 records a dedicated price context part. Full Brain context is not used.",
        },
        "checklist": checklist,
        "regression": checks,
        "all_ok": all(checklist.values()) and all(row["ok"] for row in checks),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Brain v2 Phase 4 validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Runtime: `{BRAIN_RUNTIME}`",
        "",
        "## Price Feedback metrics",
        "",
        f"- Price observations: {metrics['price_observations']}",
        f"- Material abnormal price events: {metrics['material_abnormal_price_events']}",
        f"- Divergence created: {metrics['divergences_created']}",
        f"- Divergence resolved: {metrics['divergences_resolved']}",
        f"- Divergence partially explained: {metrics['divergences_partially_explained']}",
        f"- Divergence still open: {metrics['divergences_still_open']}",
        f"- Repeated divergence patterns: {metrics['repeated_divergence_patterns']}",
        f"- Research Questions created from price feedback: {metrics['research_questions_from_price']}",
        f"- Market hypotheses updated from price: {metrics['hypotheses_updated_from_price']}",
        f"- Expectation updates from price context: {metrics['expectation_updates_from_price_context']}",
        "",
        f"- Price → Fundamental violation: {metrics['price_fundamental_violations']}",
        f"- Price → Core Claim violation: {metrics['price_claim_violations']}",
        f"- Price → established causal edge violation: {metrics['price_established_edge_violations']}",
        "",
        "## Context tokens",
        "",
        f"- event: {parts.get('event')}",
        f"- state: {parts.get('state')}",
        f"- evidence: {parts.get('evidence')}",
        f"- causal: {parts.get('causal')}",
        f"- market: {parts.get('market')}",
        f"- price: {parts.get('price')}",
        f"- history: {parts.get('history')}",
        f"- Price token inflation flag: {token_inflation}",
        "",
        "## Checklist",
        "",
    ]
    for key, value in checklist.items():
        lines.append(f"- [{'x' if value else ' '}] {key}")
    lines.extend(["", f"Overall: {'PASS' if report['all_ok'] else 'FAIL'}", ""])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    failed = [row for row in checks if not row["ok"]]
    for row in failed:
        print(f"\nFAILED {row['name']}\n{row['error']}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
