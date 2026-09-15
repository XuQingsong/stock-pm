"""Template-driven Bear / Base / Bull valuation. Numbers stay coarse on purpose."""

from __future__ import annotations

from typing import Any

from .extract import to_number
from .templates import load_template
from .types import empty_valuation_case


DEFAULT_FRAMEWORKS = {
    "semiconductor": {
        "primary_methods": ["eps_pe", "fcf"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "multiple_bear": 18,
        "multiple_base": 28,
        "multiple_bull": 40,
        "max_base_growth": 0.25,
        "max_bull_growth": 0.40,
        "bear_growth_factor": 0.30,
        "bear_eps_haircut": 0.15,
        "multiple_reason": (
            "semiconductor earnings power is valued on forward EPS times a cycle PE band; "
            "the current TTM PE is a reference, not automatically the 2-year base multiple"
        ),
    },
    "energy": {
        "primary_methods": ["earnings_pe", "fcf"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "multiple_bear": 8,
        "multiple_base": 12,
        "multiple_bull": 16,
        "max_base_growth": 0.08,
        "max_bull_growth": 0.12,
        "bear_growth_factor": 0.0,
        "bear_eps_haircut": 0.20,
        "multiple_reason": (
            "energy producers are valued on cycle-normalized earnings and FCF rather than peak growth multiples"
        ),
    },
    "generic_company": {
        "primary_methods": ["eps_pe"],
        "horizon_years": 2,
        "horizon_label": "1-3 years",
        "multiple_kind": "pe",
        "multiple_bear": 12,
        "multiple_base": 18,
        "multiple_bull": 24,
        "max_base_growth": 0.12,
        "max_bull_growth": 0.20,
        "bear_growth_factor": 0.25,
        "bear_eps_haircut": 0.10,
        "multiple_reason": (
            "a generic operating company is valued on forward EPS times a moderate PE band unless a tighter method is evidenced"
        ),
    },
}


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
    rounded = int(round(float(value) / step) * step)
    return rounded


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
    return raw


def _cagr_from_text(text: str) -> float | None:
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*cagr", text or "", re.I)
    if match:
        return float(match.group(1)) / 100.0
    return None


def stated_growth(assumptions: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> float | None:
    blobs = [str(row.get("statement") or "") for row in assumptions]
    blobs.extend(str(row.get("fact") or "") for row in evidence)
    rates = [item for item in (_cagr_from_text(text) for text in blobs) if item is not None]
    if not rates:
        return None
    return max(rates)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _growth_set(pack: dict[str, Any], framework: dict[str, Any], *, stated: float | None) -> dict[str, float]:
    profile = pack.get("company_profile") or {}
    yoy = to_number(profile.get("revenue_growth_yoy_pct") or profile.get("eps_growth_yoy_pct"))
    yoy_rate = (yoy / 100.0) if yoy is not None else None
    max_base = float(framework.get("max_base_growth") or 0.12)
    max_bull = float(framework.get("max_bull_growth") or 0.20)
    seed = stated if stated is not None else yoy_rate
    if seed is None:
        seed = 0.0
    base = _clip(seed, -0.2, max_base)
    bull = _clip(max(seed, base), -0.2, max_bull)
    bear = _clip(base * float(framework.get("bear_growth_factor") or 0.25), -0.25, max_base)
    return {"bear": round(bear, 4), "base": round(base, 4), "bull": round(bull, 4)}


def _multiples(framework: dict[str, Any], current_pe: float | None) -> dict[str, float]:
    bear = float(framework.get("multiple_bear") or 12)
    base = float(framework.get("multiple_base") or 18)
    bull = float(framework.get("multiple_bull") or 24)
    if current_pe and current_pe > 0:
        bull = max(bull, min(current_pe, bull * 1.15))
        if current_pe < base:
            base = max(bear, current_pe)
    return {"bear": round(bear, 1), "base": round(base, 1), "bull": round(bull, 1)}


def _fwd_eps(eps0: float, growth: float, years: int, *, haircut: float = 0.0) -> float:
    value = float(eps0) * ((1.0 + growth) ** years)
    return value * (1.0 - haircut)


def _upside(target: int | None, spot: float | None) -> dict[str, Any] | None:
    if target is None or spot in (None, 0):
        return None
    pct = round(100.0 * (float(target) / float(spot) - 1.0), 0)
    return {"spot": round(float(spot), 2), "target": target, "pct": int(pct)}


def _sensitivity(eps: float, multiple: float) -> list[dict[str, Any]]:
    base = eps * multiple
    rows = [
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
    return rows


def build_valuation_cases(
    pack: dict[str, Any],
    *,
    assumptions: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    key_assumption_ids: list[str] | None = None,
) -> dict[str, Any]:
    template = load_template(pack.get("template_id"))
    framework = framework_for(pack.get("template_id"), template)
    profile = pack.get("company_profile") or {}
    eps0 = to_number(profile.get("eps_ttm"))
    revenue = to_number(profile.get("revenue_ttm"))
    fcf = to_number(profile.get("fcf"))
    last_close = to_number(profile.get("last_close"))
    current_pe = to_number(profile.get("pe_ttm"))
    net_margin = to_number(profile.get("net_margin_pct"))
    years = int(framework.get("horizon_years") or 2)
    growth = _growth_set(pack, framework, stated=stated_growth(assumptions or [], evidence or []))
    multiples = _multiples(framework, current_pe)
    methods = list(framework.get("primary_methods") or ["eps_pe"])
    method = "eps_pe" if eps0 not in (None, 0) else ("fcf" if fcf not in (None, 0) else "insufficient")
    missing = []
    if eps0 in (None, 0):
        missing.append("eps_ttm")
    if last_close in (None, 0):
        missing.append("last_close")
    cases: dict[str, dict[str, Any]] = {}
    for name in ("bear", "base", "bull"):
        case = empty_valuation_case()
        case["horizon"] = framework.get("horizon_label") or "1-3 years"
        case["revenue"] = revenue
        case["fcf"] = fcf
        case["valuation_method"] = method if method != "insufficient" else "insufficient_inputs"
        case["growth_assumptions"] = {
            "annual_rate": growth[name],
            "years": years,
            "source": "stated CAGR in source text" if stated_growth(assumptions or [], evidence or []) is not None else "capped recent growth, not raw print-year growth",
        }
        case["margin_assumptions"] = {
            "net_margin_pct": net_margin,
            "eps_haircut": float(framework.get("bear_eps_haircut") or 0) if name == "bear" else 0.0,
        }
        case["multiple"] = multiples[name]
        case["multiple_reason"] = (
            f"{framework.get('multiple_reason')}. "
            + (f"Current TTM PE is {current_pe}. " if current_pe else "Current TTM PE is unavailable. ")
            + f"{name} uses {multiples[name]}x vs template band {multiples['bear']}-{multiples['bull']}x."
        )
        case["key_assumption_ids"] = list(key_assumption_ids or [])
        if method == "eps_pe" and eps0 not in (None, 0):
            haircut = float(framework.get("bear_eps_haircut") or 0) if name == "bear" else 0.0
            fwd = _fwd_eps(eps0, growth[name], years, haircut=haircut)
            case["eps"] = round(fwd, 2)
            target = round_target(fwd * multiples[name])
            case["target_value"] = target
            case["target_display"] = display_target(target)
            case["upside_downside"] = _upside(target, last_close)
            case["notes"] = (
                f"Forward EPS ~{round(fwd, 2)} from TTM EPS {eps0} over {years}y at {round(growth[name]*100, 1)}% "
                f"{'after a bear haircut' if haircut else ''}".strip()
            )
            if name == "base":
                case["sensitivity"] = _sensitivity(fwd, multiples[name])
        else:
            case["eps"] = eps0
            case["target_value"] = None
            case["target_display"] = None
            case["notes"] = "valuation inputs are incomplete; no target is invented"
            missing.append("target")
        cases[f"{name}_case"] = case
    return {
        "horizon": f"{years}y",
        "spot_price": last_close,
        "method": method,
        "methods": methods,
        "framework": framework,
        "growth": growth,
        "multiples": multiples,
        "missing": list(dict.fromkeys(missing)),
        "bear_case": cases["bear_case"],
        "base_case": cases["base_case"],
        "bull_case": cases["bull_case"],
    }
