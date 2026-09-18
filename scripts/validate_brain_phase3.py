#!/usr/bin/env python3
"""Phase 3 Now Chain self-validation. Thin market layer only."""

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

from test_brain_phase2 import Phase2Completer, _capex_event, _seed_brain, _supported_path
from test_brain_phase3 import (
    Phase3Completer,
    test_case1_supported_path_answers_happened_why_and_path,
    test_case2_market_attention_persists_without_rewriting_claim,
    test_case4_unexplained_price_is_not_mispricing,
    test_case5_market_attention_cannot_say_mispricing,
)
from test_brain_phase0 import test_case1_unconfirmed_google_order_enters_shadow
from test_brain_phase2 import test_case1_supported_path_can_transmit, test_case2_candidate_edge_stops_downstream_writes

OUT = Path("artifacts/brain_phase3_validation")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    for name, fn in (
        ("phase3_now_chain", test_case1_supported_path_answers_happened_why_and_path),
        ("phase3_market_attention_persist", test_case2_market_attention_persists_without_rewriting_claim),
        ("phase3_unexplained_price", test_case4_unexplained_price_is_not_mispricing),
        ("phase3_no_mispricing_attention", test_case5_market_attention_cannot_say_mispricing),
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
    }
    dummy = build_now_chain(event={"title": "x"})
    checklist = {
        "now_chain_answers_four_questions": set((chain.get("answers") or {})) == set(NOW_CHAIN_QUESTIONS),
        "happened": bool((chain.get("answers") or {}).get("what_happened")),
        "why_company": bool((chain.get("why_it_affects_company") or {}).get("exposures") or (chain.get("answers") or {}).get("why_it_affects_company")),
        "causal_path": bool(chain.get("path_to_driver_claim")),
        "market_is_trading": bool((chain.get("answers") or {}).get("what_market_is_trading")),
        "market_cannot_conclude_mispricing": metrics["cannot_conclude_mispricing"] is True,
        "price_cannot_rewrite_claim": metrics["core_claims_unchanged"] is True,
        "unsupported_jump_zero": int(metrics["unsupported_jump_count"] or 0) == 0,
        "targeted_not_full_brain": metrics["snapshot_full_brain"] is False,
        "no_full_market_driver_system": dummy["what_market_is_trading"]["alignment"] == "unknown",
        "phase0_phase2_regression": all(row["ok"] for row in checks),
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
        f"- 市场现在到底在交易什么: {metrics['answers'].get('what_market_is_trading')}",
        "",
        f"- market alignment: {metrics['market_alignment']}",
        f"- cannot conclude mispricing: {metrics['cannot_conclude_mispricing']}",
        f"- unsupported jump: {metrics['unsupported_jump_count']}",
        f"- snapshot full_brain: {metrics['snapshot_full_brain']}",
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
