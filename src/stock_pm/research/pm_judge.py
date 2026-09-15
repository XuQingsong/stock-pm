"""PM/Judge: the only actor that writes assumption status, thesis, and valuation."""

from __future__ import annotations

import re
from typing import Any

from .assumptions import engine_views_for_ticker
from .deep_case import build_delivery_history, reaction_window, synthesize_deep_case
from .extract import to_number
from .llm_reason import (
    clip,
    compact_assumptions,
    compact_evidence,
    compact_pack,
    compact_text,
    complete_structured,
    dump_user,
    known_ids,
    normalize_ruling,
    skipped_audit,
    validate_pm_payload,
)
from .quality import assess_research_quality_axes
from .relevance import CONTRACT_RE, HARD_COUNTER_RE, assumption_kind
from .templates import load_prompt
from .types import (
    ACTOR_PM,
    AGENT_PM,
    ASSUMPTION_STATUSES,
    NEGATIVE_MARKET_REACTION_TASK,
    THESIS_ROLE_ALIASES,
)
from .valuation import attribute_target_change, build_valuation_cases, display_target


PROMPT_VERSION = "sprint55-pm-v1"
ENGINE_TO_STATUS = {
    "strengthen": "strengthened",
    "weaken": "weakened",
    "unchanged": "unchanged",
    "broken": "broken",
}


def _fact(row: dict[str, Any]) -> str:
    return str(row.get("fact") or row.get("excerpt") or "")


def _ids(rows: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    out = []
    for row in rows:
        item = str(row.get("id") or "")
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _agent_findings(snapshot: dict[str, Any], name: str) -> list[str]:
    rows = []
    for item in snapshot.get("findings") or []:
        if isinstance(item, dict) and str(item.get("agent") or "") == name:
            text = str(item.get("text") or "").strip()
            if text:
                rows.append(text)
    return rows


def build_pm_brief(service: Any, ticker: str, *, workflow_run_id: str | None = None) -> dict[str, Any]:
    snapshot = service.research_snapshot(ticker, workflow_run_id)
    pack = snapshot.get("pack") or service.get_pack(ticker)
    views = snapshot.get("assumption_engine") or engine_views_for_ticker(service, ticker)
    evidence = snapshot.get("evidence") or []
    previous_thesis = service.store.get_latest_thesis(ticker)
    previous_valuation = None
    if previous_thesis and previous_thesis.get("valuation_id"):
        getter = getattr(service.store, "get_valuation", None)
        if callable(getter):
            previous_valuation = getter(previous_thesis["valuation_id"])
    evidence_brief = []
    for row in evidence:
        evidence_brief.append(
            {
                "id": row.get("id"),
                "fact": row.get("fact"),
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "source_time": row.get("source_time"),
                "source_type": row.get("source_type"),
                "source_quality": row.get("source_quality"),
                "independence_key": row.get("independence_key"),
                "evidence_type": row.get("evidence_type"),
                "evidence_side": (row.get("raw_reference") or {}).get("evidence_side") if isinstance(row.get("raw_reference"), dict) else None,
                "independence_family": (row.get("raw_reference") or {}).get("independence_family") if isinstance(row.get("raw_reference"), dict) else None,
                "raw_reference": row.get("raw_reference"),
            }
        )
    return {
        "ticker": str(ticker).upper(),
        "pack": pack,
        "assumptions": snapshot.get("assumptions") or [],
        "engine_views": views,
        "evidence": evidence_brief,
        "industry_findings": _agent_findings(snapshot, "industry"),
        "quant_findings": _agent_findings(snapshot, "quant"),
        "risk_findings": _agent_findings(snapshot, "risk"),
        "search_findings": _agent_findings(snapshot, "search_data"),
        "competing_hypotheses": snapshot.get("competing_hypotheses") or [],
        "economic_drivers": snapshot.get("economic_drivers") or [],
        "agent_reasoning": snapshot.get("agent_reasoning") or [],
        "tasks": snapshot.get("tasks") or [],
        "previous_thesis": previous_thesis,
        "previous_valuation": previous_valuation,
        "snapshot": snapshot,
    }


def _has_contract(rows: list[dict[str, Any]]) -> bool:
    return any(CONTRACT_RE.search(_fact(row)) for row in rows)


def _has_hard_counter(rows: list[dict[str, Any]]) -> bool:
    return any(HARD_COUNTER_RE.search(_fact(row)) for row in rows)


def _direct_support(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in view.get("supporting_evidence") or []
        if str(row.get("link_relevance") or "") == "direct" and str(row.get("link_strength") or "") in {"strong", "moderate"}
    ]


def _direct_oppose(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in view.get("opposing_evidence") or []
        if str(row.get("link_relevance") or "") == "direct" and str(row.get("link_strength") or "") in {"strong", "moderate"}
    ]


def adjudicate_assumption(view: dict[str, Any]) -> dict[str, Any]:
    """Independent PM ruling. Engine proposed_status is an input, not a copy target."""
    kind = assumption_kind(view)
    engine = str(view.get("proposed_status") or "unchanged")
    support = list(view.get("supporting_evidence") or [])
    oppose = list(view.get("opposing_evidence") or [])
    gaps = [str(item) for item in view.get("unresolved_gaps") or [] if str(item).strip()]
    direct_support = _direct_support(view)
    direct_oppose = _direct_oppose(view)
    hard_oppose = float(view.get("oppose_score") or 0) if direct_oppose else 0.0
    if direct_oppose:
        hard_oppose = max(hard_oppose, 0.55)
    named_customer = any(re.search(r"\b(customer [A-Z]|named customer|largest customer is [A-Z])", _fact(row)) for row in support)
    customer_gap = any("customer" in item.lower() or "confirmation" in item.lower() for item in gaps)
    support_ids = _ids(direct_support or support)
    oppose_ids = _ids(direct_oppose or oppose)

    status = "unchanged"
    role = "supporting"
    confidence = float(view.get("current_confidence") or view.get("confidence") or 0.5)
    invalidation = "source-backed delay, cancellation, guidance cut, or failed delivery versus the claim"
    next_check = gaps[0] if gaps else "re-check the next official print and customer-side confirmation"
    reasons = []

    if direct_oppose and _has_hard_counter(direct_oppose):
        status = "broken" if len(direct_oppose) >= 2 and hard_oppose >= 1.5 else "weakened"
        role = "core" if kind in {"execution", "guidance", "demand_visibility"} else "monitoring"
        confidence = max(0.2, confidence - 0.12)
        reasons.append(
            "PM weakens this claim because opposing source language describes delay, cancellation, a miss, or a cut: "
            + "; ".join(_fact(row)[:160] for row in direct_oppose[:2])
        )
        invalidation = "further delivery misses or additional cuts versus the same claim"
    elif kind == "growth_persist":
        status = "unchanged"
        role = "monitoring"
        reasons.append(
            "PM does not treat a recent print or a single contract as proof that two-year growth persists. "
            "The engine suggestion is noted and not adopted."
        )
        if engine == "strengthen":
            reasons.append("independent judgment: persistence still needs customer-side duration, not just a strong print")
        next_check = "independent customer capex and whether growth remains after the current contract wave"
        invalidation = "growth decelerates without a replacement demand source, or customers cut deployments"
    elif kind == "guidance":
        role = "monitoring"
        if direct_oppose:
            status = "weakened"
            confidence = max(0.2, confidence - 0.1)
            reasons.append("PM finds direct opposition to the outlook claim in source text")
        elif direct_support and not customer_gap:
            status = "unchanged"
            reasons.append(
                "an outlook quote is on the record, but PM still requires a delivery track record before strengthening guidance"
            )
        else:
            status = "unchanged"
            reasons.append("PM leaves guidance unchanged until later prints confirm or refute the outlook")
        invalidation = "management cuts the outlook or misses the stated range"
        next_check = "next reported period versus the stated outlook"
    elif kind in {"execution", "demand_visibility", "supply"}:
        contract = _has_contract(support) or _has_contract(direct_support)
        if contract and direct_support and not direct_oppose:
            status = "strengthened"
            role = "core"
            confidence = min(0.78, confidence + 0.12)
            reasons.append(
                "PM independently strengthens this delivery claim because official contract or capacity language is direct: "
                + "; ".join(_fact(row)[:160] for row in direct_support[:2])
            )
            if not named_customer:
                gaps = list(dict.fromkeys(gaps + ["customer is not independently named"]))
                reasons.append("limits remain: the customer is not independently named and capex/site readiness is not confirmed")
            invalidation = "the contract is cancelled, revenue recognition slips, or the customer delays deployment"
        elif direct_support and not contract:
            status = "unchanged"
            role = "monitoring" if kind != "supply" else "supporting"
            reasons.append(
                "related demand or supply language exists, but PM will not strengthen without a direct delivery instrument such as a contract, lease, or capacity commitment"
            )
            if engine == "strengthen":
                reasons.append("engine suggested strengthen; PM keeps the claim unchanged because the causal link is still incomplete")
        else:
            status = "unchanged"
            role = "monitoring"
            reasons.append("PM finds no independent causal support strong enough to change this assumption")
        next_check = "customer deployment, capex, power/site readiness, and supply/foundry execution"
    elif kind == "margin":
        role = "monitoring"
        if direct_oppose:
            status = "weakened"
            reasons.append("margin language in source text challenges the margin claim")
        else:
            status = "unchanged"
            reasons.append("PM keeps margin as a monitoring item until mix and cost evidence is cleaner")
        invalidation = "sustained mix or cost pressure that offsets volume"
    else:
        role = "supporting"
        status = "unchanged"
        reasons.append("PM leaves this assumption unchanged; evidence does not independently justify a status rewrite")
        if engine == "strengthen":
            reasons.append("not copied from the engine: the suggestion lacked a PM-level causal standard")

    if status not in ASSUMPTION_STATUSES:
        status = "unchanged"
    role = THESIS_ROLE_ALIASES.get(role, role)
    return {
        "assumption_id": view.get("assumption_id") or view.get("id"),
        "statement": view.get("statement"),
        "category": view.get("category"),
        "engine_proposed_status": engine,
        "final_status": status,
        "final_confidence": round(float(confidence), 3),
        "thesis_role": role,
        "reasoning": " ".join(reasons),
        "key_supporting_evidence_ids": support_ids,
        "key_opposing_evidence_ids": oppose_ids,
        "unresolved_gaps": gaps[:8],
        "invalidation_condition": invalidation,
        "next_verification": next_check,
        "kind": kind,
        "copied_engine": False,
    }


def apply_delivery_history(rulings: list[dict[str, Any]], delivery: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Use scored prints as credibility input. History is retained; a single rate is not a substitute."""
    payload = delivery or {}
    miss = payload.get("miss_rate")
    summary = str(payload.get("summary") or "")
    if not rulings:
        return rulings
    for row in rulings:
        kind = str(row.get("kind") or "")
        if kind not in {"guidance", "growth_persist", "execution", "demand_visibility"}:
            continue
        gaps = list(row.get("unresolved_gaps") or [])
        credibility = str(payload.get("credibility") or "")
        if summary:
            extra = ["management delivery history is an input to long-term commitment credibility"]
            if int(payload.get("prints_scored") or 0) < 6:
                extra.append("scored delivery sample is shorter than 6 quarters; a clean beat streak is not long-term proof")
            gaps = list(dict.fromkeys(gaps + extra))
            row["unresolved_gaps"] = gaps[:8]
            row["reasoning"] = (row.get("reasoning") or "") + (" Delivery history: " + (credibility or summary) + ".")
        if miss is None:
            continue
        if miss >= 0.25 and kind in {"guidance", "growth_persist"} and row.get("final_status") == "strengthened":
            row["final_status"] = "unchanged"
            row["reasoning"] += " Recent scored prints include misses, so PM does not strengthen the outlook on delivery score alone."
        elif miss >= 0.4 and kind == "guidance" and row.get("final_status") == "unchanged":
            row["final_status"] = "weakened"
            row["reasoning"] += " Delivery history miss-rate is elevated versus recent prints."
    return rulings


def explain_market_reaction(brief: dict[str, Any]) -> dict[str, Any]:
    pack = brief.get("pack") or {}
    reaction = reaction_window(pack)
    findings = list(brief.get("quant_findings") or [])
    evidence = list(brief.get("evidence") or [])
    tasks = brief.get("tasks") or []
    tension = next((item for item in findings if "tension is" in item.lower()), "")
    pe = to_number((pack.get("company_profile") or {}).get("pe_ttm"))
    post = to_number(reaction.get("post_1d_return_pct") or reaction.get("day_return_pct"))
    volume = to_number(reaction.get("volume_vs_20d_avg"))
    fund = to_number((pack.get("company_profile") or {}).get("revenue_growth_yoy_pct"))
    negative = post is not None and post < 0
    positive_fund = fund is not None and fund >= 2
    cited = []
    unresolved = []
    if pe is not None:
        cited.append(f"TTM PE is {pe}, which is valuation context for why a good print may not be rewarded")
    if volume is not None and volume >= 1.5:
        cited.append(f"earnings-window volume vs 20d average is {volume}")
    hay = " ".join(_fact(row) for row in evidence).lower() + " " + " ".join(findings).lower()
    if "margin" in hay or "mix" in hay:
        cited.append("source text includes margin or mix language that can offset a strong top-line print")
    if "largest customer" in hay or "concentration" in hay:
        cited.append("customer concentration is on the record and can cap how far investors trust duration")
    if "whisper" in hay or "below consensus" in hay:
        cited.append("there is source language about expectations versus the print")
    else:
        unresolved.append("guidance versus whisper/expectations is not independently confirmed in the evidence set")
    if "positioning" not in hay:
        unresolved.append("investor positioning is not evidenced")
    has_task = any(NEGATIVE_MARKET_REACTION_TASK.lower() in str(item.get("title") or "").lower() for item in tasks)
    if not negative or not positive_fund:
        summary = (
            "The latest window is not a clean case of strong fundamentals with a negative high-volume reaction, "
            "so PM does not force an explanation."
        )
        if tension:
            summary += " Quant tension: " + tension
        return {"summary": summary, "cited": cited, "unresolved": unresolved, "applicable": False}
    if not cited:
        unresolved.append("no source-backed fundamental explanation for the negative reaction was located")
        summary = (
            "Fundamentals were positive and the stock moved lower, but PM cannot honestly fill in why. "
            "The gap stays unresolved rather than inferred from experience."
        )
    else:
        summary = (
            "The tape did not reward the fundamental print. Available evidence points to "
            + "; ".join(cited)
            + ". "
            + ("Whisper and positioning remain unresolved. " if unresolved else "")
        )
    if has_task:
        summary += f" Follow-up task remains: {NEGATIVE_MARKET_REACTION_TASK}."
    return {"summary": summary.strip(), "cited": cited, "unresolved": unresolved, "applicable": True}


def _horizon_views(brief: dict[str, Any], rulings: list[dict[str, Any]], reaction: dict[str, Any]) -> dict[str, str]:
    pack = brief.get("pack") or {}
    profile = pack.get("company_profile") or {}
    name = str(profile.get("legal_name") or brief.get("ticker"))
    strengthened = [row for row in rulings if row["final_status"] == "strengthened"]
    weakened = [row for row in rulings if row["final_status"] in {"weakened", "broken"}]
    unresolved = [row for row in rulings if row["final_status"] == "unchanged"]
    pe = to_number(profile.get("pe_ttm"))
    short_bits = [
        "Over the next 1–3 months: the latest print and the earnings-window tape set the near-term debate.",
    ]
    if reaction.get("applicable"):
        short_bits.append(reaction["summary"])
    elif pe:
        short_bits.append(f"Current TTM PE is {pe}; that is context, not a trading call.")
    if not reaction.get("applicable"):
        short_bits.append("Near-term setup is about whether the next official update confirms or cools the last print.")
    mid_bits = [
        "Over the next 3–12 months: guidance delivery and whether stated commitments convert into recognized revenue are the binding checks.",
    ]
    if unresolved:
        mid_bits.append("Unresolved items the PM is watching: " + "; ".join(str(row["statement"])[:120] for row in unresolved[:3]))
    if weakened:
        mid_bits.append("Weakened claims that must be re-tested: " + "; ".join(str(row["statement"])[:120] for row in weakened[:2]))
    long_bits = [
        "Over the next 1–3 years: earnings power depends on whether evidenced demand and delivery claims persist after the current contract or project wave.",
    ]
    if strengthened:
        long_bits.append("Claims with source-backed support: " + "; ".join(str(row["statement"])[:120] for row in strengthened[:3]))
    long_bits.append(f"{name} is not collapsed into a single bullish or bearish label; horizons can disagree.")
    return {
        "short_term_view": " ".join(short_bits),
        "mid_term_view": " ".join(mid_bits),
        "long_term_view": " ".join(long_bits),
    }


def _core_thesis(brief: dict[str, Any], rulings: list[dict[str, Any]], views: dict[str, str], reaction: dict[str, Any]) -> str:
    pack = brief.get("pack") or {}
    name = str((pack.get("company_profile") or {}).get("legal_name") or brief.get("ticker"))
    template = str(pack.get("template_id") or "generic_company")
    core = [row for row in rulings if row.get("thesis_role") == "core"]
    strengthened = [row for row in rulings if row["final_status"] == "strengthened"]
    parts = [
        f"{name} is researched under the {template} template.",
        views["short_term_view"],
        views["mid_term_view"],
        views["long_term_view"],
    ]
    if core:
        parts.append("Core claims: " + "; ".join(str(row["statement"])[:160] for row in core[:4]))
    if strengthened:
        parts.append("PM strengthened " + str(len(strengthened)) + " assumption(s) on source-backed delivery evidence, not because the engine suggested it.")
    if reaction.get("applicable"):
        parts.append("Market reaction: " + reaction["summary"])
    parts.append("This is an investment thesis, not a trading recommendation and not a position-sizing instruction.")
    return " ".join(parts)


def thesis_diff(previous: dict[str, Any] | None, current: dict[str, Any], *, previous_valuation: dict[str, Any] | None = None, current_valuation: dict[str, Any] | None = None, previous_rulings: list[dict[str, Any]] | None = None, current_rulings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not previous:
        return {
            "what_changed": "initial thesis",
            "strengthened_assumptions": [row.get("assumption_id") for row in (current_rulings or []) if row.get("final_status") == "strengthened"],
            "weakened_assumptions": [row.get("assumption_id") for row in (current_rulings or []) if row.get("final_status") in {"weakened", "broken"}],
            "new_evidence": [],
            "removed_evidence": [],
            "valuation_change": None,
            "confidence_change": None,
            "thesis_change": "first version",
        }
    prev_ids = set(previous.get("key_assumption_ids") or []) | set(previous.get("core_assumption_ids") or [])
    curr_ids = set(current.get("key_assumption_ids") or []) | set(current.get("core_assumption_ids") or [])
    prev_status = {row.get("assumption_id"): row.get("final_status") for row in previous_rulings or []}
    strengthened = []
    weakened = []
    for row in current_rulings or []:
        prior = prev_status.get(row.get("assumption_id"))
        if row.get("final_status") == "strengthened" and prior != "strengthened":
            strengthened.append(row.get("assumption_id"))
        if row.get("final_status") in {"weakened", "broken"} and prior not in {"weakened", "broken"}:
            weakened.append(row.get("assumption_id"))
    prev_target = to_number(((previous_valuation or {}).get("base_case") or {}).get("target_value"))
    curr_target = to_number(((current_valuation or {}).get("base_case") or {}).get("target_value"))
    valuation_change = None
    if prev_target is not None or curr_target is not None:
        attribution = attribute_target_change(previous_valuation, current_valuation)
        valuation_change = {
            "base_target": {"from": display_target(prev_target), "to": display_target(curr_target)},
            "attribution": attribution.get("parts") or [],
            "reason": "recomputed from current pack inputs, PM rulings, and the earnings bridge",
        }
    prev_conf = to_number(previous.get("confidence"))
    curr_conf = to_number(current.get("confidence"))
    thesis_changed = str(previous.get("core_thesis") or "") != str(current.get("core_thesis") or "")
    return {
        "what_changed": "thesis version incremented",
        "strengthened_assumptions": strengthened,
        "weakened_assumptions": weakened,
        "new_core_assumption_ids": sorted(curr_ids - prev_ids),
        "removed_core_assumption_ids": sorted(prev_ids - curr_ids),
        "new_evidence": [],
        "removed_evidence": [],
        "valuation_change": valuation_change,
        "confidence_change": {"from": prev_conf, "to": curr_conf} if prev_conf is not None or curr_conf is not None else None,
        "thesis_change": "core thesis text changed" if thesis_changed else "core thesis text unchanged",
    }


def _rule_pm_judgment(brief: dict[str, Any]) -> dict[str, Any]:
    views = list(brief.get("engine_views") or [])
    rulings = [adjudicate_assumption(view) for view in views]
    delivery = build_delivery_history(brief.get("pack"))
    apply_delivery_history(rulings, delivery)
    reaction = explain_market_reaction(brief)
    horizons = _horizon_views(brief, rulings, reaction)
    core_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "core"]
    supporting_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "supporting"]
    monitoring_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "monitoring"]
    cases = build_valuation_cases(
        brief.get("pack") or {},
        assumptions=brief.get("assumptions") or [],
        evidence=brief.get("evidence") or [],
        key_assumption_ids=core_ids,
        rulings=rulings,
    )
    deep = synthesize_deep_case(
        brief.get("pack"),
        evidence=brief.get("evidence") or [],
        rulings=rulings,
        valuation=cases,
        mapping=cases.get("driver_map"),
        quant_findings=brief.get("quant_findings") or [],
        reaction=reaction,
        ticker=brief.get("ticker"),
    )
    classified = deep.get("market_reaction") or {}
    reaction = {
        **reaction,
        "confirmed": classified.get("confirmed") or [],
        "plausible_unconfirmed": classified.get("plausible_unconfirmed") or [],
        "unresolved": classified.get("unresolved") or reaction.get("unresolved") or [],
        "summary": classified.get("summary") or reaction.get("summary"),
        "classification": classified,
        "applicable": classified.get("applicable", reaction.get("applicable")),
    }
    cal = dict(cases.get("calibration_json") or {})
    cal["deep_case"] = deep
    cal["market_implied_case"] = (deep.get("market_implied") or {}).get("case")
    cal["case_columns"] = deep.get("case_columns") or {
        "bear": cases.get("bear_case"),
        "market_implied": (deep.get("market_implied") or {}).get("case"),
        "base": cases.get("base_case"),
        "bull": cases.get("bull_case"),
    }
    cal["delivery_history"] = deep.get("delivery_history")
    cases["calibration_json"] = cal
    cases["market_implied_case"] = cal["market_implied_case"]
    cases["deep_case"] = deep
    axes = assess_research_quality_axes(
        brief.get("pack"),
        evidence=brief.get("evidence"),
        assumptions=[{**row, "status": row["final_status"]} for row in rulings],
        valuation=cases,
    )
    confidences = [float(row["final_confidence"]) for row in rulings] or [0.4]
    thesis_confidence = round(min(0.8, sum(confidences) / len(confidences)), 3)
    if axes.get("quality_for_final_thesis") == "insufficient":
        thesis_confidence = min(thesis_confidence, 0.35)
    elif axes.get("quality_for_final_thesis") == "partial":
        thesis_confidence = min(thesis_confidence, 0.62)
    if cases.get("valuation_status") == "insufficient":
        thesis_confidence = min(thesis_confidence, 0.28)
    elif cases.get("valuation_status") == "provisional":
        thesis_confidence = min(thesis_confidence, 0.48)
    catalysts = []
    for row in rulings:
        if row["final_status"] == "strengthened":
            catalysts.append("delivery on: " + str(row.get("statement") or "")[:160])
    risks = [row.get("invalidation_condition") for row in rulings if row.get("invalidation_condition")]
    for gap in reaction.get("unresolved") or []:
        risks.append(gap)
    invalidation = list(dict.fromkeys(row.get("invalidation_condition") for row in rulings if row.get("thesis_role") == "core"))
    if not invalidation:
        invalidation = ["core delivery claims fail in subsequent official reports"]
    golden = deep.get("golden_answers") or {}
    monitoring = list(
        dict.fromkeys(
            [item for item in (golden.get("monitor") or []) if item]
            + [row.get("next_verification") for row in rulings if row.get("next_verification")]
            + (reaction.get("unresolved") or [])
        )
    )
    quality_payload = dict(axes)
    quality_payload["golden_answers"] = golden
    quality_payload["management_delivery"] = delivery
    thesis = {
        "core_thesis": _core_thesis(brief, rulings, horizons, reaction)
        + " "
        + str(golden.get("core_thesis") or "")
        + (" " + str(golden.get("pm_conclusion") or "") if golden.get("pm_conclusion") else "")
        + (
            " Customer-side validation: " + str(golden.get("customer_validation"))
            if golden.get("customer_validation")
            else ""
        ),
        "short_term_view": horizons["short_term_view"],
        "mid_term_view": horizons["mid_term_view"],
        "long_term_view": horizons["long_term_view"],
        "key_assumption_ids": core_ids,
        "core_assumption_ids": core_ids,
        "supporting_assumption_ids": supporting_ids,
        "key_catalysts": catalysts[:8],
        "key_risks": [item for item in risks if item][:8],
        "invalidation_conditions": [item for item in invalidation if item][:8],
        "monitoring_items": [item for item in monitoring if item][:10],
        "confidence": thesis_confidence,
        "research_quality": quality_payload,
        "market_reaction": reaction["summary"],
        "prompt_version": PROMPT_VERSION,
    }
    return {
        "rulings": rulings,
        "thesis": thesis,
        "valuation": cases,
        "market_reaction": reaction,
        "research_quality": axes,
        "monitoring_assumption_ids": monitoring_ids,
        "deep_case": deep,
        "prompt_version": PROMPT_VERSION,
        "agent_name": AGENT_PM,
        "llm_audit": skipped_audit(error="rule engine path"),
        "pm_reasoning": {"source": "deterministic_fallback"},
    }


def _python_counterfactual(cases: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("if") or item.get("statement") or "").lower()
    base = cases.get("base_case") or {}
    target = to_number(base.get("target_value"))
    eps = to_number(base.get("eps"))
    computed = {"computed": False, "method": None, "stressed_target": None, "stressed_eps": None}
    if any(token in text for token in ("70%", "0.7", "seventy percent", "70 percent")) and target is not None:
        computed = {
            "computed": True,
            "method": "scale_base_target_by_0.7",
            "stressed_target": round(target * 0.7, 2),
            "stressed_eps": eps,
        }
    elif any(token in text for token in ("300bps", "300 bps", "3 percentage", "300 basis", "margin", "dilut")) and target is not None:
        computed = {
            "computed": True,
            "method": "haircut_base_target_for_300bps_margin",
            "stressed_target": round(target * 0.9, 2),
            "stressed_eps": round(eps * 0.9, 4) if eps is not None else None,
        }
    elif any(token in text for token in ("delay", "one year", "1 year", "slip", "defer")) and target is not None:
        computed = {
            "computed": True,
            "method": "delay_duration_haircut",
            "stressed_target": round(target * 0.85, 2),
            "stressed_eps": eps,
        }
    return computed


def _guardrail_warnings(llm_rulings: list[dict[str, Any]], views: list[dict[str, Any]]) -> list[str]:
    warnings = []
    by_id = {str(view.get("assumption_id") or view.get("id") or ""): view for view in views}
    for ruling in llm_rulings:
        view = by_id.get(str(ruling.get("assumption_id") or "")) or {}
        oppose = _direct_oppose(view)
        if ruling.get("final_status") == "strengthened" and oppose and _has_hard_counter(oppose):
            warnings.append(
                f"assumption {ruling.get('assumption_id')} was strengthened while direct hard-counter evidence exists"
            )
    return warnings


def _pm_user_payload(brief: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    cases = base.get("valuation") or {}
    previous = brief.get("previous_thesis") or {}
    return {
        "ticker": brief.get("ticker"),
        "research_pack": compact_pack(brief.get("pack")),
        "assumptions": compact_assumptions(brief.get("assumptions"), limit=10),
        "evidence": compact_evidence(brief.get("evidence"), limit=24),
        "industry_findings": clip(brief.get("industry_findings"), 12),
        "risk_findings": clip(brief.get("risk_findings"), 12),
        "quant_findings": clip(brief.get("quant_findings"), 12),
        "fundamental_findings": clip(brief.get("search_findings"), 8),
        "competing_hypotheses": clip(brief.get("competing_hypotheses"), 8),
        "economic_drivers": clip(brief.get("economic_drivers"), 8),
        "python_guardrail_rulings": [
            {
                "assumption_id": row.get("assumption_id"),
                "final_status": row.get("final_status"),
                "thesis_role": row.get("thesis_role"),
                "reasoning": compact_text(row.get("reasoning"), 240),
            }
            for row in (base.get("rulings") or [])[:8]
        ],
        "valuation_math": {
            "status": cases.get("valuation_status"),
            "spot_price": cases.get("spot_price"),
            "bear_target": (cases.get("bear_case") or {}).get("target_value"),
            "base_target": (cases.get("base_case") or {}).get("target_value"),
            "bull_target": (cases.get("bull_case") or {}).get("target_value"),
            "method": (cases.get("calibration_json") or {}).get("method") or cases.get("method"),
        },
        "previous_thesis": {
            "core_thesis": compact_text(previous.get("core_thesis"), 400),
            "version": previous.get("version"),
        },
        "rules": [
            "Cite only evidence_id values from evidence[].",
            "Do not invent evidence.",
            "Do not replace valuation_math numbers.",
            "decisive_variables: 1-3 items. market_disagreement: at most 2. thesis-changing evidence: at most 5.",
            "Keep each assumption ruling to one sentence.",
        ],
    }


def _clean_pm_payload(raw: dict[str, Any], *, assumption_ids: set[str], evidence_ids: set[str]) -> dict[str, Any]:
    variables = []
    for item in raw.get("decisive_variables") or []:
        if not isinstance(item, dict):
            continue
        name = compact_text(item.get("name") or item.get("variable") or "", 80)
        if not name:
            continue
        ids = [str(eid) for eid in (item.get("evidence_ids") or item.get("evidence") or []) if str(eid).strip() and (not evidence_ids or str(eid) in evidence_ids)]
        variables.append(
            {
                "name": name,
                "why_decisive": compact_text(item.get("why_decisive") or "", 240),
                "current_view": compact_text(item.get("current_view") or "", 240),
                "evidence_ids": ids[:6],
                "sensitivity": compact_text(item.get("sensitivity") or "", 200),
                "next_check": compact_text(item.get("next_check") or "", 160),
            }
        )
        if len(variables) >= 3:
            break
    disagreement = []
    for item in raw.get("market_disagreement") or []:
        if not isinstance(item, dict):
            continue
        disagreement.append(
            {
                "pm_believes": compact_text(item.get("pm_believes") or "", 240),
                "market_appears_to_price": compact_text(item.get("market_appears_to_price") or "", 240),
                "why_pm_differs": compact_text(item.get("why_pm_differs") or "", 240),
                "evidence_that_would_prove_market_right": compact_text(
                    item.get("evidence_that_would_prove_market_right") or "", 240
                ),
            }
        )
        if len(disagreement) >= 2:
            break
    changing = []
    for item in raw.get("top_thesis_changing_evidence") or raw.get("top_5_thesis_changing_evidence") or []:
        if isinstance(item, dict):
            eid = str(item.get("evidence_id") or "").strip()
            if eid and (not evidence_ids or eid in evidence_ids):
                changing.append({"evidence_id": eid, "why_it_changes_thesis": compact_text(item.get("why_it_changes_thesis") or item.get("why") or "", 200)})
        else:
            eid = str(item).strip()
            if eid and (not evidence_ids or eid in evidence_ids):
                changing.append({"evidence_id": eid, "why_it_changes_thesis": ""})
        if len(changing) >= 5:
            break
    not_changing = []
    for item in (
        raw.get("looks_important_but_does_not_change_thesis")
        or raw.get("low_value_evidence")
        or raw.get("non_thesis_changing_evidence")
        or []
    ):
        if not isinstance(item, dict):
            continue
        eid = str(item.get("evidence_id") or "").strip()
        if eid and (not evidence_ids or eid in evidence_ids):
            not_changing.append({"evidence_id": eid, "why_not": compact_text(item.get("why_not") or item.get("why") or "", 200)})
        if len(not_changing) >= 3:
            break
    counterfactuals = []
    for item in raw.get("counterfactuals") or []:
        if not isinstance(item, dict):
            continue
        counterfactuals.append(
            {
                "if": compact_text(item.get("if") or item.get("statement") or "", 240),
                "thesis_impact": compact_text(item.get("thesis_impact") or "", 240),
                "eps_or_valuation_direction": compact_text(item.get("eps_or_valuation_direction") or "", 160),
                "what_to_recompute": compact_text(item.get("what_to_recompute") or "", 160),
            }
        )
        if len(counterfactuals) >= 6:
            break
    rulings = [
        item
        for item in (
            normalize_ruling(row, assumption_ids=assumption_ids, evidence_ids=evidence_ids)
            for row in (raw.get("assumption_rulings") or [])
        )
        if item
    ]
    golden = raw.get("golden_answers") if isinstance(raw.get("golden_answers"), dict) else {}
    most_wrong = compact_text(
        raw.get("most_likely_wrong") or golden.get("most_likely_error") or raw.get("what_could_make_me_wrong") or "",
        320,
    )
    change_mind = compact_text(
        raw.get("what_would_change_my_mind")
        or golden.get("evidence_that_would_change_the_call")
        or raw.get("thesis_invalidation")
        or "",
        320,
    )
    hypotheses = []
    for item in raw.get("competing_hypotheses") or []:
        if not isinstance(item, dict):
            continue
        statement = compact_text(item.get("statement") or "", 280)
        if not statement:
            continue
        missing = item.get("missing_evidence")
        if isinstance(missing, str):
            missing_list = [missing] if missing.strip() else []
        else:
            parts = [str(gap) for gap in (missing or [])]
            if parts and all(len(part.strip()) <= 1 for part in parts):
                joined = "".join(parts).strip()
                missing_list = [joined] if joined else []
            else:
                missing_list = [part.strip() for part in parts if part.strip() and len(part.strip()) > 1][:4]
        hypotheses.append(
            {
                "statement": statement,
                "probability_band": compact_text(item.get("probability_band") or "", 40),
                "how_to_test": compact_text(item.get("how_to_test") or "", 200),
                "impact_if_true": compact_text(item.get("impact_if_true") or "", 200),
                "missing_evidence": missing_list,
            }
        )
        if len(hypotheses) >= 4:
            break
    return {
        "core_contradiction": compact_text(raw.get("core_contradiction") or golden.get("core_contradiction") or "", 400),
        "decisive_variables": variables,
        "assumption_rulings": rulings,
        "conviction_hierarchy": [compact_text(item, 200) for item in (raw.get("conviction_hierarchy") or []) if str(item).strip()][:8],
        "core_thesis": compact_text(raw.get("core_thesis") or "", 1200),
        "short_term_view": compact_text(raw.get("short_term_view") or "", 500),
        "mid_term_view": compact_text(raw.get("mid_term_view") or "", 500),
        "long_term_view": compact_text(raw.get("long_term_view") or "", 500),
        "market_disagreement": disagreement,
        "top_thesis_changing_evidence": changing,
        "looks_important_but_does_not_change_thesis": not_changing,
        "low_value_evidence": not_changing,
        "non_thesis_changing_evidence": not_changing,
        "strongest_evidence": raw.get("strongest_evidence") if isinstance(raw.get("strongest_evidence"), dict) else {"evidence_id": None, "why": compact_text(raw.get("strongest_evidence"), 200)},
        "weakest_link": compact_text(raw.get("weakest_link") or "", 280),
        "what_could_make_me_wrong": most_wrong,
        "most_likely_wrong": most_wrong,
        "next_information_to_seek": compact_text(raw.get("next_information_to_seek") or "", 240),
        "what_would_change_my_mind": change_mind,
        "competing_hypotheses": hypotheses,
        "thesis_invalidation": compact_text(raw.get("thesis_invalidation") or "", 280),
        "valuation_driver_judgment": compact_text(raw.get("valuation_driver_judgment") or "", 400),
        "counterfactuals": counterfactuals,
        "golden_answers": {
            "core_contradiction": compact_text(golden.get("core_contradiction") or raw.get("core_contradiction") or "", 400),
            "three_variables": [row.get("name") for row in variables],
            "market_disagreement": disagreement,
            "most_likely_error": most_wrong,
            "evidence_that_would_change_the_call": change_mind,
        },
    }


def build_pm_judgment(brief: dict[str, Any], completer: Any | None = None) -> dict[str, Any]:
    base = _rule_pm_judgment(brief)
    assumption_ids = {str(row.get("assumption_id") or row.get("id") or "") for row in (brief.get("assumptions") or []) if row.get("id") or row.get("assumption_id")}
    assumption_ids |= {str(row.get("assumption_id") or "") for row in (base.get("rulings") or []) if row.get("assumption_id")}
    evidence_ids = known_ids(brief.get("evidence") or [])
    allowed = assumption_ids | evidence_ids
    raw, audit = complete_structured(
        completer,
        system=load_prompt("pm_judge.txt"),
        user=dump_user(_pm_user_payload(brief, base)),
        allowed_ids=allowed or None,
        validator=validate_pm_payload,
    )
    if not raw:
        base["llm_audit"] = audit
        base["thesis"]["research_quality"] = dict(base["thesis"].get("research_quality") or {})
        base["thesis"]["research_quality"]["pm_reasoning"] = {"source": "deterministic_fallback", "llm_audit": audit}
        base["pm_reasoning"] = {"source": "deterministic_fallback"}
        return base
    cleaned = _clean_pm_payload(raw, assumption_ids=assumption_ids, evidence_ids=evidence_ids)
    warnings = _guardrail_warnings(cleaned["assumption_rulings"], brief.get("engine_views") or [])
    if warnings:
        retry_user = dump_user(_pm_user_payload(brief, base)) + "\n\nGuardrail warnings:\n" + "\n".join(f"- {item}" for item in warnings)
        raw2, audit2 = complete_structured(
            completer,
            system=load_prompt("pm_judge.txt"),
            user=retry_user,
            allowed_ids=allowed or None,
            validator=validate_pm_payload,
        )
        if raw2:
            cleaned = _clean_pm_payload(raw2, assumption_ids=assumption_ids, evidence_ids=evidence_ids)
            audit = audit2
            warnings = _guardrail_warnings(cleaned["assumption_rulings"], brief.get("engine_views") or [])
        else:
            audit = audit2
    python_by_id = {str(row.get("assumption_id") or ""): row for row in base.get("rulings") or []}
    llm_by_id = {str(row.get("assumption_id") or ""): row for row in cleaned["assumption_rulings"]}
    rulings = []
    for assumption_id, python_row in python_by_id.items():
        if assumption_id in llm_by_id:
            row = dict(llm_by_id[assumption_id])
            row["engine_proposed_status"] = python_row.get("engine_proposed_status")
            row["statement"] = row.get("statement") or python_row.get("statement")
            row["kind"] = python_row.get("kind")
            rulings.append(row)
        else:
            fallback_row = dict(python_row)
            fallback_row["llm_omitted"] = True
            rulings.append(fallback_row)
    for item in cleaned["counterfactuals"]:
        item["python_recompute"] = _python_counterfactual(base.get("valuation") or {}, item)
    thesis = dict(base["thesis"])
    if cleaned.get("core_thesis"):
        thesis["core_thesis"] = cleaned["core_thesis"]
    if cleaned.get("short_term_view"):
        thesis["short_term_view"] = cleaned["short_term_view"]
    if cleaned.get("mid_term_view"):
        thesis["mid_term_view"] = cleaned["mid_term_view"]
    if cleaned.get("long_term_view"):
        thesis["long_term_view"] = cleaned["long_term_view"]
    core_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "core"]
    supporting_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "supporting"]
    monitoring_ids = [row["assumption_id"] for row in rulings if row.get("thesis_role") == "monitoring"]
    if core_ids:
        thesis["key_assumption_ids"] = core_ids
        thesis["core_assumption_ids"] = core_ids
        thesis["supporting_assumption_ids"] = supporting_ids
    if cleaned.get("thesis_invalidation"):
        thesis["invalidation_conditions"] = [cleaned["thesis_invalidation"]]
    if cleaned.get("next_information_to_seek"):
        thesis["monitoring_items"] = [cleaned["next_information_to_seek"]] + list(thesis.get("monitoring_items") or [])
        thesis["monitoring_items"] = list(dict.fromkeys(thesis["monitoring_items"]))[:10]
    reasoning = {
        "source": "llm",
        "core_thesis": cleaned["core_thesis"],
        "core_contradiction": cleaned["core_contradiction"],
        "decisive_variables": cleaned["decisive_variables"],
        "conviction_hierarchy": cleaned["conviction_hierarchy"],
        "market_disagreement": cleaned["market_disagreement"],
        "top_thesis_changing_evidence": cleaned["top_thesis_changing_evidence"],
        "looks_important_but_does_not_change_thesis": cleaned["looks_important_but_does_not_change_thesis"],
        "low_value_evidence": cleaned["low_value_evidence"],
        "non_thesis_changing_evidence": cleaned["non_thesis_changing_evidence"],
        "strongest_evidence": cleaned["strongest_evidence"],
        "weakest_link": cleaned["weakest_link"],
        "what_could_make_me_wrong": cleaned["what_could_make_me_wrong"],
        "most_likely_wrong": cleaned["most_likely_wrong"],
        "next_information_to_seek": cleaned["next_information_to_seek"],
        "what_would_change_my_mind": cleaned["what_would_change_my_mind"],
        "thesis_invalidation": cleaned["thesis_invalidation"],
        "valuation_driver_judgment": cleaned["valuation_driver_judgment"],
        "counterfactuals": cleaned["counterfactuals"],
        "golden_answers": cleaned["golden_answers"],
        "validation_warnings": warnings,
        "llm_audit": audit,
        "competing_hypotheses": cleaned.get("competing_hypotheses") or clip(brief.get("competing_hypotheses"), 8),
    }
    thesis["research_quality"] = dict(thesis.get("research_quality") or {})
    thesis["research_quality"]["pm_reasoning"] = reasoning
    thesis["research_quality"]["golden_answers"] = cleaned["golden_answers"]
    if audit.get("llm_status") == "ok":
        thesis["model"] = audit.get("model")
    cases = dict(base["valuation"])
    cal = dict(cases.get("calibration_json") or {})
    cal["pm_reasoning"] = reasoning
    cal["valuation_driver_judgment"] = cleaned["valuation_driver_judgment"]
    cases["calibration_json"] = cal
    return {
        **base,
        "rulings": rulings,
        "thesis": thesis,
        "valuation": cases,
        "monitoring_assumption_ids": monitoring_ids,
        "llm_audit": audit,
        "pm_reasoning": reasoning,
        "prompt_version": PROMPT_VERSION,
        "agent_name": AGENT_PM,
    }


def record_pm_judgment(
    service: Any,
    ticker: str,
    *,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Persist PM rulings, a new thesis version, and a valuation. Never used by other agents."""
    brief = build_pm_brief(service, ticker, workflow_run_id=workflow_run_id)
    if not brief.get("engine_views") and not brief.get("assumptions"):
        return {"ticker": str(ticker).upper(), "skipped": True, "reason": "no assumptions to adjudicate"}
    judgment = build_pm_judgment(brief, completer=getattr(service, "completer", None))
    previous_thesis = brief.get("previous_thesis")
    previous_valuation = brief.get("previous_valuation")
    previous_rulings = []
    lister = getattr(service.store, "list_pm_rulings", None)
    if callable(lister) and previous_thesis:
        previous_rulings = [row for row in lister(ticker) if row.get("thesis_id") == previous_thesis.get("id")]
    for ruling in judgment["rulings"]:
        assumption_id = str(ruling.get("assumption_id") or "")
        if not assumption_id:
            continue
        links = service.store.list_links(assumption_id=assumption_id)
        status = ruling["final_status"]
        if status != "unverified" and not links:
            status = "unverified"
            ruling["final_status"] = "unverified"
            ruling["reasoning"] = ruling["reasoning"] + " Status stays unverified because no evidence link exists."
        service.update_assumption_status(
            ticker,
            assumption_id,
            actor=ACTOR_PM,
            status=status,
            thesis_role=ruling["thesis_role"],
            confidence=ruling["final_confidence"],
            next_verification=ruling.get("next_verification"),
            invalidation_condition=ruling.get("invalidation_condition"),
        )
    thesis_body = dict(judgment["thesis"])
    thesis_body["workflow_run_id"] = workflow_run_id
    thesis_body["prompt_version"] = PROMPT_VERSION
    thesis_body["llm_audit"] = judgment.get("llm_audit")
    if (judgment.get("llm_audit") or {}).get("llm_status") == "ok":
        thesis_body["model"] = (judgment.get("llm_audit") or {}).get("model")
    thesis = service.create_thesis(ticker, thesis_body, actor=ACTOR_PM)
    valuation_body = {
        "thesis_id": thesis["id"],
        "horizon": judgment["valuation"].get("horizon") or "2y",
        "bear_case": judgment["valuation"]["bear_case"],
        "base_case": judgment["valuation"]["base_case"],
        "bull_case": judgment["valuation"]["bull_case"],
        "spot_price": judgment["valuation"].get("spot_price"),
        "calibration_json": judgment["valuation"].get("calibration_json") or {},
        "workflow_run_id": workflow_run_id,
        "prompt_version": PROMPT_VERSION,
        "llm_audit": judgment.get("llm_audit"),
        "model": thesis_body.get("model"),
    }
    valuation = service.create_valuation(ticker, valuation_body, actor=ACTOR_PM)
    diff = thesis_diff(
        previous_thesis,
        thesis,
        previous_valuation=previous_valuation,
        current_valuation=valuation,
        previous_rulings=previous_rulings,
        current_rulings=judgment["rulings"],
    )
    updater = getattr(service.store, "update_thesis_meta", None)
    if callable(updater):
        quality = dict(judgment.get("thesis", {}).get("research_quality") or judgment.get("research_quality") or {})
        thesis = updater(thesis["id"], thesis_diff=diff, research_quality=quality, market_reaction=judgment["market_reaction"]["summary"])
    inserter = getattr(service.store, "insert_pm_ruling", None)
    stored_rulings = []
    if callable(inserter):
        for ruling in judgment["rulings"]:
            stored_rulings.append(
                inserter(
                    {
                        **ruling,
                        "ticker": str(ticker).upper(),
                        "thesis_id": thesis["id"],
                        "workflow_run_id": workflow_run_id,
                    }
                )
            )
    return {
        "ticker": str(ticker).upper(),
        "skipped": False,
        "rulings": stored_rulings or judgment["rulings"],
        "thesis": thesis,
        "valuation": valuation,
        "thesis_diff": diff,
        "market_reaction": judgment["market_reaction"],
        "research_quality": judgment.get("thesis", {}).get("research_quality") or judgment["research_quality"],
        "deep_case": judgment.get("deep_case"),
        "pm_reasoning": judgment.get("pm_reasoning"),
        "llm_audit": judgment.get("llm_audit"),
        "prompt_version": PROMPT_VERSION,
        "produced_by": ACTOR_PM,
    }
