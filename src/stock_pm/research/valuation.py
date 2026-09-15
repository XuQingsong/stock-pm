"""Thesis- and assumption-driven Bear / Base / Bull valuation.

Template bands are sanity ranges and fallbacks, never the investment growth
or multiple answer. Numbers stay coarse on purpose.
"""

from __future__ import annotations

import re
from typing import Any

from .extract import to_number
from .relevance import assumption_kind
from .templates import load_template
from .types import empty_valuation_case


DEFAULT_FRAMEWORKS = {
    "semiconductor": {
        "primary_methods": ["eps_pe", "fcf"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "cycle_multiple_low": 18,
        "cycle_multiple_mid": 26,
        "cycle_multiple_high": 40,
        "sanity_max_growth": 0.50,
        "warning_growth": 0.25,
        "fallback_growth": 0.08,
        "bear_margin_delta_pp": -3.0,
        "bull_margin_delta_pp": 1.0,
        "driver_families": [
            "growth_end_market",
            "core_product",
            "software_recurring",
            "contract_conversion",
            "margin_mix",
            "concentration",
        ],
        "multiple_reason": (
            "semiconductor earnings power is valued on forward EPS times a cycle PE; "
            "the current TTM PE is one anchor, not automatically the 2-year base multiple"
        ),
    },
    "energy": {
        "primary_methods": ["normalized_earnings_pe", "fcf"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "cycle_multiple_low": 8,
        "cycle_multiple_mid": 12,
        "cycle_multiple_high": 16,
        "sanity_max_growth": 0.15,
        "warning_growth": 0.08,
        "fallback_growth": 0.02,
        "bear_margin_delta_pp": -2.0,
        "bull_margin_delta_pp": 1.0,
        "driver_families": [
            "commodity_price",
            "production_volume",
            "capex",
            "fcf",
            "normalized_earnings",
        ],
        "multiple_reason": (
            "energy producers are valued on cycle-normalized earnings and FCF rather than peak growth multiples"
        ),
    },
    "generic_company": {
        "primary_methods": ["eps_pe"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "cycle_multiple_low": 12,
        "cycle_multiple_mid": 18,
        "cycle_multiple_high": 24,
        "sanity_max_growth": 0.30,
        "warning_growth": 0.12,
        "fallback_growth": 0.05,
        "bear_margin_delta_pp": -1.5,
        "bull_margin_delta_pp": 0.5,
        "driver_families": ["demand", "margin_mix", "cash_generation"],
        "multiple_reason": (
            "a generic operating company is valued on forward EPS times a moderate PE unless a tighter method is evidenced"
        ),
    },
}

GROWTH_ENDMARKET_RE = re.compile(
    r"\b(ai|accelerat|asic|custom silicon|datacenter|data[- ]center|optical|datacom|hyperscal|networking solutions)\b",
    re.I,
)
SOFTWARE_RE = re.compile(r"\b(software|subscription|infrastructure software)\b", re.I)
CONTRACT_RE = re.compile(
    r"multi-year|long[- ]term contract|recognized as revenue|lease agreement|backstop|compute capacity",
    re.I,
)
CONC_RE = re.compile(r"largest customer|customer concentration|\d[\d\.]*\s*(%|percent) of revenue", re.I)
MARGIN_RE = re.compile(r"gross margin|operating margin|margin mix|mix shift|margin press", re.I)
COMMODITY_RE = re.compile(r"\b(brent|wti|crude|realized (?:oil|gas) price|commodity|\$\s*\d+(?:\.\d+)?\s*/\s*(?:bbl|boe))\b", re.I)
VOLUME_RE = re.compile(r"\b(production|volume|barrel|boe|upstream)\b", re.I)
CAPEX_RE = re.compile(r"\b(capex|capital expend|capital spend)\b", re.I)
FCF_RE = re.compile(r"\b(free cash flow|\bfcf\b)\b", re.I)
CAGR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*cagr", re.I)
GUIDE_GROWTH_RE = re.compile(
    r"(?:revenue|sales|eps|earnings).{0,24}(?:grow|growth).{0,12}(\d+(?:\.\d+)?)\s*%"
    r"|(\d+(?:\.\d+)?)\s*%\s*(?:revenue\s+|sales\s+)?(?:yoy|year-over-year|organic growth)",
    re.I,
)
LONG_DATED_RE = re.compile(r"by\s+20[3-9]\d|over the next [5-9] years|to\s+2030", re.I)
CONTRACT_PCT_RE = re.compile(r"\d+(?:\.\d+)?\s*%\s+of this", re.I)


def round_target(value: float | None) -> int | None:
    """Avoid false precision such as 423.17."""
    if value is None:
        return None
    number = abs(float(value))
    if number >= 200:
        step = 10
    elif number >= 50:
        step = 5
    else:
        step = 1
    return int(round(float(value) / step) * step)


def display_target(value: float | int | None) -> str | None:
    rounded = round_target(to_number(value) if not isinstance(value, int) else float(value))
    if rounded is None:
        return None
    return f"~${rounded}"


def framework_for(template_id: str | None, template: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(DEFAULT_FRAMEWORKS.get(str(template_id or "generic_company"), DEFAULT_FRAMEWORKS["generic_company"]))
    overlay = (template or {}).get("valuation_framework") or {}
    if isinstance(overlay, dict):
        for key, value in overlay.items():
            if value is not None:
                raw[key] = value
    if "cycle_multiple_low" not in raw and overlay.get("multiple_bear") is not None:
        raw["cycle_multiple_low"] = overlay["multiple_bear"]
    if "cycle_multiple_mid" not in raw and overlay.get("multiple_base") is not None:
        raw["cycle_multiple_mid"] = overlay["multiple_base"]
    if "cycle_multiple_high" not in raw and overlay.get("multiple_bull") is not None:
        raw["cycle_multiple_high"] = overlay["multiple_bull"]
    if "warning_growth" not in raw and overlay.get("max_base_growth") is not None:
        raw["warning_growth"] = overlay["max_base_growth"]
    if "sanity_max_growth" not in raw and overlay.get("max_bull_growth") is not None:
        raw["sanity_max_growth"] = overlay["max_bull_growth"]
    return raw


def _metric(value: Any, origin: str, note: str = "") -> dict[str, Any]:
    return {"value": value, "origin": origin, "note": note}


def _hay(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _status_of(row: dict[str, Any]) -> str:
    return str(row.get("status") or row.get("final_status") or "unverified")


def _statement(row: dict[str, Any]) -> str:
    return str(row.get("statement") or row.get("claim") or "")


def _assumption_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("assumption_id") or "")


def _merge_assumptions(
    assumptions: list[dict[str, Any]] | None,
    rulings: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in assumptions or []:
        item = dict(row)
        key = _assumption_id(item)
        if key:
            by_id[key] = item
        else:
            by_id[f"anon-{len(by_id)}"] = item
    for row in rulings or []:
        key = _assumption_id(row)
        if not key:
            continue
        current = by_id.get(key) or dict(row)
        current["status"] = row.get("final_status") or current.get("status")
        current["thesis_role"] = row.get("thesis_role") or current.get("thesis_role")
        current["kind"] = row.get("kind") or current.get("kind")
        current["statement"] = current.get("statement") or row.get("statement")
        current["id"] = key
        by_id[key] = current
    return list(by_id.values())


def _kind(row: dict[str, Any]) -> str:
    if row.get("kind"):
        return str(row["kind"])
    return assumption_kind(row)


def _cagr(start: float | None, end: float | None, years: float) -> float | None:
    if start in (None, 0) or end in (None, 0) or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    return (float(end) / float(start)) ** (1.0 / years) - 1.0


def historical_cagr(earnings: list[dict[str, Any]], field: str) -> tuple[float | None, str]:
    series = [to_number(row.get(field)) for row in reversed(earnings or [])]
    series = [item for item in series if item not in (None, 0)]
    if len(series) < 2:
        return None, "not enough prints"
    years = max((len(series) - 1) / 4.0, 0.25)
    rate = _cagr(series[0], series[-1], years)
    return rate, f"{len(series)} prints spanning ~{round(years, 2)}y"


def _latest_margin(pack: dict[str, Any]) -> tuple[float | None, str, str]:
    profile = pack.get("company_profile") or {}
    for key, origin_note in (
        ("net_margin_pct", "profile net margin"),
        ("operating_margin_pct", "profile operating margin"),
        ("gross_margin_pct", "profile gross margin"),
    ):
        value = to_number(profile.get(key))
        if value is not None:
            return value, "observed", origin_note
    earnings = list(pack.get("earnings_history") or [])
    if earnings:
        latest = earnings[0]
        value = to_number(latest.get("margin_pct"))
        if value is not None:
            return value, "derived", "latest print net margin"
        revenue = to_number(latest.get("revenue"))
        net = to_number(latest.get("earnings") or latest.get("net_income"))
        if revenue not in (None, 0) and net is not None:
            return round(100.0 * float(net) / float(revenue), 2), "derived", "latest print earnings / revenue"
    return None, "missing", "no usable margin"


def _normalized_eps(pack: dict[str, Any]) -> tuple[float | None, str]:
    profile = pack.get("company_profile") or {}
    ttm = to_number(profile.get("eps_ttm"))
    prints = [to_number(row.get("eps")) for row in (pack.get("earnings_history") or [])]
    prints = [item for item in prints if item is not None]
    if len(prints) >= 4:
        annualized = 4.0 * (sum(prints[:4]) / 4.0)
        return round(annualized, 2), "derived from last four prints"
    if ttm is not None:
        return ttm, "observed TTM EPS"
    if prints:
        return round(4.0 * (sum(prints) / len(prints)), 2), "derived from available prints"
    return None, "missing"


def _classify_segment(name: str, template_id: str) -> str:
    text = str(name or "")
    if template_id == "energy":
        if VOLUME_RE.search(text):
            return "production_volume"
        if COMMODITY_RE.search(text):
            return "commodity_price"
        return "core_product"
    if GROWTH_ENDMARKET_RE.search(text):
        return "growth_end_market"
    if SOFTWARE_RE.search(text):
        return "software_recurring"
    return "core_product"


def map_assumption_to_driver(row: dict[str, Any], template_id: str) -> dict[str, Any]:
    statement = _statement(row)
    kind = _kind(row)
    template_id = str(template_id or "generic_company")
    driver = "demand"
    effect = "revenue growth durability"
    if template_id == "energy":
        if COMMODITY_RE.search(statement) or kind in {"demand_visibility"}:
            driver, effect = "commodity_price", "realized price / earnings normalization"
        elif VOLUME_RE.search(statement) or kind == "guidance":
            driver, effect = "production_volume", "volume / production path"
        elif CAPEX_RE.search(statement):
            driver, effect = "capex", "reinvestment and FCF conversion"
        elif FCF_RE.search(statement) or kind == "growth_persist":
            driver, effect = "normalized_earnings", "cycle-normalized earnings / FCF"
        else:
            driver, effect = "normalized_earnings", "cycle-normalized earnings path"
    else:
        if kind == "margin" or MARGIN_RE.search(statement):
            driver, effect = "margin_mix", "operating / net margin"
        elif CONC_RE.search(statement) or "concentration" in statement.lower():
            driver, effect = "concentration", "multiple discount for customer concentration"
        elif kind in {"execution", "supply"} or CONTRACT_RE.search(statement):
            driver, effect = "contract_conversion", "revenue timing and demand durability"
        elif GROWTH_ENDMARKET_RE.search(statement):
            driver, effect = "growth_end_market", "AI / growth-end-market revenue growth"
        elif SOFTWARE_RE.search(statement):
            driver, effect = "software_recurring", "recurring software revenue quality"
        elif kind == "guidance":
            driver, effect = "near_term_revenue", "near-term revenue vs stated outlook"
        elif kind == "growth_persist":
            driver, effect = "revenue_growth_durability", "whether trailing growth can persist"
        else:
            driver, effect = "demand", "top-line demand"
    impact = {
        "bear": "slows, slips, or compresses",
        "base": "mostly delivered / converts on a normal path",
        "bull": "persists or expands",
    }
    status = _status_of(row)
    if status in {"weakened", "broken"}:
        impact["base"] = "underwrites slippage or compression already"
        impact["bull"] = "only recovers if later evidence repairs the claim"
    elif status == "strengthened":
        impact["base"] = "converts on the evidenced path"
        impact["bull"] = "deployments expand beyond the current wave"
    return {
        "assumption_id": _assumption_id(row),
        "statement": statement[:240],
        "status": status,
        "kind": kind,
        "driver": driver,
        "valuation_effect": effect,
        "case_impact": impact,
        "thesis_role": row.get("thesis_role"),
    }


def _guidance_growth(pack: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[float | None, str]:
    blobs = [str(row.get("text") or "") for row in (pack.get("guidance_history") or [])]
    blobs.extend(str(row.get("fact") or "") for row in evidence)
    text = " ".join(blobs)
    # Contract recognition language is not company growth.
    text = CONTRACT_PCT_RE.sub(" ", text)
    match = CAGR_RE.search(text)
    if match:
        span = text[max(0, match.start() - 80) : match.end() + 80]
        if not LONG_DATED_RE.search(span):
            return float(match.group(1)) / 100.0, "stated near-term CAGR in source text"
    hit = GUIDE_GROWTH_RE.search(text)
    if hit:
        raw = next((g for g in hit.groups() if g), None)
        if raw:
            value = float(raw) / 100.0
            if 0 <= value <= 0.8:
                return value, "explicit revenue/EPS growth language in guidance"
    return None, "no quantitative near-term growth guidance"


def _driver_status(mapping: list[dict[str, Any]], driver: str) -> str:
    rows = [row for row in mapping if row.get("driver") == driver]
    if any(row.get("status") == "broken" for row in rows):
        return "broken"
    if any(row.get("status") == "weakened" for row in rows):
        return "weakened"
    if any(row.get("status") == "strengthened" for row in rows):
        return "strengthened"
    if rows:
        return "unchanged"
    return "absent"


def _any_status(mapping: list[dict[str, Any]], statuses: set[str]) -> bool:
    return any(row.get("status") in statuses for row in mapping)


def _fade_trailing(observed: float | None, persist_status: str) -> tuple[float | None, str]:
    if observed is None:
        return None, "no trailing growth to fade"
    if persist_status == "strengthened":
        return round(observed * 0.70, 4), "persist strengthened: keep 70% of trailing growth, not the raw print year"
    if persist_status == "unchanged":
        return round(observed * 0.40, 4), "persist unproven: keep 40% of trailing growth rather than the print year"
    if persist_status in {"weakened", "broken"}:
        return round(min(0.0, observed * 0.10), 4), "persist weakened/broken: do not underwrite trailing growth"
    return round(observed * 0.35, 4), "persist unverified: keep 35% of trailing growth"


def _build_bridge(
    pack: dict[str, Any],
    *,
    assumptions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    framework: dict[str, Any],
) -> dict[str, Any]:
    profile = pack.get("company_profile") or {}
    template_id = str(pack.get("template_id") or "generic_company")
    revenue = to_number(profile.get("revenue_ttm"))
    eps_ttm = to_number(profile.get("eps_ttm"))
    fcf = to_number(profile.get("fcf"))
    last_close = to_number(profile.get("last_close"))
    pe = to_number(profile.get("pe_ttm"))
    margin, margin_origin, margin_note = _latest_margin(pack)
    shares = None
    shares_origin = "missing"
    if revenue not in (None, 0) and margin not in (None, 0) and eps_ttm not in (None, 0):
        shares = (float(revenue) * float(margin) / 100.0) / float(eps_ttm)
        shares_origin = "derived"
    hist_rev, hist_note = historical_cagr(list(pack.get("earnings_history") or []), "revenue")
    hist_eps, hist_eps_note = historical_cagr(list(pack.get("earnings_history") or []), "eps")
    yoy = to_number(profile.get("revenue_growth_yoy_pct"))
    yoy_rate = (yoy / 100.0) if yoy is not None else None
    guide_g, guide_note = _guidance_growth(pack, evidence)
    norm_eps, norm_note = _normalized_eps(pack)
    segments = []
    latest = (pack.get("earnings_history") or [{}])[0] or {}
    for item in latest.get("segments") or []:
        family = _classify_segment(str(item.get("name") or ""), template_id)
        segments.append(
            {
                "name": item.get("name"),
                "family": family,
                "revenue": to_number(item.get("revenue")),
                "growth_yoy_pct": to_number(item.get("growth_yoy_pct")),
                "origin": "observed",
            }
        )
    missing = list(pack.get("missing_fields") or [])
    if not segments and "segment_growth" not in missing and template_id != "energy":
        missing.append("segment_growth")
    if margin is None and "forward_margin" not in missing:
        missing.append("forward_margin")
    if fcf is None and "fcf" not in missing:
        missing.append("fcf")
    if template_id == "energy" and not any(COMMODITY_RE.search(str(row.get("fact") or "")) for row in evidence):
        if "commodity_price" not in missing:
            missing.append("commodity_price")
    baseline = {
        "revenue_ttm": _metric(revenue, "observed" if revenue is not None else "missing"),
        "eps_ttm": _metric(eps_ttm, "observed" if eps_ttm is not None else "missing"),
        "normalized_eps": _metric(norm_eps, "derived" if norm_eps is not None else "missing", norm_note),
        "margin_pct": _metric(margin, margin_origin, margin_note),
        "fcf": _metric(fcf, "observed" if fcf is not None else "missing"),
        "last_close": _metric(last_close, "observed" if last_close is not None else "missing"),
        "pe_ttm": _metric(pe, "observed" if pe is not None else "missing"),
        "implied_shares": _metric(round(shares, 0) if shares else None, shares_origin, "revenue × margin / EPS"),
        "trailing_revenue_yoy": _metric(yoy_rate, "observed" if yoy_rate is not None else "missing", "print-year, not a 2y assumption"),
        "historical_revenue_cagr": _metric(round(hist_rev, 4) if hist_rev is not None else None, "derived", hist_note),
        "historical_eps_cagr": _metric(round(hist_eps, 4) if hist_eps is not None else None, "derived", hist_eps_note),
        "guidance_growth": _metric(guide_g, "observed" if guide_g is not None else "missing", guide_note),
    }
    return {
        "template_id": template_id,
        "baseline": baseline,
        "segments": segments,
        "mapping": mapping,
        "missing": list(dict.fromkeys(missing)),
        "framework_sanity": {
            "warning_growth": framework.get("warning_growth"),
            "sanity_max_growth": framework.get("sanity_max_growth"),
            "cycle_multiple": [
                framework.get("cycle_multiple_low"),
                framework.get("cycle_multiple_mid"),
                framework.get("cycle_multiple_high"),
            ],
            "note": "template numbers are sanity / fallback ranges, not the investment assumption",
        },
    }


def _growth_plan(
    bridge: dict[str, Any],
    mapping: list[dict[str, Any]],
    framework: dict[str, Any],
    *,
    confidence: float,
) -> dict[str, Any]:
    template_id = bridge["template_id"]
    base_line = bridge["baseline"]
    yoy = to_number((base_line["trailing_revenue_yoy"] or {}).get("value"))
    hist = to_number((base_line["historical_revenue_cagr"] or {}).get("value"))
    guide = to_number((base_line["guidance_growth"] or {}).get("value"))
    persist = _driver_status(mapping, "revenue_growth_durability")
    if persist == "absent":
        persist = _driver_status(mapping, "demand")
    contract = _driver_status(mapping, "contract_conversion")
    end_market = _driver_status(mapping, "growth_end_market")
    volume = _driver_status(mapping, "production_volume")
    commodity = _driver_status(mapping, "commodity_price")
    weakened = _any_status(mapping, {"weakened", "broken"})
    used_fallback = False
    warnings: list[str] = []
    sources: list[str] = []

    faded, fade_note = _fade_trailing(yoy if yoy is not None else hist, persist)
    if guide is not None:
        base = guide
        origin = "observed"
        sources.append(fade_note)
        sources.append("quantitative guidance is the primary base growth input")
    elif faded is not None and (yoy is not None or hist is not None):
        base = faded
        origin = "derived"
        sources.append(fade_note)
        if hist is not None and persist != "strengthened":
            base = min(base, hist) if hist < 1 else base
            sources.append("historical delivery caps unproven persist")
    elif contract == "strengthened" or end_market == "strengthened":
        base = 0.10
        origin = "assumption"
        sources.append("no usable 2y growth series; strengthened delivery/contract claims underwrite a modest conversion overlay")
    else:
        base = float(framework.get("fallback_growth") or 0.05)
        origin = "template_fallback"
        used_fallback = True
        sources.append("no evidence-backed 2y growth rate; template fallback is labeled and is not an investment view")

    warning_g = float(framework.get("warning_growth") or 0.12)
    sanity = float(framework.get("sanity_max_growth") or 0.5)
    if template_id == "energy":
        # Energy is not an EPS-CAGR story. A long-dated CAGR is not a 2y growth-stock input.
        if volume == "strengthened":
            base = 0.04
            origin = "assumption"
            used_fallback = False
            sources = ["production delivery is strengthened; commodity held flat unless independently evidenced"]
        elif commodity == "weakened" or volume == "weakened":
            base = -0.04
            origin = "assumption"
            used_fallback = False
            sources = ["commodity or volume claims are weakened; earnings path is below the trailing print"]
        else:
            base = 0.02
            origin = "assumption"
            used_fallback = False
            sources = [
                "energy 2y path holds production near the stated plan; a long-dated earnings CAGR is not converted into a 2y EPS growth assumption"
            ]
        if guide is not None and guide <= 0.06:
            base = guide
            origin = "observed"
            sources.append("near-term quantitative volume/earnings guidance is small enough to use as a 2y path")
        warnings.append("template energy warning/fallback growth is a sanity check only and is not the 2y assumption")
    else:
        if yoy is not None and yoy > warning_g:
            warnings.append(
                f"trailing YoY {round(yoy*100, 1)}% exceeds the template warning threshold {round(warning_g*100, 1)}% and is not used as the 2y assumption"
            )
        if base > sanity:
            warnings.append(
                f"derived base growth {round(base*100, 1)}% exceeds sanity max {round(sanity*100, 1)}%; clipped for numerical safety only"
            )
            base = sanity
        if yoy is not None and abs(base - warning_g) < 0.002 and origin != "observed":
            warnings.append("base growth coincidentally near the warning threshold; it is not copied from the template cap")

    if weakened and template_id != "energy":
        base = min(base, 0.03 if contract != "strengthened" else max(base * 0.5, 0.04))
        sources.append("weakened delivery claims pull base growth down")
        if origin == "observed":
            origin = "assumption"

    if base > sanity:
        warnings.append(f"derived base growth {round(base*100, 1)}% exceeds sanity max {round(sanity*100, 1)}%; clipped for numerical safety only")
        base = sanity

    width = 1.0 + max(0.0, 0.58 - confidence) * 1.4
    bear = base - (0.12 if template_id != "energy" else 0.06) * width
    bull = base + (0.10 if template_id != "energy" else 0.04) * width
    if contract == "strengthened" or end_market == "strengthened":
        bull += 0.04
        sources.append("strengthened contract/end-demand claims widen bull via conversion/deployment")
    if persist == "strengthened":
        bull = max(bull, (yoy or base) * 0.8)
        sources.append("persist strengthened: bull can approach a faded trailing rate")
    if persist in {"weakened", "broken"} or weakened:
        bear = min(bear, -0.05)
        bull = min(bull, max(base, 0.06))
        sources.append("weakened claims cap bull and pull bear below zero growth")
    if template_id == "energy":
        if commodity == "absent":
            sources.append("commodity price is not evidenced; cases hold realized price flat and stay provisional")
        bear = min(bear, -0.08)
        bull = min(bull, max(base + 0.06, 0.08))

    return {
        "bear": round(bear, 4),
        "base": round(base, 4),
        "bull": round(bull, 4),
        "origin": origin,
        "used_template_fallback": used_fallback,
        "sources": sources,
        "warnings": warnings,
        "width_factor": round(width, 3),
    }


def _margin_plan(
    bridge: dict[str, Any],
    mapping: list[dict[str, Any]],
    framework: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    margin = to_number((bridge["baseline"]["margin_pct"] or {}).get("value"))
    origin = str((bridge["baseline"]["margin_pct"] or {}).get("origin") or "missing")
    mix = _driver_status(mapping, "margin_mix")
    hay = _hay(*(row.get("fact") for row in evidence))
    mix_language = bool(MARGIN_RE.search(hay))
    bear_delta = float(framework.get("bear_margin_delta_pp") or -2.0)
    bull_delta = float(framework.get("bull_margin_delta_pp") or 0.5)
    reasons = []
    if margin is None:
        return {
            "bear": None,
            "base": None,
            "bull": None,
            "origin": "missing",
            "reasons": ["no observed or derived margin; EPS path cannot use a margin bridge"],
        }
    base = margin
    if mix == "weakened" or mix_language:
        base = margin - 1.0
        reasons.append("mix/margin language or a weakened margin claim trims the base path by ~1pp")
    else:
        reasons.append("base holds the observed/derived margin unless mix evidence says otherwise")
    if mix == "strengthened":
        bull_delta = max(bull_delta, 1.5)
        reasons.append("strengthened margin claim allows a modest bull expansion")
    bear = base + bear_delta
    bull = base + bull_delta
    if mix == "weakened":
        bear = min(bear, base - 3.0)
        bull = min(bull, base)
        reasons.append("weakened margin/mix caps bull at the trimmed base")
    return {
        "bear": round(bear, 2),
        "base": round(base, 2),
        "bull": round(bull, 2),
        "origin": origin if origin != "missing" else "assumption",
        "reasons": reasons,
    }


def _starting_anchor(
    *,
    current_pe: float | None,
    persist: str,
    template_id: str,
    framework: dict[str, Any],
    confidence: float,
) -> tuple[float, str, str]:
    low = float(framework.get("cycle_multiple_low") or 12)
    mid = float(framework.get("cycle_multiple_mid") or 18)
    high = float(framework.get("cycle_multiple_high") or 24)
    if current_pe and persist == "strengthened" and current_pe > 0:
        start = 0.5 * current_pe + 0.5 * mid
        return round(start, 1), "observed", "blend of current PE and cycle mid because persist is strengthened"
    if current_pe and current_pe > 0:
        # Unproven persist: do not let the tape set the base multiple.
        start = 0.35 * current_pe + 0.65 * mid
        if template_id == "energy":
            start = mid
            return round(start, 1), "derived", "energy starts at cycle-normalized mid, not the current print PE"
        if current_pe > high and confidence < 0.55:
            return round(start, 1), "derived", "current PE is above cycle high; base starts between cycle mid and spot PE because persist is unproven"
        return round(start, 1), "derived", "current PE is an anchor; persist is not proven so base does not equal spot PE"
    return round(mid, 1), "template_fallback", "no current PE; cycle mid is a fallback sanity anchor, not a researched multiple"


def _multiple_plan(
    pack: dict[str, Any],
    bridge: dict[str, Any],
    mapping: list[dict[str, Any]],
    framework: dict[str, Any],
    growth: dict[str, Any],
    *,
    confidence: float,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = pack.get("company_profile") or {}
    current_pe = to_number(profile.get("pe_ttm"))
    template_id = str(pack.get("template_id") or "generic_company")
    persist = _driver_status(mapping, "revenue_growth_durability")
    contract = _driver_status(mapping, "contract_conversion")
    software = _driver_status(mapping, "software_recurring")
    conc = _driver_status(mapping, "concentration")
    weakened = _any_status(mapping, {"weakened", "broken"})
    margin = to_number((bridge["baseline"]["margin_pct"] or {}).get("value"))
    start, start_origin, start_note = _starting_anchor(
        current_pe=current_pe,
        persist=persist,
        template_id=template_id,
        framework=framework,
        confidence=confidence,
    )
    growth_premium = 0.0
    if growth["base"] >= 0.12:
        growth_premium += 4.0
    elif growth["base"] >= 0.06:
        growth_premium += 2.0
    elif growth["base"] <= 0:
        growth_premium -= 3.0
    if persist != "strengthened" and growth_premium > 0:
        growth_premium = min(growth_premium, 1.0)
    margin_premium = 0.0
    if margin is not None and margin >= 25:
        margin_premium += 4.0
    elif margin is not None and margin >= 15:
        margin_premium += 2.0
    elif margin is not None and margin < 8:
        margin_premium -= 2.0
    recurring_premium = 0.0
    if contract == "strengthened" or software == "strengthened":
        recurring_premium += 3.0
    conc_discount = 0.0
    hay = _hay(
        *(str(row.get("statement")) for row in mapping),
        *(str(row.get("fact")) for row in (evidence or [])),
    )
    if conc == "strengthened" or CONC_RE.search(hay):
        conc_discount -= 4.0
    execution_discount = 0.0
    if weakened:
        execution_discount -= 5.0
    elif persist == "unchanged":
        execution_discount -= 2.0
    if template_id == "energy":
        growth_premium = min(growth_premium, 1.0)
        recurring_premium = 0.0
        if persist != "strengthened":
            execution_discount = min(execution_discount, -1.0)

    width = 1.0 + max(0.0, 0.58 - confidence) * 1.2
    base = start + growth_premium + margin_premium + recurring_premium + conc_discount + execution_discount
    low = float(framework.get("cycle_multiple_low") or 8)
    high = float(framework.get("cycle_multiple_high") or 40)
    # Sanity, not the answer: only clamp extremes.
    hard_low = max(6.0, low - 4) if template_id == "energy" else max(4.0, low - 6)
    hard_high = high + 12
    base = max(hard_low, min(hard_high, base))
    bear = max(hard_low, base - (4.0 if template_id == "energy" else 6.0) * width)
    bull = min(hard_high, base + 5.0 * width)
    if current_pe and confidence < 0.5:
        bull = max(bull, min(current_pe, bull + 8))
    if current_pe and persist == "strengthened":
        bull = max(bull, min(current_pe, high))
    floor_ref = int(low) if template_id == "energy" else 20
    why_not_low = (
        f"not {floor_ref}x because "
        + (
            "margin/quality and evidenced delivery support a premium to a low-20s cycle floor"
            if template_id != "energy" and ((margin or 0) >= 15 or contract == "strengthened")
            else "cycle-normalized cash earnings still support more than a distressed trough multiple"
            if template_id == "energy"
            else "even a conservative path still sits above distressed-cycle multiples unless earnings collapse"
        )
    )
    why_not_high = (
        f"not {int(round(current_pe or high))}x because "
        + (
            "trailing growth is unproven as a 2y persist, so the current/high-cycle PE is not the base multiple"
            if persist != "strengthened"
            else "concentration/execution still cap how far the multiple can sit at the cycle ceiling"
        )
    )
    if template_id == "energy":
        why_not_high = "not a growth-stock multiple because energy is anchored on normalized earnings/FCF through the cycle"
    anchors = []
    if current_pe:
        anchors.append({"name": "current_valuation", "value": current_pe, "origin": "observed"})
    anchors.append({"name": "cycle_position", "value": float(framework.get("cycle_multiple_mid") or 18), "origin": "template_fallback", "note": "sanity band, not the answer"})
    if margin is not None:
        anchors.append({"name": "growth_margin_profile", "value": margin, "origin": "observed" if bridge["baseline"]["margin_pct"]["origin"] == "observed" else "derived"})
    if contract != "absent" or conc != "absent" or weakened:
        anchors.append({"name": "business_quality_or_risk", "value": None, "origin": "assumption"})
    researched_anchors = [row for row in anchors if row["origin"] != "template_fallback"]
    decomposition = {
        "starting_anchor": {"value": start, "origin": start_origin, "note": start_note},
        "growth_premium": growth_premium,
        "margin_quality_premium": margin_premium,
        "recurring_revenue_premium": recurring_premium,
        "customer_concentration_discount": conc_discount,
        "cycle_execution_discount": execution_discount,
        "result_base": round(base, 1),
        "why_not_cycle_floor": why_not_low,
        "why_not_cycle_ceiling": why_not_high,
        "anchors": anchors,
        "anchor_count_non_template": len(researched_anchors),
    }
    return {
        "bear": round(bear, 1),
        "base": round(base, 1),
        "bull": round(bull, 1),
        "decomposition": decomposition,
        "current_pe": current_pe,
        "used_template_anchor": start_origin == "template_fallback",
        "insufficient_anchors": len(researched_anchors) < 2,
    }


def _upside(target: int | None, spot: float | None) -> dict[str, Any] | None:
    if target is None or spot in (None, 0):
        return None
    pct = round(100.0 * (float(target) / float(spot) - 1.0), 0)
    return {"spot": round(float(spot), 2), "target": target, "pct": int(pct)}


def _sensitivity(eps: float, multiple: float) -> list[dict[str, Any]]:
    base = eps * multiple
    return [
        {"shock": "EPS 10% below base", "target": round_target(base * 0.9), "target_display": display_target(base * 0.9)},
        {"shock": "EPS 10% above base", "target": round_target(base * 1.1), "target_display": display_target(base * 1.1)},
        {
            "shock": f"multiple {round(multiple)}x → {round(multiple - 5)}x",
            "target": round_target(eps * max(multiple - 5, 1)),
            "target_display": display_target(eps * max(multiple - 5, 1)),
        },
        {
            "shock": f"multiple {round(multiple)}x → {round(multiple + 5)}x",
            "target": round_target(eps * (multiple + 5)),
            "target_display": display_target(eps * (multiple + 5)),
        },
    ]


def _fwd_fcf(fcf: float | None, growth: float, years: int, *, haircut: float = 0.0) -> float | None:
    if fcf in (None, 0):
        return None
    return float(fcf) * ((1.0 + growth) ** years) * (1.0 - haircut)


def _market_vs_model(
    *,
    spot: float | None,
    cases: dict[str, dict[str, Any]],
    multiples: dict[str, Any],
    growth: dict[str, Any],
    missing: list[str],
    status: str,
) -> dict[str, Any]:
    bull = cases.get("bull_case") or {}
    base = cases.get("base_case") or {}
    bull_t = to_number(bull.get("target_value"))
    base_t = to_number(base.get("target_value"))
    if spot in (None, 0) or bull_t is None:
        return {"applicable": False, "summary": "spot vs model is not comparable without a target and a last close"}
    above_bull = spot > bull_t
    above_base = base_t is not None and spot > base_t
    explanations = []
    current_pe = to_number(multiples.get("current_pe"))
    bull_m = to_number(bull.get("multiple"))
    if current_pe and bull_m and current_pe > bull_m:
        explanations.append(
            f"current TTM PE {current_pe} is above the bull model multiple {bull_m}x, so the tape is paying more than the researched bull case"
        )
    if growth.get("used_template_fallback") or growth.get("origin") == "template_fallback":
        explanations.append("forward earnings may be too conservative because growth used a labeled template fallback rather than a full driver stack")
    if growth.get("base", 1) <= 0.02:
        explanations.append("base/bull EPS paths underwrite little or no growth, which can sit below a market price that still prices expansion")
    if "segment_growth" in missing or "fcf" in missing or "commodity_price" in missing:
        explanations.append(
            "missing "
            + ", ".join(item for item in ("segment_growth", "fcf", "commodity_price", "forward_margin") if item in missing)
            + " so the gap versus the tape is at least partly a data/model limitation"
        )
    if not explanations and above_bull:
        explanations.append("every researched case is below the tape, but the system does not invent a non-evidenced reason")
    if above_bull:
        summary = (
            "Market price is above the bull case. "
            + " ".join(explanations)
            + f" valuation_status={status}, so this is not a high-confidence call that the market is simply wrong."
        )
    elif above_base:
        summary = "Market price is above base and inside or below bull. The tape is more optimistic than the underwritten base path."
    else:
        summary = "Market price is at or below the base case. That does not by itself make the name cheap."
    return {
        "applicable": True,
        "spot_above_bull": above_bull,
        "spot_above_base": above_base,
        "spot": round(float(spot), 2),
        "base_target": base_t,
        "bull_target": bull_t,
        "explanations": explanations,
        "summary": summary,
    }


def attribute_target_change(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    prev = (previous or {}).get("base_case") or {}
    curr = (current or {}).get("base_case") or {}
    e0 = to_number(prev.get("eps"))
    e1 = to_number(curr.get("eps"))
    m0 = to_number(prev.get("multiple"))
    m1 = to_number(curr.get("multiple"))
    r0 = to_number(prev.get("revenue"))
    r1 = to_number(curr.get("revenue"))
    mar0 = to_number((prev.get("margin_assumptions") or {}).get("net_margin_pct"))
    mar1 = to_number((curr.get("margin_assumptions") or {}).get("net_margin_pct"))
    t0 = round_target((e0 or 0) * (m0 or 0)) if e0 and m0 else round_target(to_number(prev.get("target_value")))
    t1 = round_target((e1 or 0) * (m1 or 0)) if e1 and m1 else round_target(to_number(curr.get("target_value")))
    parts = []
    if e0 and m0 and e1 and m1:
        after_eps = e1 * m0
        after_mult = e1 * m1
        eps_delta = after_eps - (e0 * m0)
        mult_delta = after_mult - after_eps
        parts.append({"from": "EPS", "delta": round_target(eps_delta), "display": display_target(eps_delta)})
        if mar0 is not None and mar1 is not None and r0 and r1 and mar0:
            # Split EPS into revenue vs margin when both exist.
            rev_share = 0.0
            if r0:
                rev_share = (r1 - r0) / r0
            mar_share = (mar1 - mar0) / 100.0
            denom = abs(rev_share) + abs(mar_share) or 1.0
            parts.insert(
                0,
                {
                    "from": "revenue",
                    "delta": round_target(eps_delta * (abs(rev_share) / denom) * (1 if rev_share >= 0 else -1)),
                    "display": display_target(eps_delta * (abs(rev_share) / denom) * (1 if rev_share >= 0 else -1)),
                },
            )
            parts.insert(
                1,
                {
                    "from": "margin",
                    "delta": round_target(eps_delta * (abs(mar_share) / denom) * (1 if mar_share >= 0 else -1)),
                    "display": display_target(eps_delta * (abs(mar_share) / denom) * (1 if mar_share >= 0 else -1)),
                },
            )
            parts = [row for row in parts if row["from"] != "EPS"] + [
                {"from": "EPS remainder", "delta": round_target(eps_delta), "display": display_target(eps_delta), "note": "sum of revenue/margin effects before multiple"}
            ]
        parts.append({"from": "multiple", "delta": round_target(mult_delta), "display": display_target(mult_delta)})
    return {
        "base_target": {"from": display_target(t0), "to": display_target(t1)},
        "parts": parts,
        "note": "coarse attribution; rounded on purpose",
    }


def _confidence(
    *,
    mapping: list[dict[str, Any]],
    growth: dict[str, Any],
    multiples: dict[str, Any],
    missing: list[str],
    has_baseline: bool,
) -> tuple[float, str]:
    score = 0.52
    if has_baseline:
        score += 0.08
    if growth.get("origin") in {"observed", "derived", "assumption"} and not growth.get("used_template_fallback"):
        score += 0.08
    else:
        score -= 0.12
    if multiples.get("insufficient_anchors") or multiples.get("used_template_anchor"):
        score -= 0.10
    if _any_status(mapping, {"strengthened"}):
        score += 0.06
    if _any_status(mapping, {"weakened", "broken"}):
        score -= 0.06
    gaps = [item for item in missing if item in {"segment_growth", "fcf", "forward_margin", "commodity_price"}]
    score -= 0.04 * min(len(gaps), 3)
    score = round(min(0.78, max(0.22, score)), 3)
    if score < 0.45:
        width_reason = "low valuation confidence widens Bear/Bull growth and multiple spreads; it does not add decimal precision"
    elif score > 0.62:
        width_reason = "higher valuation confidence keeps the range narrower than a data-poor case, still using coarse targets"
    else:
        width_reason = "mid confidence keeps a full Bear/Base/Bull business spread without fake precision"
    if growth.get("used_template_fallback"):
        width_reason = "template growth fallback plus " + width_reason
    return score, width_reason


def _status_for(
    *,
    has_target: bool,
    growth: dict[str, Any],
    multiples: dict[str, Any],
    missing: list[str],
    margin_ok: bool,
    guidance_ok: bool,
    template_id: str,
) -> str:
    if not has_target:
        return "insufficient"
    material_gaps = [item for item in missing if item in {"segment_growth", "fcf", "forward_margin", "commodity_price"}]
    fallbackish = bool(growth.get("used_template_fallback") or multiples.get("used_template_anchor") or multiples.get("insufficient_anchors"))
    if not margin_ok or not guidance_ok or fallbackish:
        return "provisional"
    if template_id == "energy" and "commodity_price" in missing:
        return "provisional"
    if template_id == "semiconductor" and "segment_growth" in missing:
        return "provisional"
    if len(material_gaps) >= 2:
        return "provisional"
    return "usable"


def build_valuation_cases(
    pack: dict[str, Any],
    *,
    assumptions: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    key_assumption_ids: list[str] | None = None,
    rulings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    template = load_template(pack.get("template_id"))
    framework = framework_for(pack.get("template_id"), template)
    template_id = str(pack.get("template_id") or "generic_company")
    merged = _merge_assumptions(assumptions, rulings)
    evidence_rows = list(evidence or [])
    mapping = [map_assumption_to_driver(row, template_id) for row in merged]
    bridge = _build_bridge(pack, assumptions=merged, evidence=evidence_rows, mapping=mapping, framework=framework)
    profile = pack.get("company_profile") or {}
    last_close = to_number(profile.get("last_close"))
    years = int(framework.get("horizon_years") or 2)
    methods = list(framework.get("primary_methods") or ["eps_pe"])
    has_guidance = bool(pack.get("guidance_history"))
    margin_ok = to_number((bridge["baseline"]["margin_pct"] or {}).get("value")) is not None
    has_baseline = to_number(profile.get("eps_ttm")) not in (None, 0) or to_number(profile.get("fcf")) not in (None, 0)
    # First-pass confidence without circular range, then apply width.
    seed_conf = 0.5
    growth = _growth_plan(bridge, mapping, framework, confidence=seed_conf)
    multiples = _multiple_plan(pack, bridge, mapping, framework, growth, confidence=seed_conf, evidence=evidence_rows)
    confidence, width_reason = _confidence(
        mapping=mapping,
        growth=growth,
        multiples=multiples,
        missing=bridge["missing"],
        has_baseline=bool(has_baseline and last_close),
    )
    growth = _growth_plan(bridge, mapping, framework, confidence=confidence)
    margins = _margin_plan(bridge, mapping, framework, evidence_rows)
    multiples = _multiple_plan(pack, bridge, mapping, framework, growth, confidence=confidence, evidence=evidence_rows)

    eps0 = to_number((bridge["baseline"]["normalized_eps"] or {}).get("value")) if template_id == "energy" else to_number(profile.get("eps_ttm"))
    if template_id == "energy" and eps0 is None:
        eps0 = to_number(profile.get("eps_ttm"))
    revenue0 = to_number(profile.get("revenue_ttm"))
    fcf0 = to_number(profile.get("fcf"))
    shares = to_number((bridge["baseline"]["implied_shares"] or {}).get("value"))
    method = "eps_pe"
    if template_id == "energy":
        method = "normalized_earnings_pe" if eps0 not in (None, 0) else ("fcf" if fcf0 not in (None, 0) else "insufficient")
    elif eps0 in (None, 0):
        method = "fcf" if fcf0 not in (None, 0) else "insufficient"

    cases: dict[str, dict[str, Any]] = {}
    narratives = {
        "bear": "demand slows, contract/project timing slips, margin compresses, and the multiple de-rates",
        "base": "guidance is mostly delivered, evidenced contracts/plans convert, and margin follows a normal path",
        "bull": "end-demand persists, customer deployments or volumes expand, margin holds or improves, and a premium multiple can be sustained",
    }
    if template_id == "energy":
        narratives = {
            "bear": "realized prices and/or volumes weaken, FCF compresses, and the multiple goes to the cycle floor",
            "base": "volumes follow the stated plan, commodity is held near an un-evidenced unchanged level, earnings are cycle-normalized",
            "bull": "volumes deliver and realized prices are firmer, FCF holds, still not a growth-stock multiple",
        }

    for name in ("bear", "base", "bull"):
        case = empty_valuation_case()
        g = growth[name]
        margin_pct = margins.get(name)
        multiple = multiples[name]
        case["horizon"] = framework.get("horizon_label") or "1-3 years"
        case["valuation_method"] = method if method != "insufficient" else "insufficient_inputs"
        case["growth_assumptions"] = {
            "annual_rate": g,
            "years": years,
            "origin": growth["origin"],
            "source": "; ".join(growth["sources"][:3]),
            "warnings": growth["warnings"],
            "template_warning_growth": framework.get("warning_growth"),
            "template_fallback_growth": framework.get("fallback_growth"),
            "used_as_investment_assumption": growth["origin"] != "template_fallback",
        }
        case["margin_assumptions"] = {
            "net_margin_pct": margin_pct,
            "origin": margins.get("origin"),
            "path": "; ".join(margins.get("reasons") or []),
        }
        case["multiple"] = multiple
        decomp = dict(multiples["decomposition"])
        decomp["case_multiple"] = multiple
        case["multiple_decomposition"] = decomp
        case["multiple_reason"] = (
            f"{decomp['starting_anchor']['note']}. "
            f"growth premium {decomp['growth_premium']:+.0f}, "
            f"margin/quality {decomp['margin_quality_premium']:+.0f}, "
            f"recurring {decomp['recurring_revenue_premium']:+.0f}, "
            f"concentration {decomp['customer_concentration_discount']:+.0f}, "
            f"execution {decomp['cycle_execution_discount']:+.0f}. "
            f"{decomp['why_not_cycle_floor']}. {decomp['why_not_cycle_ceiling']}."
        )
        case["revenue_growth_reason"] = case["growth_assumptions"]["source"]
        case["margin_reason"] = case["margin_assumptions"]["path"]
        case["key_assumption_ids"] = list(key_assumption_ids or [row["assumption_id"] for row in mapping if row.get("assumption_id")])
        case["key_assumptions"] = [
            f"{row.get('driver')}: {row.get('status')} → {row.get('case_impact', {}).get(name)}"
            for row in mapping[:8]
        ]
        case["driver_origins"] = [
            {"driver": row.get("driver"), "origin": "assumption", "status": row.get("status")}
            for row in mapping
        ]
        case["case_narrative"] = narratives[name]
        case["invalidation"] = (
            "core delivery or normalized-earnings claims fail in subsequent official reports"
            if name != "bear"
            else "further commodity/demand collapse beyond the already-underwritten bear path"
        )

        fwd_rev = revenue0 * ((1.0 + g) ** years) if revenue0 not in (None, 0) else None
        fwd_earn = None
        fwd_eps = None
        origin_eps = "derived"
        if fwd_rev is not None and margin_pct not in (None, 0) and shares not in (None, 0):
            fwd_earn = fwd_rev * (float(margin_pct) / 100.0)
            fwd_eps = fwd_earn / float(shares)
            case["eps_derivation"] = (
                f"revenue {round(fwd_rev, 0)} = TTM {revenue0} × (1+{round(g*100, 1)}%)^{years}; "
                f"earnings = revenue × {margin_pct}% margin; EPS = earnings / implied shares {int(shares)}"
            )
        elif eps0 not in (None, 0):
            margin_factor = 1.0
            base_m = margins.get("base")
            if base_m not in (None, 0) and margin_pct not in (None, 0):
                margin_factor = float(margin_pct) / float(base_m)
            fwd_eps = float(eps0) * ((1.0 + g) ** years) * margin_factor
            if name == "bear":
                fwd_eps *= 0.90 if template_id == "energy" else 1.0
            case["eps_derivation"] = (
                f"EPS {round(fwd_eps, 2)} from {'normalized ' if template_id=='energy' else 'TTM '}EPS {eps0} "
                f"over {years}y at {round(g*100, 1)}% growth"
                + (f" and margin path {base_m}% → {margin_pct}%" if base_m and margin_pct else "")
            )
            origin_eps = "derived"
        case["revenue"] = round(fwd_rev, 0) if fwd_rev is not None else revenue0
        case["earnings"] = round(fwd_earn, 0) if fwd_earn is not None else None
        haircut = 0.15 if name == "bear" and template_id == "energy" else 0.0
        fwd_fcf = _fwd_fcf(fcf0, g, years, haircut=haircut)
        case["fcf"] = round(fwd_fcf, 0) if fwd_fcf is not None else fcf0

        target = None
        if method in {"eps_pe", "normalized_earnings_pe"} and fwd_eps not in (None, 0) and multiple:
            case["eps"] = round(fwd_eps, 2)
            target = round_target(fwd_eps * float(multiple))
            if method == "normalized_earnings_pe" and fwd_fcf and last_close:
                # Cross-check FCF yield: required yield ~ 1/multiple.
                fcf_yield = 1.0 / max(float(multiple), 1.0)
                shares_for_fcf = shares
                if shares_for_fcf in (None, 0) and last_close and eps0:
                    # last-resort: skip yield overlay
                    shares_for_fcf = None
                if shares_for_fcf not in (None, 0):
                    fcf_ps = float(fwd_fcf) / float(shares_for_fcf)
                    fcf_target = round_target(fcf_ps / fcf_yield) if fcf_yield else None
                    if fcf_target:
                        blended = round_target(0.6 * target + 0.4 * fcf_target)
                        case["notes"] = (
                            f"Normalized EPS×PE ~{display_target(target)}; FCF yield cross-check ~{display_target(fcf_target)}; blend ~{display_target(blended)}"
                        )
                        target = blended
        elif method == "fcf" and fwd_fcf and multiple:
            # Price from FCF / (1/multiple) using implied FCF yield.
            fcf_yield = 1.0 / max(float(multiple), 1.0)
            if shares not in (None, 0):
                target = round_target((float(fwd_fcf) / float(shares)) / fcf_yield)
            case["eps"] = round(fwd_eps, 2) if fwd_eps else None
            case["notes"] = "FCF yield path because EPS is missing"
        else:
            case["eps"] = round(fwd_eps, 2) if fwd_eps else eps0
            case["notes"] = "valuation inputs are incomplete; no target is invented"
        case["target_value"] = target
        case["target_display"] = display_target(target)
        case["upside_downside"] = _upside(target, last_close)
        if not case.get("notes"):
            case["notes"] = (
                f"{name}: growth {round(g*100, 1)}% ({growth['origin']}), "
                f"margin {margin_pct}%, multiple {multiple}x, {method}"
            )
        if name == "base" and case.get("eps") and multiple:
            case["sensitivity"] = _sensitivity(float(case["eps"]), float(multiple))
        cases[f"{name}_case"] = case

    has_target = to_number((cases["base_case"] or {}).get("target_value")) is not None
    status = _status_for(
        has_target=has_target,
        growth=growth,
        multiples=multiples,
        missing=bridge["missing"],
        margin_ok=margin_ok,
        guidance_ok=has_guidance,
        template_id=template_id,
    )
    market = _market_vs_model(
        spot=last_close,
        cases=cases,
        multiples=multiples,
        growth=growth,
        missing=bridge["missing"],
        status=status,
    )
    calibration = {
        "earnings_bridge": bridge,
        "driver_map": mapping,
        "valuation_status": status,
        "valuation_confidence": confidence,
        "range_width_reason": width_reason,
        "market_vs_model": market,
        "used_template_fallback": bool(growth.get("used_template_fallback") or multiples.get("used_template_anchor")),
        "missing": bridge["missing"],
        "method": method,
        "methods": methods,
        "growth": {k: growth[k] for k in ("bear", "base", "bull", "origin", "used_template_fallback", "warnings", "sources")},
        "multiples": {k: multiples[k] for k in ("bear", "base", "bull")},
        "multiple_decomposition": multiples["decomposition"],
    }
    return {
        "horizon": f"{years}y",
        "spot_price": last_close,
        "method": method,
        "methods": methods,
        "framework": framework,
        "bear_case": cases["bear_case"],
        "base_case": cases["base_case"],
        "bull_case": cases["bull_case"],
        "calibration_json": calibration,
        **calibration,
    }
