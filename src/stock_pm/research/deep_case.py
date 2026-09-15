"""Template-driven deep-case synthesis. No issuer-specific branches."""

from __future__ import annotations

from typing import Any

from .extract import (
    beat_label,
    extract_commitments,
    extract_guidance_mentions,
    materials_text,
    to_number,
)
from .financials import coarsen_growth, display_pct, display_pct_range, lineage
from .relevance import CAPEX_RE, CONC_RE, CONTRACT_RE, DEMAND_RE, POWER_RE, SUPPLY_RE, assumption_kind
from .templates import load_template
from .valuation import display_target, round_target


ISSUER_SOURCE_TYPES = {
    "transcript",
    "earnings_release",
    "investor_presentation",
    "conference_remarks",
    "press_release",
    "official_document",
    "sec_filing",
}

CHAIN_BY_TEMPLATE = {
    "semiconductor": (
        ("customer_demand", ("customer", "demand", "hyperscal", "end market", "ai")),
        ("customer_capex", ("capex", "capital expend", "capital spend")),
        ("site_power", ("power", "electric", "data center", "data-center", "grid", "site")),
        ("product_deployments", ("deploy", "accelerator", "asic", "custom silicon", "xpu", "cluster")),
        ("networking", ("network", "optical", "ethernet", "switching", "datacom")),
        ("foundry_packaging", ("foundry", "packag", "wafer", "supply", "capacity")),
        ("issuer_revenue", ("revenue", "guidance", "outlook", "segment")),
    ),
    "energy": (
        ("commodity_price", ("commodity", "brent", "wti", "realized", "oil", "gas")),
        ("production_volume", ("production", "volume", "barrel", "boe", "upstream")),
        ("project_capex", ("capex", "capital expend", "project", "sanction")),
        ("cash_generation", ("free cash", "fcf", "earnings", "return")),
    ),
    "generic_company": (
        ("end_demand", ("customer", "demand", "order", "pipeline")),
        ("conversion", ("contract", "convert", "recognize", "deliver")),
        ("supply", ("supply", "capacity", "production")),
        ("issuer_revenue", ("revenue", "guidance", "outlook")),
    ),
}

TREE_BRANCHES = (
    ("A", "Demand", {"demand_visibility", "demand", "growth_end_market", "near_term_revenue"}),
    ("B", "Execution", {"execution", "supply", "contract_conversion", "foundry", "packaging"}),
    ("C", "Economics", {"margin", "growth_persist", "fcf", "normalized_earnings", "cash_generation", "guidance"}),
    ("D", "Market", {"concentration", "valuation", "competition"}),
)


def _issuer_owned_channel(item: dict[str, Any], ticker: str | None = None) -> bool:
    payload = item or {}
    symbol = str(ticker or payload.get("ticker") or "").lower()
    source_type = str(payload.get("source_type") or "").lower()
    source = str(payload.get("source") or "").lower()
    url = str(payload.get("source_url") or "").lower()
    if symbol and symbol in url and any(token in url for token in ("transcript", "earnings", "investor", "sec.gov")):
        return True
    if source_type in {"transcript", "earnings_release", "investor_presentation"} and source not in {"web_search"}:
        return True
    if "earnings call" in source or source == "earnings_release":
        return True
    return False


def evidence_side(row: dict[str, Any] | None, ticker: str | None = None) -> str:
    """Issuer management claim vs independent customer/industry confirmation. Never mixed."""
    item = row or {}
    raw = item.get("raw_reference") if isinstance(item.get("raw_reference"), dict) else {}
    explicit = str(
        item.get("evidence_side")
        or item.get("independence_family")
        or raw.get("evidence_side")
        or raw.get("independence_family")
        or ""
    ).strip()
    if _issuer_owned_channel(item, ticker):
        return "issuer_management"
    if explicit == "independent_customer":
        url = str(item.get("source_url") or "").lower()
        source = str(item.get("source") or "").lower()
        if source == "web_search" and "sec.gov" not in url:
            return "industry_third_party"
        return explicit
    if explicit in {"issuer_management", "industry_third_party", "market"}:
        return explicit
    evidence_type = str(item.get("evidence_type") or "").lower()
    if evidence_type == "quant":
        return "market"
    fact = str(item.get("fact") or item.get("excerpt") or "").lower()
    source = str(item.get("source") or "").lower()
    source_type = str(item.get("source_type") or "").lower()
    customerish = bool(
        DEMAND_RE.search(fact)
        or CAPEX_RE.search(fact)
        or "hyperscal" in fact
        or "customer" in fact
        or "deploy" in fact
    )
    issuerish = any(token in source for token in ("earnings", "transcript", "company", "issuer", "ir ")) or source_type in {
        "transcript",
        "earnings_release",
        "investor_presentation",
    }
    if source_type == "web_search" or source == "web_search":
        if issuerish or _issuer_owned_channel(item, ticker):
            return "issuer_management"
        url = str(item.get("source_url") or item.get("source") or "").lower()
        filingish = any(token in url or token in fact for token in ("sec.gov", "10-q", "10-k", "10q", "10k"))
        if customerish and filingish:
            return "independent_customer"
        return "industry_third_party"
    if customerish and ("customer 10-" in fact or "customer filing" in source or "customer earnings" in source):
        return "independent_customer"
    if "competitor" in fact or "market share" in fact or evidence_type in {"industry", "competitive"}:
        if issuerish:
            return "issuer_management"
        return "industry_third_party"
    if source_type in ISSUER_SOURCE_TYPES or issuerish:
        return "issuer_management"
    if customerish:
        return "independent_customer"
    return "industry_third_party"


def stamp_evidence_side(item: dict[str, Any], *, query: str | None = None, ticker: str | None = None) -> dict[str, Any]:
    """Persist issuer vs customer vs industry family on the evidence row. Never overwrites independence_key."""
    del query
    payload = item or {}
    raw = dict(payload.get("raw_reference") or {})
    side = evidence_side(payload, ticker=ticker or payload.get("ticker"))
    payload["evidence_side"] = side
    payload["independence_family"] = side
    raw["evidence_side"] = side
    raw["independence_family"] = side
    payload["raw_reference"] = raw
    return payload


def _metric_from_quote(quote: str) -> str:
    hay = quote.lower()
    if "margin" in hay:
        return "margin"
    if any(token in hay for token in ("ai", "accelerat", "custom silicon", "asic")):
        return "growth_end_market"
    if any(token in hay for token in ("software", "subscription", "vmware")):
        return "software"
    if any(token in hay for token in ("contract", "multi-year", "lease", "committed")):
        return "contract"
    if any(token in hay for token in ("capacity", "deploy", "foundry", "packag")):
        return "capacity"
    if "eps" in hay or "earnings" in hay:
        return "eps"
    if "revenue" in hay or "sales" in hay:
        return "revenue"
    return "other"


def _horizon_from_quote(quote: str) -> str:
    hay = quote.lower()
    if "next quarter" in hay or "this quarter" in hay:
        return "next_quarter"
    if "full-year" in hay or "full year" in hay or "fy" in hay:
        return "fy"
    if "multi-year" in hay or "long-term" in hay or "long term" in hay or "next 3" in hay or "next five" in hay:
        return "multi_year"
    return "unspecified"


def build_commitment_ledger(
    pack: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    payload = pack or {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    text = materials_text(payload)
    extracted = extract_commitments(text) + extract_guidance_mentions(text)
    for item in extracted:
        quote = str(item.get("quote") or "").strip()
        key = quote.lower()[:180]
        if not quote or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "commitment": quote,
                "date": None,
                "source": "official_materials",
                "time_horizon": _horizon_from_quote(quote),
                "metric": _metric_from_quote(quote),
                "stated_value_or_range": None,
                "current_status": "promised",
                "supporting_evidence": [],
                "counter_evidence": [],
                "next_check": "next official print versus the stated claim",
                "origin": "issuer_management",
            }
        )
    for row in evidence or []:
        fact = str(row.get("fact") or "").strip()
        if not fact:
            continue
        key = fact.lower()[:180]
        if key in seen:
            continue
        if not (extract_commitments(fact) or extract_guidance_mentions(fact) or CONTRACT_RE.search(fact)):
            continue
        seen.add(key)
        side = evidence_side(row)
        rows.append(
            {
                "commitment": fact[:280],
                "date": str(row.get("source_time") or "")[:10] or None,
                "source": row.get("source"),
                "source_id": row.get("id"),
                "source_url": row.get("source_url"),
                "time_horizon": _horizon_from_quote(fact),
                "metric": _metric_from_quote(fact),
                "stated_value_or_range": None,
                "current_status": "promised" if side == "issuer_management" else "externally_noted",
                "supporting_evidence": [row.get("id")] if row.get("id") else [],
                "counter_evidence": [],
                "next_check": "re-check delivery versus this claim in the next report",
                "origin": side,
            }
        )
    return rows[:24]


def _iso_date(value: Any):
    text = str(value or "")[:10]
    if len(text) < 10:
        return None
    try:
        from datetime import date as date_cls

        return date_cls.fromisoformat(text)
    except ValueError:
        return None


def _dedupe_prints(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        stamp = _iso_date(row.get("report_date") or row.get("period_end"))
        match = None
        if stamp is not None:
            for prev in kept:
                prev_stamp = _iso_date(prev.get("report_date") or prev.get("period_end"))
                if prev_stamp is not None and abs((stamp - prev_stamp).days) <= 10:
                    match = prev
                    break
        if match is None:
            kept.append(row)
            continue
        better = to_number(row.get("eps_estimate")) is not None and to_number(match.get("eps_estimate")) is None
        better = better or (
            to_number(row.get("revenue_estimate")) is not None and to_number(match.get("revenue_estimate")) is None
        )
        if better:
            kept[kept.index(match)] = row
    return kept[:8]


def reaction_window(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Prefer a high-volume down window after a print, not merely the latest bar."""
    rows = list((pack or {}).get("price_reaction_history") or [])
    scored = []
    for row in rows:
        post = to_number(row.get("post_1d_return_pct") or row.get("day_return_pct"))
        vol = to_number(row.get("volume_vs_20d_avg"))
        if post is None:
            continue
        scored.append((row, post, vol or 0.0))
    negative_heavy = [item for item in scored if item[1] < 0 and item[2] >= 1.5]
    if negative_heavy:
        return negative_heavy[0][0]
    negative = [item for item in scored if item[1] < 0]
    if negative:
        return negative[0][0]
    return rows[0] if rows else {}


def build_delivery_history(pack: dict[str, Any] | None) -> dict[str, Any]:
    earnings = _dedupe_prints(list((pack or {}).get("earnings_history") or []))
    guidance = list((pack or {}).get("guidance_history") or [])
    history: list[dict[str, Any]] = []
    counts = {"beat": 0, "met": 0, "missed": 0, "revised": 0, "unscored": 0}
    for row in earnings:
        rev = beat_label(to_number(row.get("revenue")), to_number(row.get("revenue_estimate")))
        eps = beat_label(to_number(row.get("eps")), to_number(row.get("eps_estimate")))
        period = str(row.get("fiscal_period") or row.get("report_date") or "")
        move = None
        for item in guidance:
            blob = " ".join(str(item.get(key) or "") for key in ("text", "quote", "fiscal_period", "source_time"))
            if period and period in blob:
                move = str(item.get("move") or "").lower() or None
                break
        if move is None and guidance:
            first = str((guidance[0] or {}).get("move") or "").lower()
            if first in {"raised", "lowered", "maintained"}:
                move = first
        outcome = None
        if rev == "miss" or eps == "miss":
            outcome = "missed"
        elif rev == "beat" or eps == "beat":
            outcome = "beat"
        elif rev == "inline" or eps == "inline":
            outcome = "met"
        if move in {"lowered", "raised"}:
            counts["revised"] += 1
        if outcome:
            counts[outcome] += 1
        else:
            counts["unscored"] += 1
        history.append(
            {
                "period": period,
                "report_date": row.get("report_date"),
                "revenue": outcome_label(rev),
                "eps": outcome_label(eps),
                "guidance_move": move,
                "outcome": outcome or "unscored",
            }
        )
    scored = counts["beat"] + counts["met"] + counts["missed"]
    beat_rate = round(counts["beat"] / scored, 3) if scored else None
    miss_rate = round(counts["missed"] / scored, 3) if scored else None
    summary = (
        f"{counts['beat']} beat / {counts['met']} met / {counts['missed']} missed across {scored} scored prints; "
        f"{counts['revised']} guidance revisions in the same window"
        if scored
        else "not enough consensus-versus-actual prints to score delivery"
    )
    return {
        "history": history,
        "beat": counts["beat"],
        "met": counts["met"],
        "missed": counts["missed"],
        "revised": counts["revised"],
        "prints_scored": scored,
        "beat_rate": beat_rate,
        "miss_rate": miss_rate,
        "summary": summary,
        "note": "history is retained; beat_rate is a summary, not a substitute for the ledger",
    }


def outcome_label(value: str | None) -> str | None:
    if value == "inline":
        return "met"
    if value == "miss":
        return "missed"
    return value


def customer_side_evidence(evidence: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = list(evidence or [])
    issuer = [row for row in rows if evidence_side(row) == "issuer_management"]
    customer = [row for row in rows if evidence_side(row) == "independent_customer"]
    industry = [row for row in rows if evidence_side(row) == "industry_third_party"]
    return {
        "issuer_management": _brief_evidence(issuer),
        "independent_customer": _brief_evidence(customer),
        "industry_third_party": _brief_evidence(industry),
        "independent_confirmation_present": bool(customer),
        "note": "issuer claims and independent customer confirmation are separate evidence families",
    }


def _brief_evidence(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    out = []
    for row in rows[:limit]:
        out.append(
            {
                "id": row.get("id"),
                "fact": str(row.get("fact") or "")[:280],
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "source_time": row.get("source_time"),
                "source_type": row.get("source_type"),
                "side": evidence_side(row),
            }
        )
    return out


def build_revenue_bridge(pack: dict[str, Any] | None, valuation: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = pack or {}
    template_id = str(payload.get("template_id") or "generic_company")
    profile = payload.get("company_profile") or {}
    current = to_number(profile.get("revenue_ttm"))
    existing = (valuation or {}).get("forward_revenue_bridge") or (valuation or {}).get("calibration_json", {}).get("forward_revenue_bridge")
    latest = (payload.get("earnings_history") or [{}])[0] or {}
    lines = []
    total = 0.0
    for item in latest.get("segments") or []:
        name = str(item.get("name") or "").strip()
        rev = to_number(item.get("revenue"))
        yoy = to_number(item.get("growth_yoy_pct"))
        if rev:
            total += float(rev)
        family = "core_product"
        hay = name.lower()
        if any(token in hay for token in ("ai", "custom", "accelerat", "asic", "xpu")):
            family = "growth_end_market"
        elif any(token in hay for token in ("software", "subscription", "vmware")):
            family = "software_recurring"
        elif any(token in hay for token in ("network", "optical")):
            family = "networking"
        lines.append(
            {
                "name": name,
                "family": family,
                "latest_print_revenue": rev,
                "trailing_yoy_pct": yoy,
                "origin": "observed",
                "quality": "primary",
                "note": "latest print mix; not automatically the 2y path",
            }
        )
    if lines and total:
        for row in lines:
            if row.get("latest_print_revenue"):
                row["share"] = round(float(row["latest_print_revenue"]) / total, 4)
        mode = "segment_mix"
        origin = "observed"
    else:
        mode = "top_down_range"
        origin = "estimated"
        families = ["growth_end_market", "software_recurring", "core_product"] if template_id == "semiconductor" else ["core_product"]
        if template_id == "energy":
            families = ["production_volume", "commodity_price"]
        for family in families:
            lines.append(
                {
                    "name": family,
                    "family": family,
                    "latest_print_revenue": None,
                    "share": None,
                    "trailing_yoy_pct": None,
                    "origin": "estimated",
                    "quality": "weak",
                    "note": "official mix not in pack; contribution is a labeled range, not a precise split",
                }
            )
    return {
        "mode": mode,
        "current_revenue": current,
        "lines": lines,
        "origin": origin,
        "forward": existing,
        "note": (
            "If the growth-end-market thesis holds, incremental revenue has to come from the labeled mix lines. "
            "Missing mix stays estimated rather than invented."
        ),
    }


def build_causal_chain(
    pack: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    template_id = str((pack or {}).get("template_id") or "generic_company")
    layers_spec = CHAIN_BY_TEMPLATE.get(template_id) or CHAIN_BY_TEMPLATE["generic_company"]
    rows = list(evidence or [])
    layers = []
    for name, tokens in layers_spec:
        hits = []
        for row in rows:
            hay = str(row.get("fact") or "").lower()
            if any(token in hay for token in tokens):
                hits.append(row)
        if hits:
            confidence = "medium" if len(hits) == 1 else "high"
            unresolved = []
            bottleneck = False
        else:
            confidence = "low"
            unresolved = [f"no source-backed facts on {name}"]
            bottleneck = True
        issuer_hits = [row for row in hits if evidence_side(row) == "issuer_management"]
        customer_hits = [row for row in hits if evidence_side(row) == "independent_customer"]
        issuer_only = hits and not customer_hits and all(evidence_side(row) == "issuer_management" for row in hits)
        if issuer_only and name in {"customer_demand", "customer_capex", "end_demand"}:
            unresolved.append("layer still lacks independent customer-side confirmation")
            confidence = "low" if confidence == "medium" else confidence
            bottleneck = True
        weakness = 0
        if bottleneck:
            weakness += 3
        weakness += {"low": 2, "medium": 1, "high": 0}.get(confidence, 2)
        if not customer_hits and name in {"customer_demand", "customer_capex", "end_demand", "site_power"}:
            weakness += 1
        if not hits:
            weakness += 2
        layers.append(
            {
                "layer": name,
                "evidence": _brief_evidence(hits, limit=4),
                "confidence": confidence,
                "bottleneck": bottleneck,
                "unresolved": unresolved,
                "independent_customer_hits": len(customer_hits),
                "issuer_hits": len(issuer_hits),
                "weakness": weakness,
            }
        )
    weakest = min(layers, key=lambda row: (-int(row.get("weakness") or 0), row["layer"]))["layer"]
    return {
        "template_id": template_id,
        "layers": layers,
        "weakest_link": weakest,
        "note": "each layer is only as strong as sourced evidence; issuer commentary is not independent confirmation",
    }


def build_assumption_tree(
    rulings: list[dict[str, Any]] | None,
    mapping: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_id = {str(row.get("assumption_id") or row.get("id")): row for row in (rulings or []) if row.get("assumption_id") or row.get("id")}
    driver_by_id = {str(row.get("assumption_id")): row for row in (mapping or []) if row.get("assumption_id")}
    branches = []
    used: set[str] = set()
    for code, title, kinds in TREE_BRANCHES:
        children = []
        for key, row in by_id.items():
            kind = str(row.get("kind") or assumption_kind(row))
            driver = str((driver_by_id.get(key) or {}).get("driver") or "")
            if kind not in kinds and driver not in kinds:
                continue
            used.add(key)
            children.append(_tree_node(row, driver_by_id.get(key)))
        branches.append({"id": code, "title": title, "nodes": children})
    leftover = [_tree_node(row, driver_by_id.get(str(row.get("assumption_id")))) for key, row in by_id.items() if key not in used]
    if leftover:
        branches.append({"id": "E", "title": "Other", "nodes": leftover})
    return {"core_thesis": "see PM golden answers", "branches": branches}


def _tree_node(row: dict[str, Any], mapped: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "assumption_id": row.get("assumption_id") or row.get("id"),
        "statement": row.get("statement"),
        "status": row.get("final_status") or row.get("status"),
        "confidence": row.get("final_confidence") or row.get("confidence"),
        "driver": (mapped or {}).get("driver"),
        "support": row.get("key_supporting_evidence_ids") or [],
        "oppose": row.get("key_opposing_evidence_ids") or [],
        "unresolved": row.get("unresolved_gaps") or [],
        "next_verification": row.get("next_verification"),
        "thesis_role": row.get("thesis_role"),
    }


def classify_market_reaction(
    pack: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
    *,
    quant_findings: list[str] | None = None,
    reaction_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = pack or {}
    reaction = reaction_window(payload)
    post = to_number(reaction.get("post_1d_return_pct") or reaction.get("day_return_pct"))
    fund = to_number((payload.get("company_profile") or {}).get("revenue_growth_yoy_pct"))
    applicable = post is not None and post < 0 and fund is not None and fund >= 2
    confirmed: list[str] = []
    plausible: list[str] = []
    unresolved: list[str] = []
    hay = " ".join(str(row.get("fact") or "") for row in (evidence or [])).lower()
    hay += " " + " ".join(quant_findings or []).lower()
    pe = to_number((payload.get("company_profile") or {}).get("pe_ttm"))
    if pe is not None and pe >= 30:
        confirmed.append(f"TTM PE {pe} is elevated versus a mid-cycle operating band, so a strong print can still be sold")
    if CONC_RE.search(hay) or "largest customer" in hay:
        confirmed.append("customer concentration is in source text and can cap duration trust")
    if "margin" in hay or "mix" in hay:
        plausible.append("margin/mix language is on the record and may have offset the top-line print")
    if "whisper" in hay or "below consensus" in hay or "expectations" in hay:
        plausible.append("there is language about the print versus expectations; it is not independently confirmed as a whisper number")
    else:
        unresolved.append("guidance versus whisper/expectations is not independently confirmed")
    if "positioning" not in hay and "crowded" not in hay:
        unresolved.append("positioning / crowded-trade commentary is not evidenced")
    vol = to_number(reaction.get("volume_vs_20d_avg"))
    if vol is not None and vol >= 1.5:
        confirmed.append(f"earnings-window volume vs 20d average is {vol}")
    if not applicable:
        return {
            "applicable": False,
            "confirmed": confirmed,
            "plausible_unconfirmed": plausible,
            "unresolved": unresolved,
            "summary": "this window is not a clean strong-print / down-tape case",
        }
    if not confirmed and not plausible:
        unresolved.append("no source-backed reason for the negative reaction was located")
    summary = (
        "Confirmed: " + ("; ".join(confirmed) if confirmed else "none")
        + ". Plausible but unconfirmed: " + ("; ".join(plausible) if plausible else "none")
        + ". Unresolved: " + ("; ".join(unresolved) if unresolved else "none")
        + "."
    )
    if reaction_summary and reaction_summary.get("summary"):
        summary = str(reaction_summary["summary"]) + " Classification: " + summary
    return {
        "applicable": True,
        "confirmed": confirmed,
        "plausible_unconfirmed": plausible,
        "unresolved": unresolved,
        "summary": summary,
    }


def market_implied_case(pack: dict[str, Any] | None, valuation: dict[str, Any] | None) -> dict[str, Any]:
    profile = (pack or {}).get("company_profile") or {}
    spot = to_number(profile.get("last_close") or (valuation or {}).get("spot_price"))
    ttm_eps = to_number(profile.get("eps_ttm"))
    pe_ttm = to_number(profile.get("pe_ttm"))
    pe_fwd = to_number(profile.get("pe_forward"))
    base = (valuation or {}).get("base_case") or {}
    bull = (valuation or {}).get("bull_case") or {}
    bear = (valuation or {}).get("bear_case") or {}
    years = int(((base.get("growth_assumptions") or {}).get("years") or 2))
    base_multiple = to_number(base.get("multiple"))
    base_eps = to_number(base.get("eps"))
    base_g = to_number((base.get("growth_assumptions") or {}).get("annual_rate"))
    bull_g = to_number((bull.get("growth_assumptions") or {}).get("annual_rate"))
    implied_ntm_eps = None
    implied_ntm_growth = None
    if pe_fwd not in (None, 0) and spot not in (None, 0):
        implied_ntm_eps = float(spot) / float(pe_fwd)
        if ttm_eps not in (None, 0):
            implied_ntm_growth = implied_ntm_eps / float(ttm_eps) - 1.0
    implied_eps_at_base_mult = None
    implied_2y_growth = None
    if spot not in (None, 0) and base_multiple not in (None, 0):
        implied_eps_at_base_mult = float(spot) / float(base_multiple)
        if ttm_eps not in (None, 0) and years:
            implied_2y_growth = (implied_eps_at_base_mult / float(ttm_eps)) ** (1.0 / years) - 1.0
    implied_multiple_on_base_eps = None
    if spot not in (None, 0) and base_eps not in (None, 0):
        implied_multiple_on_base_eps = float(spot) / float(base_eps)
    doubts = []
    if implied_2y_growth is not None and base_g is not None and implied_2y_growth > base_g + 0.05:
        doubts.append("duration/growth: the tape prices more growth than Base if we grant the researched multiple")
    if implied_2y_growth is not None and bull_g is not None and implied_2y_growth > bull_g + 0.03:
        doubts.append("the tape is above Bull growth at the researched multiple, so disagreement is not only multiple")
    if implied_multiple_on_base_eps is not None and base_multiple is not None and implied_multiple_on_base_eps > base_multiple + 4:
        doubts.append("multiple: the tape pays more than the researched Base multiple on Base EPS")
    if implied_multiple_on_base_eps is not None and to_number(bull.get("multiple")) and implied_multiple_on_base_eps > float(bull.get("multiple")) + 1:
        doubts.append("the tape's implied multiple on Base EPS sits at or above Bull")
    if not doubts:
        if implied_2y_growth is not None and base_g is not None and implied_2y_growth < base_g - 0.03:
            doubts.append("the tape prices less growth than Base, so the market may be discounting duration, execution, or mix")
        elif implied_multiple_on_base_eps is not None and base_multiple is not None and implied_multiple_on_base_eps < base_multiple - 3:
            doubts.append("the tape applies a lower multiple than Base on the same EPS path (concentration, duration, or de-rating)")
        else:
            doubts.append("spot and Base are close enough that the split between growth vs multiple doubt is not sharp")
    g_display = display_pct_range(
        to_number((bear.get("growth_assumptions") or {}).get("annual_rate")),
        bull_g,
        implied_2y_growth if implied_2y_growth is not None else base_g,
    )
    case = {
        "horizon": base.get("horizon"),
        "valuation_method": "market_implied",
        "target_value": round_target(spot) if spot is not None else None,
        "target_display": display_target(spot) if spot is not None else None,
        "eps": round(implied_eps_at_base_mult, 1) if implied_eps_at_base_mult else None,
        "multiple": round(implied_multiple_on_base_eps, 1) if implied_multiple_on_base_eps else pe_ttm,
        "growth_assumptions": {
            "annual_rate": coarsen_growth(implied_2y_growth),
            "origin": "market_implied",
            "display": display_pct(implied_2y_growth),
            "source": "spot divided by researched Base multiple, then CAGR versus TTM EPS",
        },
        "notes": "this column is the tape, not a researched case; it exists to show disagreement",
        "case_narrative": "market-implied path: what growth and/or multiple the current price requires",
    }
    return {
        "case": case,
        "implied_ntm_eps": round(implied_ntm_eps, 2) if implied_ntm_eps else None,
        "implied_ntm_growth": coarsen_growth(implied_ntm_growth),
        "implied_2y_eps_at_base_multiple": round(implied_eps_at_base_mult, 2) if implied_eps_at_base_mult else None,
        "implied_2y_growth_at_base_multiple": coarsen_growth(implied_2y_growth),
        "implied_multiple_on_base_eps": round(implied_multiple_on_base_eps, 1) if implied_multiple_on_base_eps else None,
        "current_pe": pe_ttm,
        "forward_pe": pe_fwd,
        "base_growth": base_g,
        "bull_growth": bull_g,
        "base_multiple": base_multiple,
        "display": g_display,
        "market_doubts": doubts,
        "summary": " ".join(doubts),
    }


def golden_answers(
    *,
    pack: dict[str, Any] | None,
    rulings: list[dict[str, Any]],
    valuation: dict[str, Any] | None,
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    name = str(((pack or {}).get("company_profile") or {}).get("legal_name") or (pack or {}).get("ticker") or "the issuer")
    template = str((pack or {}).get("template_id") or "generic_company")
    core = [row for row in rulings if row.get("thesis_role") == "core"]
    ranked = sorted(rulings, key=lambda row: float(row.get("final_confidence") or 0), reverse=True)
    strongest = next((row for row in ranked if row.get("final_status") == "strengthened"), ranked[0] if ranked else None)
    fragile = None
    for status in ("broken", "weakened"):
        for row in rulings:
            if row.get("final_status") == status:
                fragile = row
                break
        if fragile:
            break
    if fragile is None:
        for row in rulings:
            if row.get("kind") == "growth_persist" or row.get("thesis_role") == "monitoring":
                gaps = row.get("unresolved_gaps") or []
                if gaps or row.get("kind") == "growth_persist":
                    fragile = row
                    break
    if fragile is None:
        for row in rulings:
            gaps = row.get("unresolved_gaps") or []
            if any("customer" in str(item).lower() or "confirmation" in str(item).lower() for item in gaps):
                if row.get("final_status") != "strengthened":
                    fragile = row
                    break
    if fragile is None:
        non_strong = [row for row in rulings if row.get("final_status") != "strengthened"]
        pool = non_strong or rulings
        if pool:
            fragile = min(pool, key=lambda row: float(row.get("final_confidence") or 1))
    implied = artifacts.get("market_implied") or {}
    chain = artifacts.get("causal_chain") or {}
    reaction = artifacts.get("market_reaction") or {}
    delivery = artifacts.get("delivery_history") or {}
    top3 = []
    for row in core + ranked:
        if row in top3:
            continue
        top3.append(row)
        if len(top3) >= 3:
            break
    monitor = []
    for item in (
        "next official print versus stated outlook",
        "independent customer capex / deployment commentary",
        chain.get("weakest_link") and f"weakest chain layer: {chain.get('weakest_link')}",
        "net vs operating margin and mix",
        "customer concentration share of revenue",
        "FCF conversion",
    ):
        if item and item not in monitor:
            monitor.append(item)
    answers = {
        "core_thesis": (
            f"{name} under the {template} template: 1–3 year earnings power depends on whether sourced demand "
            f"and delivery claims persist after the current wave. "
            + ("Core claims: " + "; ".join(str(row.get("statement") or "")[:160] for row in core[:3]) if core else "No core claim is fully locked.")
        ),
        "top_assumptions": [
            {
                "assumption_id": row.get("assumption_id"),
                "statement": row.get("statement"),
                "status": row.get("final_status"),
                "role": row.get("thesis_role"),
            }
            for row in top3
        ],
        "strongest_assumption": {
            "assumption_id": (strongest or {}).get("assumption_id"),
            "statement": (strongest or {}).get("statement"),
            "status": (strongest or {}).get("final_status"),
            "why": (strongest or {}).get("reasoning"),
        }
        if strongest
        else None,
        "fragile_assumption": {
            "assumption_id": (fragile or {}).get("assumption_id"),
            "statement": (fragile or {}).get("statement"),
            "status": (fragile or {}).get("final_status"),
            "unresolved": (fragile or {}).get("unresolved_gaps"),
            "why": "weakest sourced node: gaps, opposition, or missing independent confirmation",
        }
        if fragile
        else None,
        "market_worry": implied.get("summary") or reaction.get("summary") or "market worry is not isolated beyond valuation context",
        "thesis_events": {
            "strengthen": "independent customer confirmation that capex and deployments convert on the stated horizon, plus delivery versus the commitment ledger",
            "weaken": f"slippage on the weakest chain layer ({chain.get('weakest_link')})" if chain.get("weakest_link") else "customer capex cuts or delayed conversion",
            "break": "cancellation or a guidance cut that breaks a core delivery claim, or a sustained miss versus the delivery history",
        },
        "monitor": monitor[:5],
        "delivery_context": delivery.get("summary"),
    }
    return answers


def synthesize_deep_case(
    pack: dict[str, Any] | None,
    *,
    evidence: list[dict[str, Any]] | None = None,
    rulings: list[dict[str, Any]] | None = None,
    valuation: dict[str, Any] | None = None,
    mapping: list[dict[str, Any]] | None = None,
    quant_findings: list[str] | None = None,
    reaction: dict[str, Any] | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    load_template((pack or {}).get("template_id"))
    symbol = str(ticker or (pack or {}).get("ticker") or "")
    tagged = []
    for row in evidence or []:
        item = dict(row)
        item["ticker"] = item.get("ticker") or symbol
        tagged.append(item)
    ledger = build_commitment_ledger(pack, tagged)
    delivery = build_delivery_history(pack)
    customers = customer_side_evidence(tagged)
    revenue_bridge = build_revenue_bridge(pack, valuation)
    chain = build_causal_chain(pack, tagged)
    tree = build_assumption_tree(rulings, mapping)
    classified = classify_market_reaction(pack, evidence, quant_findings=quant_findings, reaction_summary=reaction)
    implied = market_implied_case(pack, valuation)
    artifacts = {
        "commitment_ledger": ledger,
        "delivery_history": delivery,
        "customer_side_evidence": customers,
        "revenue_bridge": revenue_bridge,
        "causal_chain": chain,
        "assumption_tree": tree,
        "market_reaction": classified,
        "market_implied": implied,
    }
    artifacts["golden_answers"] = golden_answers(
        pack=pack,
        rulings=list(rulings or []),
        valuation=valuation,
        artifacts=artifacts,
    )
    artifacts["case_columns"] = {
        "bear": (valuation or {}).get("bear_case"),
        "market_implied": implied.get("case"),
        "base": (valuation or {}).get("base_case"),
        "bull": (valuation or {}).get("bull_case"),
    }
    artifacts["lineage"] = {
        "template_id": (pack or {}).get("template_id"),
        "evidence_count": len(evidence or []),
        "ruling_count": len(rulings or []),
        "weakest_link": chain.get("weakest_link"),
        "independent_customer": customers.get("independent_confirmation_present"),
        "delivery": lineage(
            delivery.get("beat_rate"),
            origin="historical_delivery",
            quality="secondary",
            note=delivery.get("summary") or "",
            display=delivery.get("summary"),
        ),
    }
    return artifacts


def search_queries_for(ticker: str, pack: dict[str, Any] | None, required: list[str] | None = None) -> list[str]:
    """Generic live-search queries from template axes and task data. No issuer-specific nouns."""
    symbol = str(ticker or "").upper()
    template = load_template((pack or {}).get("template_id"))
    template_id = str(template.get("id") or "generic_company")
    needed = {str(item) for item in (required or [])}
    queries: list[str] = []
    axes = [str(item.get("id") or "") for item in (template.get("question_axes") or [])]
    wants_customer = bool(
        {"customer_capex", "customer_confirmation", "end_demand"} & (set(axes) | needed)
    )
    if wants_customer:
        if template_id == "semiconductor":
            queries.append(f"{symbol} customer capital expenditure data center")
            queries.append(f"{symbol} customer capex AI infrastructure")
            queries.append(f"{symbol} customer deployment custom accelerator")
            queries.append("hyperscaler capital expenditure 10-Q AI data center")
            queries.append("data center power procurement interconnection")
        elif template_id == "energy":
            queries.append(f"{symbol} downstream demand project capex")
            queries.append(f"{symbol} production volume offtake")
        else:
            queries.append(f"{symbol} customer demand capital expenditure")
            queries.append(f"{symbol} customer deployment confirmation")
    if "power_capacity" in needed or (template_id == "semiconductor" and "customer_capex" in axes):
        queries.append(f"{symbol} data center power capacity procurement")
    if "supply_capacity" in axes or "supply_lock_in" in needed:
        if template_id == "semiconductor":
            queries.append(f"{symbol} foundry packaging supply capacity")
        elif template_id == "energy":
            queries.append(f"{symbol} project capacity startup")
        else:
            queries.append(f"{symbol} supply capacity production")
    if "management_delivery" in axes or "guidance_history" in needed:
        queries.append(f"{symbol} earnings guidance versus results")
    if not queries:
        queries.append(f"{symbol} earnings call transcript guidance")
    seen: set[str] = set()
    unique = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique.append(query)
    return unique[:8]
