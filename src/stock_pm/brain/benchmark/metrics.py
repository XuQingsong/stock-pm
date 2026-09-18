"""Deterministic benchmark metrics. No automatic winner."""

from __future__ import annotations

from typing import Any

from stock_pm.brain.claim_integrity import (
    extract_factual_tokens,
    is_fact_restatement,
    reject_unknown_ids,
    token_supported,
)
from stock_pm.research.llm_reason import compact_text


HUMAN_SCORE_FIELDS = (
    "driver_recall",
    "driver_precision",
    "core_claim_quality",
    "event_routing",
    "transmission_quality",
    "counter_reasoning",
    "evidence_grounding",
    "overall",
)

COST_RATES = {
    "deepseek-chat": {"input": 0.14, "output": 0.28, "ccy": "USD"},
    "deepseek-flash": {"input": 0.14, "output": 0.28, "ccy": "USD"},
    "qwen3.8-max": {"input": 2.5, "output": 20.0, "ccy": "CNY"},
    "ZHIPU/GLM-5.3": {"input": 4.0, "output": 16.0, "ccy": "CNY"},
    "glm-5.3": {"input": 4.0, "output": 16.0, "ccy": "CNY"},
    "kimi/kimi-k3": {"input": 20.0, "output": 100.0, "ccy": "CNY"},
    "kimi-k3": {"input": 20.0, "output": 100.0, "ccy": "CNY"},
}


def empty_human_scores() -> dict[str, None]:
    return {key: None for key in HUMAN_SCORE_FIELDS}


def _norm_name(value: Any) -> str:
    return compact_text(value or "", 80).lower()


def driver_names(payload: dict[str, Any] | None) -> list[str]:
    names = []
    for row in (payload or {}).get("value_drivers") or []:
        name = _norm_name((row or {}).get("driver_name"))
        if name and name not in names:
            names.append(name)
    return names


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    rates = COST_RATES.get(model) or COST_RATES.get(model.split("/")[-1] if "/" in model else model)
    if not rates or rates.get("input") is None:
        return {"amount": None, "ccy": None, "note": "no rate table for this model id"}
    amount = (input_tokens / 1_000_000) * float(rates["input"]) + (output_tokens / 1_000_000) * float(rates["output"])
    return {"amount": round(amount, 6), "ccy": rates["ccy"], "note": "indicative, not an invoice"}


def count_invalid_ids(values: Any, allowed: set[str]) -> tuple[list[str], list[str]]:
    return reject_unknown_ids(values, allowed)


def count_unsupported_numbers(statement: str, evidence_blob: str) -> list[str]:
    out = []
    for token in extract_factual_tokens(statement):
        if not token_supported(token, evidence_blob):
            out.append(token)
    return out


def event_routing_success(items: list[dict[str, Any]], expected_ids: list[str]) -> dict[str, Any]:
    by_id = {str(row.get("event_id")): row for row in items if isinstance(row, dict)}
    routed = 0
    thin = 0
    missing = []
    for event_id in expected_ids:
        row = by_id.get(event_id)
        if not row:
            missing.append(event_id)
            continue
        chain = compact_text(row.get("transmission_chain") or "", 20)
        direction = str(row.get("direction") or "")
        if chain and direction:
            routed += 1
            blob = f"{row.get('short_term_impact') or ''} {row.get('long_term_impact') or ''} {chain}".lower()
            if direction in {"support", "oppose"} and "because" not in blob and "via" not in blob and len(chain) < 24:
                thin += 1
        else:
            missing.append(event_id)
    return {
        "expected": len(expected_ids),
        "returned": len(by_id),
        "routed": routed,
        "thin_good_news_bad_news": thin,
        "missing_event_ids": missing,
        "success_rate": round(routed / len(expected_ids), 3) if expected_ids else 0.0,
    }


def score_run(
    *,
    pack: dict[str, Any],
    drivers: dict[str, Any] | None,
    claims: dict[str, Any] | None,
    events: dict[str, Any] | None,
    counters: dict[str, Any] | None,
    audits: list[dict[str, Any]],
    expected_event_ids: list[str],
    model: str,
) -> dict[str, Any]:
    allowed = set(pack.get("allowed_evidence_ids") or [])
    evidence_blob = " ".join(str(row.get("fact") or row.get("excerpt") or "") for row in pack.get("validated_facts") or [])
    value_drivers = [row for row in (drivers or {}).get("value_drivers") or [] if isinstance(row, dict)]
    core_drivers = [row for row in (drivers or {}).get("core_drivers") or [] if isinstance(row, dict)]
    core_claims = [row for row in (claims or {}).get("core_claims") or [] if isinstance(row, dict)]
    invalid: list[str] = []
    unsupported: list[str] = []
    fact_restatements = 0
    for row in value_drivers + core_claims:
        kept, rejected = count_invalid_ids(row.get("evidence_ids") or row.get("supporting_evidence_ids") or [], allowed)
        invalid.extend(rejected)
        statement = str(row.get("statement") or row.get("description") or "")
        unsupported.extend(count_unsupported_numbers(statement, evidence_blob))
        if row.get("statement") and is_fact_restatement(str(row.get("statement"))):
            fact_restatements += 1
    counter_rows = [row for row in (counters or {}).get("claims") or [] if isinstance(row, dict)]
    counter_complete = 0
    for row in counter_rows:
        if compact_text(row.get("strongest_counter") or "", 8) and compact_text(row.get("what_would_invalidate") or "", 8):
            counter_complete += 1
    event_rows = [row for row in (events or {}).get("events") or [] if isinstance(row, dict)]
    routing = event_routing_success(event_rows, expected_event_ids)
    tokens_in = sum(int(row.get("input_tokens") or 0) for row in audits)
    tokens_out = sum(int(row.get("output_tokens") or 0) for row in audits)
    latency = sum(int(row.get("latency_ms") or 0) for row in audits)
    failures = [row for row in audits if row.get("llm_status") not in {"ok"}]
    return {
        "driver_count": len(value_drivers),
        "driver_overlap": None,
        "unique_material_drivers": [],
        "core_driver_count": len(core_drivers),
        "core_claim_count": len(core_claims),
        "fact_restatement_core_claims": fact_restatements,
        "unsupported_assertion_count": len(list(dict.fromkeys(unsupported))),
        "unsupported_tokens": list(dict.fromkeys(unsupported))[:12],
        "invalid_evidence_id_count": len(list(dict.fromkeys(invalid))),
        "invalid_evidence_ids": list(dict.fromkeys(invalid))[:12],
        "counter_reasoning_count": counter_complete,
        "event_routing_success": routing["success_rate"],
        "event_routing": routing,
        "consistency_failures": len(failures),
        "latency_ms": latency,
        "input_tokens": tokens_in or None,
        "output_tokens": tokens_out or None,
        "estimated_cost": estimate_cost(model, tokens_in, tokens_out),
        "human_scores": empty_human_scores(),
    }


def overlap_metrics(per_model_drivers: dict[str, list[str]]) -> dict[str, Any]:
    names = {key: set(values) for key, values in per_model_drivers.items()}
    labels = list(names)
    overlap: dict[str, Any] = {}
    if len(labels) >= 2:
        shared = set.intersection(*[names[key] for key in labels]) if labels else set()
        overlap["all_models"] = sorted(shared)
        for i, left in enumerate(labels):
            for right in labels[i + 1 :]:
                both = names[left] & names[right]
                overlap[f"{left}∩{right}"] = sorted(both)
    unique = {}
    for label, values in names.items():
        others = set()
        for other, other_values in names.items():
            if other != label:
                others |= other_values
        unique[label] = sorted(values - others)
    return {"overlap": overlap, "unique_material_drivers": unique}
