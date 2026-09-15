"""Evidence-grounded LLM helpers. Completers never mint Evidence rows."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from .types import (
    ASSUMPTION_STATUSES,
    LINK_DIRECTIONS,
    LINK_RELEVANCE,
    LINK_STRENGTHS,
    PROPOSED_ASSUMPTION_STATUSES,
    PROPOSED_STATUS_ALIASES,
    THESIS_ROLE_ALIASES,
    THESIS_ROLES,
)


LLM_STATUSES = ("ok", "skipped", "failed", "fallback")
PROBABILITY_BANDS = ("low", "medium", "high")
FAKE_PRECISION = re.compile(r"\b\d{1,2}\.\d+%|\b(?:3[1-9]|[4-9]\d)%\b")
DURATION_VALUES = ("one_off", "transient", "multi_year", "structural", "unknown")


def skipped_audit(
    *,
    error: str | None = "LLM not invoked; deterministic observe() used",
    provider: str | None = None,
    model: str | None = None,
    prompt_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "llm_called": False,
        "llm_status": "skipped",
        "provider": provider,
        "model": model,
        "prompt_hash": prompt_hash,
        "latency_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "error": error,
        "fallback_used": True,
    }


def audit_from_result(result: dict[str, Any] | None, *, fallback_used: bool | None = None) -> dict[str, Any]:
    row = dict(result or {})
    status = str(row.get("llm_status") or "")
    raw_status = str(row.get("status") or "")
    if not status:
        if raw_status == "ok":
            status = "ok"
        elif raw_status in {"missing_key"}:
            status = "skipped"
        elif raw_status:
            status = "failed"
        else:
            status = "skipped"
    called = bool(row.get("llm_called"))
    if called is False and raw_status == "ok":
        called = True
    if raw_status == "ok":
        called = True
    if raw_status in {"missing_key"}:
        called = False
        status = "skipped"
    used_fallback = row.get("fallback_used")
    if fallback_used is not None:
        used_fallback = fallback_used
    if used_fallback is None:
        used_fallback = status != "ok"
    if status == "ok" and used_fallback:
        status = "fallback"
    return {
        "llm_called": bool(called),
        "llm_status": status if status in LLM_STATUSES else "failed",
        "provider": row.get("provider"),
        "model": row.get("model"),
        "prompt_hash": row.get("prompt_hash"),
        "latency_ms": row.get("latency_ms"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "total_tokens": row.get("total_tokens"),
        "error": row.get("error"),
        "fallback_used": bool(used_fallback),
        "raw_status": raw_status or None,
    }


def prompt_digest(system: str, user: str) -> str:
    encoded = (system or "") + "\n---\n" + (user or "")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compact_text(value: Any, limit: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _text_list(value: Any, *, limit: int = 6, width: int = 160) -> list[str]:
    if isinstance(value, str):
        text = compact_text(value, width)
        return [text] if text else []
    out = []
    for item in value or []:
        text = compact_text(item, width)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def compact_evidence(rows: list[dict[str, Any]] | None, *, limit: int = 40) -> list[dict[str, Any]]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or row.get("_key") or "").strip()
        fact = compact_text(row.get("fact") or row.get("excerpt"), 360)
        if not ident and not fact:
            continue
        raw = row.get("raw_reference") if isinstance(row.get("raw_reference"), dict) else {}
        out.append(
            {
                "id": row.get("id"),
                "evidence_key": row.get("_key") or row.get("evidence_key"),
                "fact": fact,
                "source": row.get("source"),
                "source_type": row.get("source_type"),
                "source_quality": row.get("source_quality"),
                "evidence_type": row.get("evidence_type"),
                "evidence_family": raw.get("independence_family") or raw.get("evidence_side") or row.get("evidence_type"),
                "source_url": row.get("source_url"),
            }
        )
        if len(out) >= limit:
            break
    return out


def compact_assumptions(rows: list[dict[str, Any]] | None, *, limit: int = 16) -> list[dict[str, Any]]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or row.get("assumption_id") or "").strip()
        statement = compact_text(row.get("statement"), 280)
        if not ident and not statement:
            continue
        out.append(
            {
                "id": ident or None,
                "statement": statement,
                "status": row.get("status") or row.get("proposed_status"),
                "category": row.get("category"),
                "thesis_role": row.get("thesis_role"),
                "confidence": row.get("confidence") or row.get("current_confidence"),
            }
        )
        if len(out) >= limit:
            break
    return out


def compact_pack(pack: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(pack or {})
    profile = dict(raw.get("company_profile") or {})
    profile.pop("transcripts", None)
    earnings = []
    for row in list(raw.get("earnings_history") or [])[:4]:
        if not isinstance(row, dict):
            continue
        earnings.append(
            {
                "fiscal_period": row.get("fiscal_period"),
                "report_date": row.get("report_date"),
                "revenue": row.get("revenue"),
                "eps": row.get("eps"),
                "revenue_estimate": row.get("revenue_estimate"),
                "eps_estimate": row.get("eps_estimate"),
                "post_1d_return_pct": row.get("post_1d_return_pct"),
            }
        )
    return {
        "ticker": raw.get("ticker"),
        "template_id": raw.get("template_id"),
        "company_profile": {
            "legal_name": profile.get("legal_name"),
            "sector": profile.get("sector"),
            "revenue_ttm": profile.get("revenue_ttm"),
            "eps_ttm": profile.get("eps_ttm"),
            "last_close": profile.get("last_close"),
            "pe_ttm": profile.get("pe_ttm"),
            "pe_forward": profile.get("pe_forward"),
            "revenue_growth_yoy_pct": profile.get("revenue_growth_yoy_pct"),
            "gross_margin_pct": profile.get("gross_margin_pct"),
            "operating_margin_pct": profile.get("operating_margin_pct"),
            "net_margin_pct": profile.get("net_margin_pct"),
        },
        "earnings_history": earnings,
        "missing_fields": list(raw.get("missing_fields") or [])[:12],
        "price_reaction_history": list(raw.get("price_reaction_history") or [])[:2],
    }


def known_ids(*groups: list[dict[str, Any]] | None) -> set[str]:
    found: set[str] = set()
    for group in groups:
        for row in group or []:
            if not isinstance(row, dict):
                continue
            for key in ("id", "_key", "evidence_key", "evidence_id", "assumption_id"):
                value = str(row.get(key) or "").strip()
                if value:
                    found.add(value)
    return found


def cited_ids(payload: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {
                    "evidence_id",
                    "evidence_key",
                    "assumption_id",
                } or key.endswith("_evidence_id"):
                    text = str(value or "").strip()
                    if text:
                        found.add(text)
                if key.endswith("_ids") or key.endswith("_evidence_ids") or key.endswith("_assumption_ids"):
                    for item in value or []:
                        text = str(item or "").strip()
                        if text:
                            found.add(text)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def unknown_citations(payload: Any, allowed: set[str]) -> list[str]:
    if not allowed:
        return []
    return sorted(item for item in cited_ids(payload) if item not in allowed)


def probability_band(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in PROBABILITY_BANDS:
        return text
    if text in {"likely", "probable"}:
        return "high"
    if text in {"possible", "plausible"}:
        return "medium"
    if text in {"unlikely", "remote"}:
        return "low"
    match = re.search(r"(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%", text)
    if match:
        high = int(match.group(2))
        if high >= 60:
            return "high"
        if high >= 30:
            return "medium"
        return "low"
    return "medium"


def dump_user(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def complete_structured(
    completer: Any,
    *,
    system: str,
    user: str,
    schema: dict[str, Any] | None = None,
    allowed_ids: set[str] | None = None,
    validator: Any | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Call a JsonCompleter. Retry once if citations are unknown. Never invent evidence."""
    if completer is None:
        return None, skipped_audit()
    started = time.perf_counter()

    def _call(prompt: str) -> dict[str, Any]:
        result = completer.complete_json(system=system, user=prompt, schema=schema)
        if not isinstance(result, dict):
            return {"status": "failed", "payload": None, "error": "completer returned non-dict"}
        result.setdefault("prompt_hash", prompt_digest(system, prompt))
        if result.get("latency_ms") is None:
            result["latency_ms"] = int(round((time.perf_counter() - started) * 1000))
        return result

    result = _call(user)
    audit = audit_from_result(result)
    payload = result.get("payload") if result.get("status") == "ok" else None
    if not isinstance(payload, dict):
        if audit["llm_status"] == "ok":
            audit["llm_status"] = "failed"
            audit["fallback_used"] = True
            audit["error"] = audit.get("error") or "model JSON was not an object"
        return None, audit

    problems: list[str] = []
    if allowed_ids is not None:
        unknown = unknown_citations(payload, allowed_ids)
        if unknown:
            problems.append("unknown evidence or assumption ids: " + ", ".join(unknown[:12]))
    if validator is not None:
        extra = validator(payload) or []
        problems.extend(str(item) for item in extra if item)
    if not problems:
        audit["fallback_used"] = False
        audit["llm_status"] = "ok"
        return payload, audit

    retry_user = (
        user
        + "\n\nPrevious output was rejected.\n"
        + "\n".join(f"- {item}" for item in problems)
        + "\nCite only ids from the user JSON. Do not invent facts or evidence."
    )
    result2 = _call(retry_user)
    audit = audit_from_result(result2, fallback_used=False)
    payload2 = result2.get("payload") if result2.get("status") == "ok" else None
    if not isinstance(payload2, dict):
        audit["llm_status"] = "fallback"
        audit["fallback_used"] = True
        audit["error"] = "; ".join(problems)
        return None, audit
    problems2: list[str] = []
    if allowed_ids is not None:
        unknown = unknown_citations(payload2, allowed_ids)
        if unknown:
            problems2.append("unknown evidence or assumption ids: " + ", ".join(unknown[:12]))
    if validator is not None:
        extra = validator(payload2) or []
        problems2.extend(str(item) for item in extra if item)
    if problems2:
        audit["llm_status"] = "fallback"
        audit["fallback_used"] = True
        audit["error"] = "; ".join(problems2)
        return None, audit
    audit["llm_status"] = "ok"
    audit["fallback_used"] = False
    return payload2, audit


def clean_link(item: Any, *, assumption_ids: set[str], evidence_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    assumption_id = str(item.get("assumption_id") or "").strip()
    evidence_id = str(item.get("evidence_id") or item.get("evidence_key") or "").strip()
    direction = str(item.get("direction") or "").strip().lower()
    if direction == "irrelevant":
        return None
    if direction not in LINK_DIRECTIONS:
        return None
    strength = str(item.get("strength") or "moderate").strip().lower()
    if strength not in LINK_STRENGTHS:
        strength = "moderate"
    relevance = str(item.get("relevance") or "indirect").strip().lower()
    if relevance not in LINK_RELEVANCE:
        relevance = "indirect"
    if assumption_id and assumption_ids and assumption_id not in assumption_ids:
        return None
    if evidence_id and evidence_ids and evidence_id not in evidence_ids:
        return None
    reason = compact_text(item.get("reason") or "", 400)
    causal = compact_text(item.get("causal_path") or "", 280)
    independence = compact_text(item.get("independence_note") or "", 200)
    bits = [reason]
    if causal:
        bits.append("Causal path: " + causal)
    if independence:
        bits.append("Independence: " + independence)
    payload = {
        "assumption_id": assumption_id,
        "evidence_id": item.get("evidence_id"),
        "evidence_key": item.get("evidence_key") or (None if item.get("evidence_id") else evidence_id),
        "direction": direction,
        "strength": strength,
        "relevance": relevance,
        "reason": " ".join(bit for bit in bits if bit).strip() or "model linked this evidence to the assumption",
        "causal_path": causal or None,
        "independence_note": independence or None,
    }
    if not payload["assumption_id"] or not (payload.get("evidence_id") or payload.get("evidence_key")):
        return None
    return payload


def clean_proposal(item: Any, *, assumption_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    assumption_id = str(item.get("assumption_id") or "").strip()
    if assumption_id and assumption_ids and assumption_id not in assumption_ids:
        return None
    raw_status = str(item.get("proposed_status") or item.get("status") or "").strip().lower()
    proposed = PROPOSED_STATUS_ALIASES.get(raw_status)
    if proposed not in PROPOSED_ASSUMPTION_STATUSES:
        return None
    reason = compact_text(item.get("reason") or "", 400)
    if not reason:
        return None
    return {
        "assumption_id": assumption_id,
        "statement": item.get("statement"),
        "proposed_status": proposed,
        "reason": reason,
        "confidence": item.get("confidence"),
        "unresolved_gaps": _text_list(item.get("unresolved_gaps"), limit=6, width=160),
    }


def clean_hypotheses(items: Any, *, evidence_ids: set[str]) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        statement = compact_text(item.get("statement") or item.get("hypothesis") or "", 280)
        if not statement:
            continue
        support = [
            str(eid)
            for eid in (item.get("supporting_evidence_ids") or [])
            if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)
        ]
        oppose = [
            str(eid)
            for eid in (item.get("opposing_evidence_ids") or [])
            if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)
        ]
        out.append(
            {
                "statement": statement,
                "probability_band": probability_band(item.get("probability_band") or item.get("probability")),
                "supporting_evidence_ids": support[:6],
                "opposing_evidence_ids": oppose[:6],
                "missing_evidence": _text_list(item.get("missing_evidence"), limit=6, width=160),
                "how_to_test": compact_text(item.get("how_to_test") or "", 240),
                "impact_if_true": compact_text(item.get("impact_if_true") or "", 240),
            }
        )
        if len(out) >= 6:
            break
    return out


def clean_economic_drivers(items: Any, *, evidence_ids: set[str]) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        driver = compact_text(item.get("driver") or "", 120)
        if not driver:
            continue
        duration = str(item.get("duration") or "unknown").strip().lower().replace(" ", "_")
        if duration not in DURATION_VALUES:
            if "one" in duration:
                duration = "one_off"
            elif "struct" in duration:
                duration = "structural"
            elif "year" in duration or "persist" in duration:
                duration = "multi_year"
            else:
                duration = "unknown"
        ids = [
            str(eid)
            for eid in (item.get("evidence_ids") or [])
            if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)
        ]
        out.append(
            {
                "driver": driver,
                "why_it_matters": compact_text(item.get("why_it_matters") or "", 280),
                "evidence_ids": ids[:6],
                "duration": duration,
                "confidence": probability_band(item.get("confidence")),
                "valuation_channel": compact_text(item.get("valuation_channel") or "", 160),
            }
        )
        if len(out) >= 8:
            break
    return out


def clean_search_plan(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = payload if isinstance(payload, dict) else {}
    queries = []
    for item in list(row.get("search_queries") or []) + list(row.get("queries") or []):
        text = compact_text(item, 160)
        if text and text not in queries:
            queries.append(text)
    questions = [compact_text(item, 200) for item in (row.get("search_questions") or []) if str(item).strip()][:10]
    sources = [compact_text(item, 80) for item in (row.get("preferred_source_types") or []) if str(item).strip()][:8]
    mind = [compact_text(item, 200) for item in (row.get("what_would_change_my_mind") or []) if str(item).strip()][:6]
    return {
        "search_questions": questions[:10],
        "search_queries": queries[:10],
        "preferred_source_types": sources,
        "what_would_change_my_mind": mind,
    }


def attach_audit(output: Any, audit: dict[str, Any], extra: dict[str, Any] | None = None) -> Any:
    output.llm_audit = audit
    reasoning = dict(getattr(output, "reasoning", None) or {})
    if extra:
        reasoning.update(extra)
    reasoning["llm_audit"] = audit
    output.model = audit.get("model") or getattr(output, "model", None)
    if audit.get("llm_status") == "ok":
        reasoning["fallback"] = False
    else:
        reasoning["fallback"] = True
    output.reasoning = reasoning
    output.prompt_version = getattr(output, "prompt_version", None)
    return output


def clip(items: list[Any] | None, limit: int) -> list[Any]:
    return list(items or [])[:limit]


def normalize_ruling(item: Any, *, assumption_ids: set[str], evidence_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    assumption_id = str(item.get("assumption_id") or "").strip()
    if not assumption_id or (assumption_ids and assumption_id not in assumption_ids):
        return None
    status = str(item.get("final_status") or item.get("status") or "").strip().lower()
    status = PROPOSED_STATUS_ALIASES.get(status, status)
    if status == "strengthen":
        status = "strengthened"
    if status == "weaken":
        status = "weakened"
    if status not in ASSUMPTION_STATUSES:
        status = "unchanged"
    role = THESIS_ROLE_ALIASES.get(str(item.get("thesis_role") or "supporting").strip().lower(), "supporting")
    if role not in THESIS_ROLES:
        role = "supporting"
    support = [
        str(eid)
        for eid in (item.get("key_supporting_evidence_ids") or [])
        if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)
    ]
    oppose = [
        str(eid)
        for eid in (item.get("key_opposing_evidence_ids") or [])
        if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)
    ]
    return {
        "assumption_id": assumption_id,
        "statement": item.get("statement"),
        "final_status": status,
        "final_confidence": item.get("final_confidence") or item.get("confidence") or 0.5,
        "thesis_role": role,
        "reasoning": compact_text(item.get("reasoning") or item.get("reason") or "", 600),
        "key_supporting_evidence_ids": support[:6],
        "key_opposing_evidence_ids": oppose[:6],
        "unresolved_gaps": [compact_text(gap, 160) for gap in (item.get("unresolved_gaps") or []) if str(gap).strip()][:6],
        "invalidation_condition": compact_text(item.get("invalidation_condition") or "", 240),
        "next_verification": compact_text(item.get("next_verification") or "", 200),
        "engine_proposed_status": item.get("engine_proposed_status"),
        "copied_engine": False,
    }


def validate_pm_payload(payload: dict[str, Any]) -> list[str]:
    problems = []
    variables = payload.get("decisive_variables") or []
    if not isinstance(variables, list) or not variables:
        problems.append("decisive_variables must contain 1–3 items")
    elif len(variables) > 3:
        problems.append("decisive_variables must contain at most 3 items")
    disagreement = payload.get("market_disagreement") or []
    if isinstance(disagreement, list) and len(disagreement) > 2:
        problems.append("market_disagreement must contain at most 2 items")
    changing = payload.get("top_thesis_changing_evidence") or payload.get("top_5_thesis_changing_evidence") or []
    if isinstance(changing, list) and len(changing) > 5:
        problems.append("top thesis-changing evidence must contain at most 5 items")
    return problems
