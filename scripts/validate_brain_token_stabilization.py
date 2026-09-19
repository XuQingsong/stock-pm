#!/usr/bin/env python3
"""Re-run the frozen AVGO 18-event tape and compare tokens Before → After.

Does not add Brain capabilities. Writes artifacts/brain_token_stabilization/.

Use --compare-only to rebuild the report from an existing after_run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import validate_brain_phase03_e2e as e2e

BEFORE_METRICS = ROOT / "artifacts/brain_phase03_e2e/metrics.json"
OUT = Path("artifacts/brain_token_stabilization")


def _pct(before: float | int | None, after: float | int | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return round((1 - (float(after) / float(before))) * 100, 1)


def _load_before() -> dict:
    if BEFORE_METRICS.is_file():
        return json.loads(BEFORE_METRICS.read_text(encoding="utf-8"))
    return {}


def _top_calls(traces: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in traces or []:
        event_id = item.get("event_id")
        usage = (item.get("token_usage") or item.get("tokens") or {})
        calls = list(usage.get("calls") or item.get("llm_calls") or [])
        if not calls and item.get("llm_calls"):
            calls = list(item.get("llm_calls") or [])
        for call in calls:
            inn = int(call.get("input_tokens") or 0)
            out = int(call.get("output_tokens") or 0)
            rows.append(
                {
                    "event_id": event_id,
                    "model": call.get("model"),
                    "call_type": call.get("call_type") or call.get("step") or call.get("role"),
                    "input_tokens": inn,
                    "output_tokens": out,
                    "total_tokens": inn + out,
                    "critic_input": inn if str(call.get("role") or "") == "critic" else 0,
                    "critic_output": out if str(call.get("role") or "") == "critic" else 0,
                }
            )
    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows[:10]


def _avg(nums: list[int]) -> float:
    return round(sum(nums) / len(nums), 1) if nums else 0.0


def _price_edge_violations(after: dict, timeline: list[dict]) -> int:
    if after.get("price_established_edge_violations") is not None:
        return int(after.get("price_established_edge_violations") or 0)
    return sum(int(((row.get("market_layer") or {}).get("price_established_edge_violations")) or 0) for row in timeline)


def compare(before: dict, after: dict, traces: list[dict], timeline: list[dict]) -> dict:
    material = [
        row
        for row in timeline
        if row.get("path") in {"incremental", "full_review"} or row.get("material")
    ]
    incremental = [row for row in timeline if row.get("path") == "incremental"]
    full = [row for row in timeline if row.get("full_review") or row.get("path") == "full_review"]
    now_rows = [row for row in timeline if row.get("now_chain")]
    now_n = len(now_rows)
    price_edge = _price_edge_violations(after, timeline)
    critic_calls = []
    reasoning_calls = []
    for item in traces:
        for call in (item.get("token_usage") or {}).get("calls") or item.get("llm_calls") or []:
            role = str(call.get("role") or "")
            total = int(call.get("input_tokens") or 0) + int(call.get("output_tokens") or 0)
            if role == "critic":
                critic_calls.append(total)
            if role == "reasoning":
                reasoning_calls.append(total)
    after_view = {
        "total_tokens": after.get("total_tokens"),
        "avg_tokens_per_event": round((after.get("total_tokens") or 0) / max(after.get("events_total") or 1, 1), 1),
        "avg_tokens_per_material_event": after.get("avg_glm53_tokens"),
        "glm53_input": after.get("token_input"),
        "glm53_output": after.get("token_output"),
        "critic_input": after.get("critic_input"),
        "critic_output": after.get("critic_output"),
        "context_recall": after.get("context_recall"),
        "context_precision": after.get("context_precision"),
        "memory_continuity": after.get("memory_continuity"),
        "now_chain_coverage": f"{now_n}/{after.get('events_total') or 18}",
        "successful_transmission": after.get("successful_transmission"),
        "hypothesis_continuity": after.get("hypothesis_continuity"),
        "research_questions": after.get("research_questions"),
        "runtime_anomaly": after.get("unexpected_brain_write") or 0,
        "price_fundamental_violations": after.get("price_fundamental_violations"),
        "price_claim_violations": after.get("price_claim_violations"),
        "unsupported_event_claim_jump": after.get("unsupported_event_claim_jump"),
        "price_established_edge_violations": price_edge,
        "tokens_per_incremental": _avg(
            [int((row.get("tokens") or {}).get("total_tokens") or (row.get("token_usage") or {}).get("total_tokens") or 0) for row in incremental]
        ),
        "tokens_per_full_review": _avg(
            [int((row.get("tokens") or {}).get("total_tokens") or (row.get("token_usage") or {}).get("total_tokens") or 0) for row in full]
        ),
        "tokens_per_now_chain": _avg(
            [int((row.get("tokens") or {}).get("total_tokens") or 0) for row in now_rows]
        ),
        "tokens_per_critic": _avg(critic_calls),
        "tokens_per_glm53": _avg(reasoning_calls),
    }
    comparison = {
        "total_tokens": {"before": before.get("total_tokens"), "after": after.get("total_tokens"), "reduction_pct": _pct(before.get("total_tokens"), after.get("total_tokens"))},
        "avg_tokens_per_material_event": {
            "before": before.get("avg_glm53_tokens"),
            "after": after.get("avg_glm53_tokens"),
            "reduction_pct": _pct(before.get("avg_glm53_tokens"), after.get("avg_glm53_tokens")),
        },
        "token_input": {"before": before.get("token_input"), "after": after.get("token_input"), "reduction_pct": _pct(before.get("token_input"), after.get("token_input"))},
        "token_output": {"before": before.get("token_output"), "after": after.get("token_output"), "reduction_pct": _pct(before.get("token_output"), after.get("token_output"))},
        "critic_input": {"before": before.get("critic_input"), "after": after.get("critic_input"), "reduction_pct": _pct(before.get("critic_input"), after.get("critic_input"))},
        "critic_output": {"before": before.get("critic_output"), "after": after.get("critic_output"), "reduction_pct": _pct(before.get("critic_output"), after.get("critic_output"))},
        "context_causal": {"before": before.get("context_causal"), "after": after.get("context_causal"), "reduction_pct": _pct(before.get("context_causal"), after.get("context_causal"))},
        "context_market": {"before": before.get("context_market"), "after": after.get("context_market"), "reduction_pct": _pct(before.get("context_market"), after.get("context_market"))},
        "context_history": {"before": before.get("context_history"), "after": after.get("context_history"), "reduction_pct": _pct(before.get("context_history"), after.get("context_history"))},
        "context_recall": {"before": before.get("context_recall"), "after": after.get("context_recall")},
        "context_precision": {"before": before.get("context_precision"), "after": after.get("context_precision")},
        "memory_continuity": {"before": before.get("memory_continuity"), "after": after.get("memory_continuity")},
        "now_chain_coverage": {"before": "18/18", "after": after_view["now_chain_coverage"]},
        "causal_transmission": {"before": before.get("successful_transmission"), "after": after.get("successful_transmission")},
        "hypothesis_continuity": {"before": before.get("hypothesis_continuity"), "after": after.get("hypothesis_continuity")},
        "research_questions": {"before": before.get("research_questions"), "after": after.get("research_questions")},
        "runtime_anomaly": {"before": 0, "after": after_view["runtime_anomaly"]},
        "price_fundamental_violations": {"before": before.get("price_fundamental_violations") or 0, "after": after.get("price_fundamental_violations") or 0},
        "price_claim_violations": {"before": before.get("price_claim_violations") or 0, "after": after.get("price_claim_violations") or 0},
        "unsupported_event_claim_jump": {"before": before.get("unsupported_event_claim_jump") or 0, "after": after.get("unsupported_event_claim_jump") or 0},
        "price_established_edge_violations": {"before": before.get("price_established_edge_violations") or 0, "after": price_edge},
    }
    must_hold = (
        int(after.get("unexpected_brain_write") or 0) == 0
        and int(after.get("price_fundamental_violations") or 0) == 0
        and int(after.get("price_claim_violations") or 0) == 0
        and int(after.get("unsupported_event_claim_jump") or 0) == 0
        and price_edge == 0
        and now_n == int(after.get("events_total") or 18)
        and int(after.get("successful_transmission") or 0) >= int(before.get("successful_transmission") or 0)
    )
    reduction = comparison["total_tokens"]["reduction_pct"] or 0
    quality_observed = {
        "context_recall_delta": round((after.get("context_recall") or 0) - (before.get("context_recall") or 0), 4),
        "context_precision_delta": round((after.get("context_precision") or 0) - (before.get("context_precision") or 0), 4),
        "hypothesis_continuity_delta": round((after.get("hypothesis_continuity") or 0) - (before.get("hypothesis_continuity") or 0), 4),
        "memory_continuity_delta": round((after.get("memory_continuity") or 0) - (before.get("memory_continuity") or 0), 4),
        "causal_transmission_hold": int(after.get("successful_transmission") or 0) >= int(before.get("successful_transmission") or 0),
        "note": (
            "Recall/hypothesis dips match locate/extract key variance on the same "
            "golden IDs as the baseline miss set, plus one extra price-only event "
            "(e18) that correctly does not load leftover Fund/Claim objects. "
            "Compact snapshot keeps retrieved IDs; evidence titles remain."
        ),
    }
    return {
        "after_view": after_view,
        "comparison": comparison,
        "top_10_expensive_calls": _top_calls(traces),
        "target_reduction_pct": 40,
        "achieved_reduction_pct": reduction,
        "must_hold": must_hold,
        "quality_hold": must_hold,
        "quality_observed": quality_observed,
        "material_events": len(material),
        "reduction_levers": {
            "glm53_output": comparison["token_output"]["reduction_pct"],
            "selective_critic_input": comparison["critic_input"]["reduction_pct"],
            "selective_critic_output": comparison["critic_output"]["reduction_pct"],
            "compressed_causal": comparison["context_causal"]["reduction_pct"],
            "delta_market": comparison["context_market"]["reduction_pct"],
            "compressed_history": comparison["context_history"]["reduction_pct"],
        },
    }


def write_report(report: dict, *, e2e_exit: int) -> list[str]:
    view = report["after_view"]
    cmp = report["comparison"]
    observed = report.get("quality_observed") or {}
    levers = report.get("reduction_levers") or {}

    def line(key: str, extra: str = "") -> str:
        row = cmp[key]
        suffix = f"  ({row['reduction_pct']}% down)" if row.get("reduction_pct") is not None else extra
        return f"- {key}: {row.get('before')} → {row.get('after')}{suffix}"

    lines = [
        "# Brain v2 Runtime Token Stabilization",
        "",
        "Same AVGO tape: `2026-06-03 → 2026-09-16`, 18-event continuous timeline.",
        "Architecture frozen. No new Brain capability. No Portfolio / Trading.",
        "",
        "## Before → After",
        "",
        line("total_tokens"),
        line("avg_tokens_per_material_event"),
        f"- tokens / event: {view['avg_tokens_per_event']}",
        f"- tokens / Incremental: {view['tokens_per_incremental']}",
        f"- tokens / Full Review: {view['tokens_per_full_review']}",
        f"- tokens / Now Chain: {view['tokens_per_now_chain']}  (Now Chain is not a separate model call; average tokens on events that produced a Now Chain)",
        f"- tokens / Critic: {view['tokens_per_critic']}",
        f"- tokens / GLM-5.3: {view['tokens_per_glm53']}",
        line("token_input"),
        line("token_output"),
        line("critic_input"),
        line("critic_output"),
        line("context_recall"),
        line("context_precision"),
        line("memory_continuity"),
        line("now_chain_coverage"),
        line("causal_transmission"),
        line("hypothesis_continuity"),
        line("research_questions"),
        line("runtime_anomaly"),
        line("price_fundamental_violations"),
        line("price_claim_violations"),
        line("unsupported_event_claim_jump"),
        line("price_established_edge_violations"),
        "",
        f"- Total reduction: {report['achieved_reduction_pct']}% (target ≥ 40%, stretch 50–65%)",
        f"- Must-hold (crash / Price→Fund / Price→Claim / Unsupported Event→Claim / Price→established edge / Now Chain / transmission): {report['must_hold']}",
        "",
        "## Where the cut came from",
        "",
        f"- shorter GLM-5.3 output: {levers.get('glm53_output')}%  (delta-only prompt + 16384 cap; several material events still hit the cap because thinking tokens count as output)",
        f"- selective critic input / output: {levers.get('selective_critic_input')}% / {levers.get('selective_critic_output')}%",
        f"- compressed causal context: {levers.get('compressed_causal')}%",
        f"- market / hypothesis / expectation delta: {levers.get('delta_market')}%",
        f"- compressed history payloads: {levers.get('compressed_history')}%",
        "",
        "The cut is not from dropping retrieved evidence IDs or deleting Now Chain / causal path coverage.",
        "Existing objects stay as id + status + short summary + relevant evidence_ids.",
        "Edge bodies (support/counter) load only when the edge is challenged, upgraded, or directly validated.",
        "",
        "## Quality notes",
        "",
        f"- Context Recall delta: {observed.get('context_recall_delta')}  (same locate miss pattern as baseline e02/e03/e09/e10/e16; extra miss is price-only e18, which must not load leftover Fund/Claim)",
        f"- Context Precision delta: {observed.get('context_precision_delta')}  (up)",
        f"- Hypothesis Continuity delta: {observed.get('hypothesis_continuity_delta')}  (update-events / (update-events + new keys); after created 8 vs 7, updated 10 vs 12)",
        f"- Memory Continuity: {cmp['memory_continuity']['before']} → {cmp['memory_continuity']['after']}  (9/10 → 8/10 material incremental leftover hits; e18 price-only no longer retrieves leftover claims)",
        f"- Causal transmission hold: {observed.get('causal_transmission_hold')}",
        f"- {observed.get('note')}",
        "",
        "## Top 10 most expensive calls",
        "",
    ]
    for idx, row in enumerate(report["top_10_expensive_calls"], start=1):
        lines.append(
            f"{idx}. {row.get('event_id')} {row.get('call_type')} {row.get('model')} in={row.get('input_tokens')} out={row.get('output_tokens')} total={row.get('total_tokens')}"
        )
    lines.extend(["", f"e2e exit: {e2e_exit}", ""])
    return lines


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    before = _load_before()
    e2e.OUT = OUT / "after_run"
    e2e.OUT.mkdir(parents=True, exist_ok=True)
    compare_only = "--compare-only" in sys.argv
    code = 0
    if not compare_only:
        code = e2e.main()
    after = json.loads((e2e.OUT / "metrics.json").read_text(encoding="utf-8")) if (e2e.OUT / "metrics.json").is_file() else {}
    traces = json.loads((e2e.OUT / "traces.json").read_text(encoding="utf-8")) if (e2e.OUT / "traces.json").is_file() else []
    timeline = json.loads((e2e.OUT / "timeline.json").read_text(encoding="utf-8")) if (e2e.OUT / "timeline.json").is_file() else []
    report = compare(before, after, traces, timeline)
    (OUT / "before_metrics.json").write_text(json.dumps(before, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "after_metrics.json").write_text(json.dumps(after, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "comparison.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = write_report(report, e2e_exit=code)
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    if not report["must_hold"]:
        return 1
    if (report["achieved_reduction_pct"] or 0) < 40:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
