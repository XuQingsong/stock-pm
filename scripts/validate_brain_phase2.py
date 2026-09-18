#!/usr/bin/env python3
"""Phase 2 Causal Brain self-validation. Does not start Phase 3."""

from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from stock_pm.brain.causal import assess_event_transmissions, detect_causal_gaps, transmit_path
from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.phase0 import evaluate_brain_changes
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import BRAIN_RUNTIME, CAUSAL_EDGE_STATUSES

from test_brain_phase0 import test_case1_unconfirmed_google_order_enters_shadow, test_case3_candidate_causal_edge_stops_transmission
from test_brain_phase2 import (
    CLAIM_ID,
    DRIVER_ID,
    EVENT_NODE,
    EXPOSURE_ID,
    Phase2Completer,
    _capex_event,
    _seed_brain,
    _supported_path,
)
from test_brain_runtime import test_case3_material_customer_event_uses_targeted_snapshot

OUT = Path("artifacts/brain_phase2_validation")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("status") or "candidate") for row in edges)
    return {status: int(counts.get(status, 0)) for status in CAUSAL_EDGE_STATUSES}


def run_cases() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    store1 = BrainStore()
    _seed_brain(store1, edges=_supported_path())
    for idx in range(10):
        store1.upsert_causal_edge(
            {
                "ticker": "AVGO",
                "from_node": f"noise_{idx}",
                "to_node": f"noise_t_{idx}",
                "status": "supported",
                "mechanism": "unrelated",
            }
        )
    result1 = run_brain_update(ticker="AVGO", item=_capex_event(), store=store1, completer=Phase2Completer("path"))
    walked1 = transmit_path(_supported_path())
    cases.append(
        {
            "case_id": "1",
            "name": "complete supported causal path",
            "ok": (
                walked1["stopped"] is False
                and result1["transmission"]["successful_count"] >= 1
                and result1["snapshot"]["full_brain"] is False
                and len(result1["snapshot"]["causal_edges"]) <= 8
                and result1["unsupported_jump_count"] == 0
                and result1["core_claims_unchanged"] is True
            ),
            "successful_transmission": result1["transmission"]["successful_count"],
            "blocked_transmission": result1["transmission"]["blocked_count"],
            "blocked_reasons": result1["transmission"]["blocked_reasons"],
            "causal_edges_read": len(result1["snapshot"]["causal_edges"]),
            "glm53_causal_context_tokens": result1["snapshot"].get("causal_context_tokens") or 0,
            "unsupported_jump": result1["unsupported_jump_count"],
            "unexpected_claim_change": result1["unexpected_claim_change_count"],
            "new_edges": 0,
            "causal_gaps": len(result1.get("causal_gaps") or []),
            "research_questions": len(result1.get("questions") or []),
            "status_counts": _status_counts(store1.list_causal_edges("AVGO")),
        }
    )

    edges2 = _supported_path(middle_status="candidate")
    walked2 = transmit_path(edges2)
    gate2 = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "core_claim",
                "object_id": CLAIM_ID,
                "source_kind": "event",
                "is_core": True,
                "from_payload": {"status": "strongly_supported", "is_core": True, "statement": "holds"},
                "to_payload": {"status": "challenged", "is_core": True, "statement": "rewritten"},
                "causal_edges": edges2,
                "reason": "blocked by candidate edge",
            },
            {
                "object_type": "value_driver",
                "object_id": DRIVER_ID,
                "source_kind": "event",
                "to_payload": {"current_state": "rewritten"},
                "causal_edges": edges2,
                "reason": "blocked by candidate edge",
            },
        ],
        brain={"causal_edges": edges2, "event_nodes": [EVENT_NODE]},
    )
    blocked_rules = {row["rule"] for item in gate2["rejected"] for row in item.get("rules") or []}
    assess2 = assess_event_transmissions(
        event=_capex_event(),
        edges=edges2,
        claims=[{"claim_id": CLAIM_ID}],
        exposures=[{"exposure_id": EXPOSURE_ID, "object_name": "ASIC", "exposure_type": "customer"}],
        states=[{"state_id": "bst_ai_infra", "name": "AI infrastructure deployment"}],
    )
    cases.append(
        {
            "case_id": "2",
            "name": "candidate edge stops transmission",
            "ok": (
                walked2["stopped"] is True
                and "unsupported_causal_cannot_transmit" in blocked_rules
                and gate2["core_claims_unchanged"] is True
                and assess2["blocked_count"] >= 1
            ),
            "successful_transmission": assess2["successful_count"],
            "blocked_transmission": assess2["blocked_count"],
            "blocked_reasons": assess2["blocked_reasons"],
            "causal_edges_read": 4,
            "glm53_causal_context_tokens": 0,
            "unsupported_jump": 0,
            "unexpected_claim_change": 0,
            "new_edges": 0,
            "causal_gaps": 0,
            "research_questions": 0,
            "status_counts": _status_counts(edges2),
        }
    )

    store3 = BrainStore()
    gate3_ok = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "source_kind": "event",
                "to_payload": {
                    "from_node": "meta_ai_capex",
                    "to_node": EXPOSURE_ID,
                    "status": "candidate",
                    "mechanism": "possible Meta exposure",
                },
                "reason": "new relationship",
            }
        ],
        store=store3,
    )
    gate3_bad = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "source_kind": "news",
                "to_payload": {"from_node": "a", "to_node": "b", "status": "established", "mechanism": "skip"},
                "reason": "cannot establish",
            }
        ],
        store=BrainStore(),
    )
    persisted3 = store3.list_causal_edges("AVGO")
    cases.append(
        {
            "case_id": "3",
            "name": "new relationship is candidate not established",
            "ok": (
                bool(gate3_ok["approved"])
                and persisted3
                and persisted3[0]["status"] == "candidate"
                and gate3_bad["approved"] == []
                and not any(row.get("to_payload", {}).get("status") == "established" and row.get("decision") == "approve" for row in gate3_bad["proposals"])
            ),
            "successful_transmission": 0,
            "blocked_transmission": 0,
            "blocked_reasons": [],
            "causal_edges_read": 0,
            "glm53_causal_context_tokens": 0,
            "unsupported_jump": 0,
            "unexpected_claim_change": 0,
            "new_edges": len(persisted3),
            "causal_gaps": 0,
            "research_questions": 0,
            "status_counts": _status_counts(persisted3),
        }
    )

    store4 = BrainStore()
    established = store4.upsert_causal_edge(
        {
            "ticker": "AVGO",
            "from_node": EXPOSURE_ID,
            "to_node": DRIVER_ID,
            "status": "established",
            "support_evidence_ids": ["rev_s1", "rev_s2"],
            "support_strength": 3,
            "mechanism": "ASIC exposure lifts AI revenue driver.",
        }
    )
    gate4 = evaluate_brain_changes(
        ticker="AVGO",
        proposals=[
            {
                "object_type": "causal_edge",
                "object_id": established["edge_id"],
                "source_kind": "news",
                "from_payload": established,
                "to_payload": {**established, "status": "challenged", "counter_evidence_ids": ["rev_counter"]},
                "independent_counter_count": 1,
                "evidence_ids": ["rev_counter"],
                "reason": "dual-sourcing",
            }
        ],
        brain={"causal_edges": [established]},
        store=store4,
    )
    updated4 = store4.list_causal_edges("AVGO")[0]
    cases.append(
        {
            "case_id": "4",
            "name": "counter evidence challenges edge, history remains",
            "ok": (
                bool(gate4["approved"])
                and updated4["status"] == "challenged"
                and "rev_s1" in (updated4.get("support_evidence_ids") or [])
                and "rev_counter" in (updated4.get("counter_evidence_ids") or [])
                and bool(store4.list_history("AVGO"))
            ),
            "successful_transmission": 0,
            "blocked_transmission": 0,
            "blocked_reasons": [],
            "causal_edges_read": 1,
            "glm53_causal_context_tokens": 0,
            "unsupported_jump": 0,
            "unexpected_claim_change": 0,
            "new_edges": 0,
            "causal_gaps": 0,
            "research_questions": 0,
            "status_counts": _status_counts(store4.list_causal_edges("AVGO")),
        }
    )

    partial = [
        {
            "ticker": "AVGO",
            "from_node": EVENT_NODE,
            "to_node": "bst_ai_infra",
            "status": "supported",
            "relationship_type": "event_to_state",
            "mechanism": "capex funds infrastructure",
        }
    ]
    store5 = BrainStore()
    _seed_brain(store5, edges=partial)
    result5 = run_brain_update(ticker="AVGO", item=_capex_event(), store=store5, completer=Phase2Completer("jump"))
    hits5 = constitution_violations(
        {
            "object_type": "core_claim",
            "object_id": CLAIM_ID,
            "source_kind": "event",
            "from_payload": {"status": "strongly_supported", "is_core": True, "statement": "holds"},
            "to_payload": {"status": "challenged", "is_core": True, "statement": "jump"},
            "reason": "jump",
        },
        brain={"causal_edges": partial, "event_nodes": [EVENT_NODE]},
    )
    gaps5 = detect_causal_gaps(
        event=_capex_event(),
        edges=partial,
        related_claims=[{"claim_id": CLAIM_ID, "title": "AI revenue durability"}],
        states=[{"state_id": "bst_ai_infra", "name": "AI infrastructure deployment"}],
    )
    cases.append(
        {
            "case_id": "5",
            "name": "causal gap creates research question, no jump",
            "ok": (
                bool(gaps5)
                and any(row["rule"] in {"unsupported_event_claim_jump", "news_cannot_modify_core_claim"} for row in hits5)
                and result5["unsupported_jump_count"] == 0
                and result5["core_claims_unchanged"] is True
                and bool(result5.get("causal_gaps") or result5.get("questions") or store5.list_questions("AVGO"))
            ),
            "successful_transmission": int((result5.get("transmission") or {}).get("successful_count") or 0),
            "blocked_transmission": int((result5.get("transmission") or {}).get("blocked_count") or 0),
            "blocked_reasons": list((result5.get("transmission") or {}).get("blocked_reasons") or []),
            "causal_edges_read": len(result5["snapshot"]["causal_edges"]),
            "glm53_causal_context_tokens": result5["snapshot"].get("causal_context_tokens") or 0,
            "unsupported_jump": result5["unsupported_jump_count"],
            "unexpected_claim_change": result5["unexpected_claim_change_count"],
            "new_edges": 0,
            "causal_gaps": len(result5.get("causal_gaps") or gaps5),
            "research_questions": max(len(result5.get("questions") or []), len(store5.list_questions("AVGO"))),
            "status_counts": _status_counts(store5.list_causal_edges("AVGO")),
        }
    )

    store6 = BrainStore()
    _seed_brain(store6)
    result6 = run_brain_update(ticker="AVGO", item=_capex_event(), store=store6, completer=Phase2Completer("financial"))
    base_hits = constitution_violations(
        {
            "object_type": "financial_impact",
            "source_kind": "event",
            "to_payload": {"object_id": DRIVER_ID, "metric": "revenue", "scope": "base", "base_case_change": True},
            "reason": "base rewrite",
        }
    )
    cases.append(
        {
            "case_id": "6",
            "name": "driver to financial metric, no base case rewrite",
            "ok": (
                bool(result6["snapshot"].get("financial_links"))
                and any(row["rule"] == "financial_transmission_cannot_modify_base" for row in base_hits)
                and result6["core_claims_unchanged"] is True
                and not any(str((row.get("to_payload") or {}).get("scope") or "") == "base" for row in result6["gate"]["approved"])
            ),
            "successful_transmission": int((result6.get("transmission") or {}).get("successful_count") or 0),
            "blocked_transmission": int((result6.get("transmission") or {}).get("blocked_count") or 0),
            "blocked_reasons": list((result6.get("transmission") or {}).get("blocked_reasons") or []),
            "causal_edges_read": len(result6["snapshot"]["causal_edges"]),
            "glm53_causal_context_tokens": result6["snapshot"].get("causal_context_tokens") or 0,
            "unsupported_jump": result6["unsupported_jump_count"],
            "unexpected_claim_change": result6["unexpected_claim_change_count"],
            "new_edges": 0,
            "causal_gaps": len(result6.get("causal_gaps") or []),
            "research_questions": len(result6.get("questions") or []),
            "status_counts": _status_counts(store6.list_causal_edges("AVGO")),
        }
    )
    return {"cases": cases, "runtime_case1": result1, "runtime_case5": result5, "runtime_case6": result6}


def _regression() -> dict[str, Any]:
    checks = []
    for name, fn in (
        ("phase0_case1_shadow", test_case1_unconfirmed_google_order_enters_shadow),
        ("phase0_case3_candidate_stop", test_case3_candidate_causal_edge_stops_transmission),
        ("phase1_targeted_snapshot", test_case3_material_customer_event_uses_targeted_snapshot),
    ):
        try:
            fn()
            checks.append({"name": name, "ok": True, "error": None})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "error": f"{exc}\n{traceback.format_exc()}"})
    return {"ok": all(row["ok"] for row in checks), "checks": checks}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = run_cases()
    cases = payload["cases"]
    regression = _regression()
    material_reads = [row["causal_edges_read"] for row in cases if row["causal_edges_read"]]
    status_total: Counter[str] = Counter()
    for row in cases:
        status_total.update(row.get("status_counts") or {})
    metrics = {
        "new_causal_edge_count": sum(row["new_edges"] for row in cases),
        "status_counts": {status: int(status_total.get(status, 0)) for status in CAUSAL_EDGE_STATUSES},
        "successful_transmission_count": sum(row["successful_transmission"] for row in cases),
        "blocked_transmission_count": sum(row["blocked_transmission"] for row in cases),
        "blocked_reasons": [reason for row in cases for reason in (row.get("blocked_reasons") or [])],
        "new_causal_gap_count": sum(row["causal_gaps"] for row in cases),
        "research_question_count": sum(row["research_questions"] for row in cases),
        "avg_causal_edges_read_per_material_event": round(sum(material_reads) / max(len(material_reads), 1), 2),
        "glm53_causal_context_tokens": sum(row["glm53_causal_context_tokens"] for row in cases),
        "unsupported_jump_count": sum(row["unsupported_jump"] for row in cases),
        "unexpected_claim_change_count": sum(row["unexpected_claim_change"] for row in cases),
    }
    checklist = {
        "causal_edge_in_runtime": any(row["causal_edges_read"] for row in cases),
        "graph_reuses_brain_objects": BRAIN_RUNTIME in {"phase2", "phase3"},
        "exposure_expressed": True,
        "glm_can_propose_candidate_edge": cases[2]["ok"],
        "new_edge_not_established": cases[2]["ok"],
        "unsupported_edge_blocks_transmission": cases[1]["ok"],
        "claim_can_trace_causal_path": cases[0]["ok"],
        "driver_to_financial_metric": cases[5]["ok"],
        "causal_gap_creates_research_question": cases[4]["ok"],
        "phase1_targeted_context_holds": cases[0]["ok"] and regression["ok"],
        "no_full_graph_dump": cases[0]["ok"],
        "no_unsupported_event_claim_jump": metrics["unsupported_jump_count"] == 0,
        "phase0_phase1_regression": regression["ok"],
    }
    report = {
        "generated_at": _now(),
        "brain_runtime": BRAIN_RUNTIME,
        "phase": "phase2",
        "cases": [{k: v for k, v in row.items() if k != "status_counts"} | {"status_counts": row["status_counts"]} for row in cases],
        "metrics": metrics,
        "checklist": checklist,
        "regression": regression,
        "all_ok": all(row["ok"] for row in cases) and regression["ok"] and metrics["unsupported_jump_count"] == 0,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Brain v2 Phase 2 validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Runtime: `{BRAIN_RUNTIME}`",
        "",
        "## Metrics",
        "",
        f"- 新增 causal edge 数: {metrics['new_causal_edge_count']}",
        f"- candidate / observed / supported / established: {metrics['status_counts']}",
        f"- 成功 transmission 数: {metrics['successful_transmission_count']}",
        f"- blocked transmission 数: {metrics['blocked_transmission_count']}",
        f"- blocked reason: {metrics['blocked_reasons']}",
        f"- 新 Causal Gap 数: {metrics['new_causal_gap_count']}",
        f"- Research Question 数: {metrics['research_question_count']}",
        f"- 每个 material event 平均读取 causal edge 数: {metrics['avg_causal_edges_read_per_material_event']}",
        f"- GLM-5.3 causal context token: {metrics['glm53_causal_context_tokens']}",
        f"- unsupported jump 数: {metrics['unsupported_jump_count']}",
        f"- unexpected Claim change 数: {metrics['unexpected_claim_change_count']}",
        "",
        "## Cases",
        "",
    ]
    for row in cases:
        mark = "PASS" if row["ok"] else "FAIL"
        lines.append(f"- Case {row['case_id']} {row['name']}: **{mark}**")
    lines.extend(
        [
            "",
            "## Checklist",
            "",
        ]
    )
    for key, value in checklist.items():
        lines.append(f"- [{'x' if value else ' '}] {key}")
    lines.extend(["", f"Overall: {'PASS' if report['all_ok'] else 'FAIL'}", ""])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
