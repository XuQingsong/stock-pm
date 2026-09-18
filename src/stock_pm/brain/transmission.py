"""Event transmission: Event → State → Exposure → Driver → Claim.

Do not jump layers. Stop when a step has no evidence.
Do not summarize as bullish/bearish.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text

from .limits import limit_words
from .types import TRANSMISSION_MAX_STEPS

LAYER_ORDER = ("event", "state", "exposure", "driver", "claim", "financial", "scenario")
BARE_LABELS = {"bullish", "bearish", "support", "oppose", "positive", "negative", "neutral"}


def _layer(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {"company_exposure": "exposure", "value_driver": "driver", "core_claim": "claim"}
    text = aliases.get(text, text)
    return text if text in LAYER_ORDER else ""


def validate_transmission(
    raw: dict[str, Any] | None,
    *,
    allowed_ids: set[str],
    exposure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(raw or {})
    if str(payload.get("direction") or "").strip().lower() in BARE_LABELS and not payload.get("transmission_chain"):
        return {
            "valid": False,
            "truncated": True,
            "reason": "bare_label_forbidden",
            "transmission_chain": [],
            "affected_states": [],
            "affected_drivers": [],
            "affected_claims": [],
            "scenario_only": True,
            "base_case_change": False,
            "confidence": "low",
        }
    if exposure is not None and not exposure.get("can_affect_claim"):
        chain = _normalize_steps(payload.get("transmission_chain") or [], allowed_ids)
        stopped = [row for row in chain if row["layer"] in {"event", "state", "exposure"}]
        return {
            "valid": True,
            "truncated": True,
            "reason": "stopped_before_claim_without_issuer_exposure",
            "transmission_chain": stopped[:TRANSMISSION_MAX_STEPS],
            "affected_states": list(payload.get("affected_states") or []),
            "affected_drivers": [],
            "affected_claims": [],
            "direction": payload.get("direction"),
            "strength": payload.get("strength") or "weak",
            "direct_or_indirect": "indirect",
            "short_term_impact": limit_words(compact_text(payload.get("short_term_impact") or "", 240), 40),
            "long_term_impact": limit_words(compact_text(payload.get("long_term_impact") or "", 240), 40),
            "financial_metrics_affected": [],
            "scenario_only": True,
            "base_case_change": False,
            "confidence": "low",
            "evidence_needed_next": payload.get("evidence_needed_next") or "issuer-specific exposure evidence",
        }
    steps = _normalize_steps(payload.get("transmission_chain") or [], allowed_ids)
    grounded: list[dict[str, Any]] = []
    seen_layers: list[str] = []
    truncated = False
    reason = ""
    for step in steps[:TRANSMISSION_MAX_STEPS]:
        layer = step["layer"]
        if not layer:
            truncated = True
            reason = "unknown_layer"
            break
        if seen_layers:
            prev = seen_layers[-1]
            prev_idx = LAYER_ORDER.index(prev)
            next_idx = LAYER_ORDER.index(layer)
            if next_idx < prev_idx:
                truncated = True
                reason = "layer_regression"
                break
            if next_idx - prev_idx > 1:
                truncated = True
                reason = "unsupported_leap"
                break
        if layer != "event" and not step["evidence_ids"]:
            truncated = True
            reason = "unsupported_transmission_step"
            break
        grounded.append(step)
        seen_layers.append(layer)
    reached = set(seen_layers)
    claims = list(payload.get("affected_claims") or []) if "claim" in reached else []
    drivers = list(payload.get("affected_drivers") or []) if "driver" in reached else []
    if "claim" in reached and "exposure" not in reached:
        truncated = True
        reason = reason or "event_to_claim_without_exposure"
        claims = []
        grounded = [row for row in grounded if row["layer"] not in {"claim", "financial", "scenario"}]
        reached = {row["layer"] for row in grounded}
        drivers = drivers if "driver" in reached else []
    return {
        "valid": bool(grounded) and reason != "bare_label_forbidden",
        "truncated": truncated or len(steps) > TRANSMISSION_MAX_STEPS,
        "reason": reason,
        "transmission_chain": grounded,
        "affected_states": list(payload.get("affected_states") or []) if "state" in reached or not grounded else list(payload.get("affected_states") or []),
        "affected_drivers": drivers,
        "affected_claims": claims,
        "direction": compact_text(payload.get("direction") or "", 40) or None,
        "strength": payload.get("strength") or "medium",
        "direct_or_indirect": payload.get("direct_or_indirect") or "direct",
        "short_term_impact": limit_words(compact_text(payload.get("short_term_impact") or "", 240), 40),
        "long_term_impact": limit_words(compact_text(payload.get("long_term_impact") or "", 240), 40),
        "financial_metrics_affected": list(payload.get("financial_metrics_affected") or []) if "financial" in reached else [],
        "scenario_only": True if "scenario" in reached or "claim" not in reached else bool(payload.get("scenario_only", True)),
        "base_case_change": bool(payload.get("base_case_change")) if "claim" in reached else False,
        "confidence": payload.get("confidence") or "low",
        "evidence_needed_next": compact_text(payload.get("evidence_needed_next") or "", 160),
    }


def _normalize_steps(raw_steps: Any, allowed_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw_steps or []:
        if not isinstance(item, dict):
            continue
        layer = _layer(item.get("layer") or item.get("from") or item.get("to"))
        evidence_ids = []
        for eid in item.get("evidence_ids") or []:
            key = str(eid or "").strip()
            if key and key in allowed_ids and key not in evidence_ids:
                evidence_ids.append(key)
        statement = limit_words(compact_text(item.get("statement") or item.get("step") or "", 200), 30)
        if not layer or not statement:
            continue
        out.append(
            {
                "layer": layer,
                "statement": statement,
                "direction": compact_text(item.get("direction") or "", 20) or None,
                "strength": item.get("strength") or "medium",
                "direct_or_indirect": item.get("direct_or_indirect") or "direct",
                "evidence_ids": evidence_ids,
            }
        )
    return out
