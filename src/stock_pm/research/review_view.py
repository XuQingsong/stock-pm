"""Read-only research review payload. No issuer-specific branches or invented numbers."""

from __future__ import annotations

from typing import Any

from .deep_case import evidence_side, synthesize_deep_case
from .extract import to_number
from .financials import display_pct
from .relevance import assumption_kind


LAYER_LABELS = {
    "customer_demand": "客户需求",
    "customer_capex": "客户资本开支",
    "site_power": "数据中心 / 电力",
    "product_deployments": "部署",
    "networking": "网络",
    "foundry_packaging": "供应链",
    "issuer_revenue": "公司收入",
    "commodity_price": "商品价格",
    "production_volume": "产量",
    "project_capex": "项目资本开支",
    "cash_generation": "现金创造",
    "end_demand": "终端需求",
    "conversion": "转化",
    "supply": "供给",
}

FAMILY_LABELS = {
    "growth_end_market": "AI / 终端需求增长",
    "core_product": "核心半导体业务",
    "software_recurring": "软件经常性收入",
    "networking": "网络",
    "production_volume": "产量",
    "commodity_price": "商品价格",
}


def _as_count(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    return 0


def _text(value: Any, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def _evidence_brief(row: dict[str, Any] | None) -> dict[str, Any]:
    item = row or {}
    url = item.get("source_url")
    excerpt = _text(item.get("excerpt") or item.get("fact"), 360)
    fact = _text(item.get("fact"), 360)
    verified = bool(url or item.get("source") or item.get("source_time"))
    return {
        "id": item.get("id"),
        "fact": fact,
        "excerpt": excerpt,
        "source": item.get("source"),
        "source_time": item.get("source_time"),
        "source_url": url,
        "source_type": item.get("source_type"),
        "side": evidence_side(item),
        "trace": "ok" if verified else "UNVERIFIED",
        "reason": item.get("reason") or item.get("link_reason"),
        "strength": item.get("strength") or item.get("link_strength"),
        "relevance": item.get("relevance") or item.get("link_relevance"),
    }


def _index_evidence(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("id") or "")
        if key:
            out[key] = row
    return out


def _lookup_evidence(ids: list[Any], index: dict[str, dict[str, Any]], *, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    found = []
    seen: set[str] = set()
    for item in ids or []:
        key = str(item or "")
        if not key or key in seen:
            continue
        seen.add(key)
        row = dict(index.get(key) or {"id": key, "fact": None, "source": None})
        if extra:
            row = {**row, **extra}
        brief = _evidence_brief(row)
        if not index.get(key):
            brief["trace"] = "UNVERIFIED"
        found.append(brief)
        if len(found) >= 6:
            break
    return found


def _case_brief(case: dict[str, Any] | None) -> dict[str, Any]:
    row = case or {}
    growth = row.get("growth_assumptions") if isinstance(row.get("growth_assumptions"), dict) else {}
    margin = row.get("margin_assumptions") if isinstance(row.get("margin_assumptions"), dict) else {}
    return {
        "growth": growth.get("annual_rate") if growth else row.get("growth"),
        "growth_display": growth.get("display") or display_pct(growth.get("annual_rate") if growth else row.get("growth")),
        "growth_origin": growth.get("origin"),
        "margin": margin.get("net") or margin.get("operating") or row.get("margin"),
        "eps": row.get("eps"),
        "multiple": row.get("multiple"),
        "target": row.get("target_display") or row.get("target_value"),
        "origin": growth.get("origin") or row.get("valuation_method"),
        "confidence": row.get("confidence") or row.get("notes"),
        "method": row.get("valuation_method"),
        "narrative": _text(row.get("case_narrative") or row.get("notes"), 280),
    }


def _ledger_row(row: dict[str, Any]) -> dict[str, Any]:
    from .review_copy import _horizon_zh, _metric_zh, zh_gap, zh_origin, zh_status

    status = row.get("current_status") or row.get("status") or "unresolved"
    source = row.get("source")
    return {
        "commitment": row.get("commitment"),
        "date": row.get("date"),
        "source": source,
        "source_zh": zh_origin(source),
        "source_url": row.get("source_url"),
        "time_horizon": row.get("time_horizon"),
        "time_horizon_zh": _horizon_zh(row.get("time_horizon")),
        "metric": row.get("metric"),
        "metric_zh": _metric_zh(row.get("metric")),
        "stated_value_or_range": row.get("stated_value_or_range"),
        "status": status,
        "status_zh": zh_status(status),
        "delivery_status": row.get("delivery_status") or status,
        "next_check": row.get("next_check"),
        "next_check_zh": zh_gap(row.get("next_check")),
        "trace": "ok" if (source or row.get("source_url") or row.get("source_id")) else "UNVERIFIED",
    }


def _range_display(payload: dict[str, Any] | None) -> str | None:
    row = payload or {}
    low = row.get("low")
    high = row.get("high")
    if low is None and high is None:
        return None
    left = display_pct(low) or "Missing"
    right = display_pct(high) or "Missing"
    return f"{left} – {right}"


def _compact_thesis(thesis: dict[str, Any], golden: dict[str, Any]) -> tuple[str, str]:
    full = str(thesis.get("core_thesis") or golden.get("core_thesis") or "").strip() or "Missing"
    compact = str(golden.get("core_thesis") or "").strip()
    if compact and (full == "Missing" or len(full) > max(len(compact) + 40, 420)):
        return compact, full
    if len(full) > 520:
        return full[:520].rsplit(" ", 1)[0] + "…", full
    return full, full


def _spot(value: Any) -> float | None:
    number = to_number(value)
    if number is None:
        return None
    return round(float(number), 2)


def _prefer_demand(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> int:
        hay = str(row.get("fact") or "").lower()
        pts = 0
        for token, weight in (
            ("capital expend", 5),
            ("capex", 5),
            ("data center", 4),
            ("deploy", 3),
            ("custom silicon", 4),
            ("accelerator", 3),
            ("power", 2),
        ):
            if token in hay:
                pts += weight
        return pts

    ranked = sorted(rows, key=score, reverse=True)
    return [_evidence_brief(row) for row in ranked[:limit]]


def _deep_case(snapshot: dict[str, Any]) -> dict[str, Any]:
    valuation = snapshot.get("valuation") or {}
    cal = valuation.get("calibration_json") if isinstance(valuation.get("calibration_json"), dict) else {}
    stored = cal.get("deep_case") or valuation.get("deep_case")
    synthesized = synthesize_deep_case(
        snapshot.get("pack"),
        evidence=snapshot.get("evidence") or [],
        rulings=snapshot.get("pm_rulings") or [],
        valuation=valuation,
        mapping=(cal.get("driver_map") or valuation.get("driver_map") or []),
        ticker=snapshot.get("ticker"),
    )
    if isinstance(stored, dict) and stored.get("causal_chain"):
        merged = dict(synthesized)
        merged.update(stored)
        for key, value in synthesized.items():
            current = merged.get(key)
            if current in (None, [], {}, ""):
                merged[key] = value
            elif isinstance(current, dict) and isinstance(value, dict):
                nested = dict(value)
                nested.update(current)
                for nested_key, nested_value in value.items():
                    if nested.get(nested_key) in (None, [], ""):
                        nested[nested_key] = nested_value
                merged[key] = nested
        if not merged.get("golden_answers"):
            merged["golden_answers"] = synthesized.get("golden_answers") or {}
        return merged
    return synthesized


def _enrich_tree(tree: dict[str, Any], rulings: list[dict[str, Any]], evidence_index: dict[str, dict[str, Any]], assumptions: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(row.get("assumption_id") or row.get("id")): row for row in rulings if row.get("assumption_id") or row.get("id")}
    assumption_by_id = {str(row.get("id")): row for row in assumptions}
    branches = []
    for branch in tree.get("branches") or []:
        nodes = []
        for node in branch.get("nodes") or []:
            aid = str(node.get("assumption_id") or "")
            ruling = by_id.get(aid) or {}
            assumption = assumption_by_id.get(aid) or {}
            links = list(assumption.get("links") or [])
            support_ids = list(node.get("support") or ruling.get("key_supporting_evidence_ids") or [])
            oppose_ids = list(node.get("oppose") or ruling.get("key_opposing_evidence_ids") or [])
            support_links = [row for row in links if row.get("direction") == "support"]
            oppose_links = [row for row in links if row.get("direction") == "oppose"]
            if not support_ids:
                support_ids = [row.get("evidence_id") for row in support_links]
            if not oppose_ids:
                oppose_ids = [row.get("evidence_id") for row in oppose_links]
            reason_by_id = {str(row.get("evidence_id")): row for row in links}
            support = []
            for brief in _lookup_evidence(support_ids, evidence_index):
                link = reason_by_id.get(str(brief.get("id")) or "")
                if link:
                    brief["reason"] = link.get("reason")
                    brief["strength"] = link.get("strength")
                    brief["relevance"] = link.get("relevance")
                support.append(brief)
            oppose = []
            for brief in _lookup_evidence(oppose_ids, evidence_index):
                link = reason_by_id.get(str(brief.get("id")) or "")
                if link:
                    brief["reason"] = link.get("reason")
                    brief["strength"] = link.get("strength")
                    brief["relevance"] = link.get("relevance")
                oppose.append(brief)
            unresolved = list(node.get("unresolved") or ruling.get("unresolved_gaps") or [])
            nodes.append(
                {
                    "assumption_id": aid,
                    "statement": node.get("statement") or ruling.get("statement"),
                    "status": node.get("status") or ruling.get("final_status") or assumption.get("status") or "unverified",
                    "confidence": node.get("confidence") or ruling.get("final_confidence") or assumption.get("confidence"),
                    "thesis_role": node.get("thesis_role") or ruling.get("thesis_role") or assumption.get("thesis_role"),
                    "kind": ruling.get("kind") or assumption_kind(ruling or assumption),
                    "supporting_count": len(support_ids),
                    "opposing_count": len(oppose_ids),
                    "unresolved_count": len(unresolved),
                    "supporting": support,
                    "opposing": oppose,
                    "unresolved": unresolved,
                    "next_verification": node.get("next_verification") or ruling.get("next_verification") or assumption.get("next_verification"),
                    "invalidation": ruling.get("invalidation_condition"),
                    "reasoning": ruling.get("reasoning"),
                }
            )
        branches.append({"id": branch.get("id"), "title": branch.get("title"), "nodes": nodes})
    return {"core_thesis": tree.get("core_thesis"), "branches": branches}


def _monitor(golden: dict[str, Any], thesis: dict[str, Any], chain: dict[str, Any], customers: dict[str, Any], delivery: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    events = golden.get("thesis_events") or {}
    items = [item for item in (golden.get("monitor") or thesis.get("monitoring_items") or []) if item][:5]
    profile = pack.get("company_profile") or {}
    weakest = chain.get("weakest_link")
    out = []
    for text in items:
        hay = str(text).lower()
        state = "unresolved"
        next_check = "next official update"
        if "print" in hay or "outlook" in hay:
            state = delivery.get("credibility") or delivery.get("summary") or "delivery ledger incomplete"
            next_check = "next official print versus stated outlook"
        elif "customer capex" in hay or "deployment" in hay or "independent customer" in hay:
            state = customers.get("conclusion") or "customer-side confirmation unresolved"
            next_check = "independent customer capex / deployment commentary"
        elif "weakest" in hay or (weakest and weakest.replace("_", " ") in hay):
            layer = next((row for row in (chain.get("layers") or []) if row.get("layer") == weakest), {})
            state = f"weakest layer {weakest}: " + "; ".join(layer.get("unresolved") or ["unresolved"])
            next_check = f"re-check {weakest}"
        elif "margin" in hay or "mix" in hay:
            margin = profile.get("gross_margin_pct") or profile.get("operating_margin_pct") or profile.get("net_margin_pct")
            state = f"reported margin context {margin}" if margin is not None else "margin / mix not independently resolved"
            next_check = "net vs operating margin and mix"
        elif "concentration" in hay:
            state = "customer concentration remains a duration constraint unless share is re-stated"
            next_check = "customer concentration share of revenue"
        out.append(
            {
                "item": text,
                "current_state": state,
                "next_check": next_check,
                "strengthen": events.get("strengthen") or "Missing",
                "weaken": events.get("weaken") or "Missing",
                "break_condition": events.get("break") or "Missing",
            }
        )
    return out


def _reaction_groups(reaction: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    def wrap(items: list[Any]) -> list[dict[str, Any]]:
        out = []
        for item in items or []:
            text = _text(item, 280)
            matches = []
            tokens = [token for token in text.lower().replace(";", " ").split() if len(token) > 5][:4]
            for row in evidence:
                hay = str(row.get("fact") or "").lower()
                if tokens and sum(1 for token in tokens if token in hay) >= 1:
                    matches.append(_evidence_brief(row))
                if len(matches) >= 3:
                    break
            out.append({"text": text, "evidence": matches, "trace": "ok" if matches else "UNVERIFIED"})
        return out

    return {
        "applicable": reaction.get("applicable"),
        "summary": reaction.get("summary"),
        "confirmed": wrap(reaction.get("confirmed") or []),
        "plausible_unconfirmed": wrap(reaction.get("plausible_unconfirmed") or []),
        "unresolved": wrap(reaction.get("unresolved") or []),
    }


def build_research_review(service: Any, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    snapshot = service.research_snapshot(symbol, prefer_frozen=True)
    pack = snapshot.get("pack") or {}
    thesis = snapshot.get("thesis") or service.empty_thesis(symbol)
    valuation = snapshot.get("valuation") or service.empty_valuation(symbol)
    evidence = list(snapshot.get("evidence") or [])
    assumptions = list(snapshot.get("assumptions") or [])
    rulings = list(snapshot.get("pm_rulings") or [])
    evidence_index = _index_evidence(evidence)
    deep = _deep_case(snapshot)
    golden = deep.get("golden_answers") or (thesis.get("research_quality") or {}).get("golden_answers") or {}
    customers = deep.get("customer_side_evidence") or {}
    delivery = deep.get("delivery_history") or {}
    chain = deep.get("causal_chain") or {}
    bridge = deep.get("revenue_bridge") or {}
    implied = deep.get("market_implied") or {}
    reaction = deep.get("market_reaction") or {}
    tree = _enrich_tree(deep.get("assumption_tree") or {"core_thesis": thesis.get("core_thesis"), "branches": []}, rulings, evidence_index, assumptions)
    columns = deep.get("case_columns") or {}
    cal = valuation.get("calibration_json") if isinstance(valuation.get("calibration_json"), dict) else {}
    missing_fields = list(pack.get("missing_fields") or [])
    missing = []
    if thesis.get("status") == "missing" or not thesis.get("core_thesis"):
        missing.append("investment thesis")
    if valuation.get("status") == "missing" or not valuation.get("base_case"):
        missing.append("valuation")
    if "fcf" in missing_fields:
        missing.append("FCF")
    if bridge.get("origin") == "estimated" or bridge.get("mode") == "top_down_range":
        missing.append("official segment mix")
    if not customers.get("named_issuer_cross_check_present"):
        missing.append("independent customer contract confirmation")
    if int(delivery.get("prints_scored") or 0) < 6:
        missing.append("scored delivery sample shorter than 6 quarters")
    for field in missing_fields:
        label = "FCF" if str(field).lower() == "fcf" else str(field).replace("_", " ")
        if label not in missing and str(field).lower() not in {str(item).lower() for item in missing}:
            missing.append(label)

    named = bool(customers.get("named_issuer_cross_check_present"))
    confirmation_layers = {"customer_capex", "customer_demand", "end_demand", "product_deployments"}
    layers = []
    for row in chain.get("layers") or []:
        name = str(row.get("layer") or "")
        unresolved = list(row.get("unresolved") or [])
        family = (
            "independent_customer"
            if row.get("independent_customer_hits")
            else ("issuer_management" if row.get("issuer_hits") else "missing")
        )
        confidence = row.get("confidence")
        bottleneck = bool(row.get("bottleneck"))
        if not named and name in confirmation_layers:
            note = "industry demand hits are not a named-issuer contract confirmation"
            if note not in unresolved:
                unresolved.append(note)
            if family == "independent_customer":
                family = "industry_demand_only"
            confidence = "low"
            bottleneck = True
        layers.append(
            {
                "layer": name,
                "label": LAYER_LABELS.get(name, name.replace("_", " ").title()),
                "confidence": confidence,
                "bottleneck": bottleneck,
                "unresolved": unresolved,
                "issuer_hits": row.get("issuer_hits") or 0,
                "independent_customer_hits": row.get("independent_customer_hits") or 0,
                "evidence_family": family,
                "evidence": row.get("evidence") or [],
                "weakest": False,
            }
        )
    weakest_name = chain.get("weakest_link")
    if not named:
        present = [row["layer"] for row in layers if row["layer"] in confirmation_layers]
        for candidate in ("customer_capex", "customer_demand", "end_demand"):
            if candidate in present:
                weakest_name = candidate
                break
        else:
            weakest_name = present[0] if present else weakest_name
    for row in layers:
        row["weakest"] = row["layer"] == weakest_name
    chain = {**chain, "weakest_link": weakest_name, "layers": layers}

    bridge_lines = []
    for row in bridge.get("lines") or []:
        family = str(row.get("family") or "")
        bridge_lines.append(
            {
                **row,
                "label": row.get("name") or FAMILY_LABELS.get(family, family or "unknown / missing"),
            }
        )
    if bridge.get("origin") == "estimated" or not bridge_lines:
        bridge_lines.append({"label": "unknown / missing", "origin": "estimated", "latest_print_revenue": None, "note": "official mix not in pack"})

    fragile = golden.get("fragile_assumption") or {}
    strongest = golden.get("strongest_assumption") or {}
    gap = None
    for item in fragile.get("unresolved") or []:
        gap = item
        break
    if not gap:
        weakest_layer = next((row for row in layers if row.get("weakest")), {})
        gap = (weakest_layer.get("unresolved") or ["unresolved"])[0] if weakest_layer else "unresolved"

    store = getattr(service, "store", None)
    theses = store.list_theses(symbol) if store and hasattr(store, "list_theses") else []
    history = []
    for row in theses:
        diff = row.get("thesis_diff") or {}
        history.append(
            {
                "id": row.get("id"),
                "version": row.get("version"),
                "created_at": row.get("created_at"),
                "confidence": row.get("confidence"),
                "core_thesis": _text(row.get("core_thesis"), 400),
                "valuation_id": row.get("valuation_id"),
                "what_changed": diff.get("what_changed") or diff.get("thesis_change") or ("initial thesis" if row.get("version") == 1 else "thesis version incremented"),
                "strengthened_assumptions": diff.get("strengthened_assumptions") or [],
                "weakened_assumptions": diff.get("weakened_assumptions") or [],
                "valuation_change": diff.get("valuation_change"),
                "confidence_change": diff.get("confidence_change"),
                "unresolved": (row.get("research_quality") or {}).get("unresolved") if isinstance(row.get("research_quality"), dict) else None,
                "thesis_diff": diff,
            }
        )

    profile = pack.get("company_profile") or {}
    status = cal.get("valuation_status") or valuation.get("valuation_status") or valuation.get("status")
    why_provisional = []
    if status == "provisional":
        if "fcf" in missing_fields:
            why_provisional.append("FCF missing")
        if bridge.get("origin") == "estimated" or "segment_mix" in missing_fields or "segment_growth" in missing_fields:
            why_provisional.append("official segment mix missing")
        if not why_provisional:
            why_provisional = [item for item in missing if item not in {"investment thesis", "valuation"}][:4]
    compact, full_thesis = _compact_thesis(thesis, golden)
    spot = _spot(profile.get("last_close") or valuation.get("spot_price"))

    payload = {
        "ticker": symbol,
        "legal_name": profile.get("legal_name") or symbol,
        "template_id": pack.get("template_id"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_status": snapshot.get("snapshot_status"),
        "snapshot_manifest": snapshot.get("manifest") or {},
        "hero": {
            "core_thesis": compact,
            "core_thesis_full": full_thesis,
            "confidence": thesis.get("confidence"),
            "short_term_view": thesis.get("short_term_view") or "Missing",
            "mid_term_view": thesis.get("mid_term_view") or "Missing",
            "long_term_view": thesis.get("long_term_view") or "Missing",
            "valuation_status": status or "Missing",
            "why_provisional": why_provisional,
            "top_assumptions": golden.get("top_assumptions") or [],
            "strongest_assumption": strongest,
            "weakest_assumption": fragile,
            "weakest_layer": chain.get("weakest_link") or "Missing",
            "biggest_unresolved_gap": gap or "Missing",
            "spot": spot,
            "customer_direct": _as_count(customers.get("direct_issuer_cross_check")),
            "customer_category": _as_count(customers.get("category_cross_check")),
            "industry_demand": bool(customers.get("industry_demand_only") or customers.get("demand_side_hits_present")),
        },
        "cases": {
            "bear": _case_brief(columns.get("bear") or valuation.get("bear_case")),
            "market_implied": _case_brief(columns.get("market_implied") or implied.get("case")),
            "base": _case_brief(columns.get("base") or valuation.get("base_case")),
            "bull": _case_brief(columns.get("bull") or valuation.get("bull_case")),
        },
        "assumption_tree": tree,
        "commitment_ledger": [_ledger_row(row) for row in (deep.get("commitment_ledger") or [])],
        "delivery_history": delivery,
        "customer_side": {
            "conclusion": customers.get("conclusion") or "Missing",
            "direct_issuer_cross_check": _as_count(customers.get("direct_issuer_cross_check")),
            "category_cross_check": _as_count(customers.get("category_cross_check")),
            "industry_demand_confirmation": bool(customers.get("industry_demand_only") or customers.get("demand_side_hits_present")),
            "named_issuer_cross_check_present": bool(customers.get("named_issuer_cross_check_present")),
            "search_program": customers.get("search_program") or {},
            "issuer_management": _prefer_demand(customers.get("issuer_management") or [], 8),
            "independent_customer": _prefer_demand(customers.get("independent_customer") or [], 8),
            "industry_third_party": _prefer_demand(customers.get("industry_third_party") or [], 8),
            "industry_demand_only": _prefer_demand(customers.get("industry_demand_only") or [], 8),
            "note": customers.get("note"),
        },
        "revenue_bridge": {
            "current_revenue": bridge.get("current_revenue"),
            "mode": bridge.get("mode") or "Missing",
            "origin": bridge.get("origin") or "Missing",
            "lines": bridge_lines,
            "note": bridge.get("note"),
        },
        "causal_chain": {
            "weakest_link": chain.get("weakest_link"),
            "layers": layers,
            "note": chain.get("note"),
        },
        "market_implied": {
            "title": "当前股价隐含的增长预期",
            "spot": spot,
            "market_comparison_status": implied.get("market_comparison_status") or ("unavailable" if spot in (None, 0) else "available"),
            "reason": implied.get("reason") if implied.get("market_comparison_status") == "unavailable" or spot in (None, 0) else None,
            "market_implied_under_base_multiple": implied.get("market_implied_under_base_multiple"),
            "sensitivity": implied.get("sensitivity") or [],
            "market_implied_range": implied.get("market_implied_range"),
            "market_implied_range_display": _range_display(implied.get("market_implied_range")),
            "vs_pm_base": implied.get("vs_pm_base") or "Missing",
            "vs_pm_bull": implied.get("vs_pm_bull") or "Missing",
            "pm_base_growth": implied.get("base_growth") or implied.get("pm_base_growth"),
            "pm_bull_growth": implied.get("bull_growth") or implied.get("pm_bull_growth"),
            "pm_wording": implied.get("pm_wording") or implied.get("summary"),
        },
        "market_reaction": _reaction_groups(reaction, evidence),
        "valuation": {
            "status": status or "Missing",
            "why_provisional": why_provisional,
            "missing_fields": missing_fields,
            "method": valuation.get("method") or cal.get("method"),
        },
        "monitoring": _monitor(golden, thesis, chain, customers, delivery, pack),
        "thesis_history": history,
        "missing": missing,
        "quality": snapshot.get("research_quality_axes") or thesis.get("research_quality") or {},
    }
    from .pm_desk import build_pm_desk
    from .review_copy import build_review_ui

    payload["pm_reasoning"] = build_pm_desk(thesis=thesis, snapshot=snapshot, evidence=evidence)
    payload["ui"] = build_review_ui(payload)
    return payload
