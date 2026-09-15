"""PM/Judge: the only actor that writes assumption status, thesis, and valuation."""

from __future__ import annotations

import re
from typing import Any

from .assumptions import engine_views_for_ticker
from .deep_case import build_delivery_history, reaction_window, synthesize_deep_case
from .extract import to_number
from .quality import assess_research_quality_axes
from .relevance import CONTRACT_RE, HARD_COUNTER_RE, assumption_kind
from .types import (
    ACTOR_PM,
    AGENT_PM,
    ASSUMPTION_STATUSES,
    NEGATIVE_MARKET_REACTION_TASK,
    THESIS_ROLE_ALIASES,
)
from .valuation import attribute_target_change, build_valuation_cases, display_target


PROMPT_VERSION = "sprint5-pm-v2"
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


def build_pm_judgment(brief: dict[str, Any]) -> dict[str, Any]:
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
    judgment = build_pm_judgment(brief)
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
        thesis = updater(thesis["id"], thesis_diff=diff, research_quality=judgment["research_quality"], market_reaction=judgment["market_reaction"]["summary"])
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
        "research_quality": judgment["research_quality"],
        "deep_case": judgment.get("deep_case"),
        "prompt_version": PROMPT_VERSION,
        "produced_by": ACTOR_PM,
    }
