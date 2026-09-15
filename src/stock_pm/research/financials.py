"""Financial statement integrity helpers for valuation.

Operating, gross, and net margins are never substituted for each other.
Share count is never implied from operating income / EPS.
"""

from __future__ import annotations

from typing import Any

from .extract import nested_get, to_number


GROWTH_ORIGINS = (
    "management_guidance",
    "consensus",
    "historical_delivery",
    "evidence_derived",
    "fallback",
)
SHARE_ORIGINS = (
    "sec_10q",
    "sec_10k",
    "companyfacts",
    "earnings_release",
    "derived_ni_eps",
    "market_cap_price",
    "missing",
)


def lineage(
    value: Any,
    *,
    origin: str,
    period: str | None = None,
    source: str | None = None,
    source_id: str | None = None,
    source_url: str | None = None,
    quality: str = "secondary",
    note: str = "",
    display: str | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "period": period,
        "origin": origin,
        "source": source,
        "source_id": source_id,
        "source_url": source_url,
        "quality": quality,
        "note": note,
        "display": display,
    }


def round_pp(rate: float | None, step: int = 5) -> float | None:
    """Round a growth rate to step percentage points. 0.389 → 0.40 when step=5."""
    if rate is None:
        return None
    pct = float(rate) * 100.0
    if pct >= 0:
        snapped = int(pct / step + 0.5) * step
    else:
        snapped = int(pct / step - 0.5) * step
    return snapped / 100.0


def coarsen_growth(rate: float | None, *, template_id: str | None = None) -> float | None:
    """Coarse growth: 5pp above ~10%, 1pp for small/energy paths. Never keep 38.9-style precision."""
    if rate is None:
        return None
    if str(template_id or "") == "energy" or abs(float(rate)) < 0.10:
        return round(float(rate) * 100.0) / 100.0
    return round_pp(rate, 5)


def display_pct(rate: float | None, *, template_id: str | None = None) -> str | None:
    if rate is None:
        return None
    pct = coarsen_growth(rate, template_id=template_id)
    if pct is None:
        return None
    number = int(round(pct * 100))
    return f"~{number}%"


def display_pct_range(
    low: float | None,
    high: float | None,
    center: float | None = None,
    *,
    template_id: str | None = None,
) -> str | None:
    lo = coarsen_growth(low, template_id=template_id)
    hi = coarsen_growth(high, template_id=template_id)
    mid = coarsen_growth(center, template_id=template_id) if center is not None else None
    if lo is None and hi is None and mid is None:
        return None
    if lo is not None and hi is not None and lo != hi:
        text = f"~{int(round(lo * 100))}–{int(round(hi * 100))}%"
        if mid is not None:
            text += f"; Base {display_pct(mid, template_id=template_id)}"
        return text
    return display_pct(mid if mid is not None else lo if lo is not None else hi, template_id=template_id)


def display_margin(value: float | None) -> str | None:
    if value is None:
        return None
    return f"~{int(round(float(value)))}%"


def _raw(fundamentals: dict[str, Any] | None) -> dict[str, Any]:
    payload = fundamentals or {}
    raw = payload.get("raw_data")
    return raw if isinstance(raw, dict) else {}


def separate_margins(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return gross / operating / net as independent lineage rows. Never mix them."""
    profile = pack.get("company_profile") or {}
    earnings = list(pack.get("earnings_history") or [])
    latest = earnings[0] if earnings else {}
    out: dict[str, dict[str, Any]] = {}
    for key, label in (
        ("gross_margin_pct", "gross_margin"),
        ("operating_margin_pct", "operating_margin"),
        ("net_margin_pct", "net_margin"),
    ):
        value = to_number(profile.get(key))
        if value is not None:
            out[label] = lineage(
                value,
                origin="observed",
                period="TTM",
                source="fundamentals_snapshot",
                quality="primary",
                note=label.replace("_", " "),
                display=display_margin(value),
            )
            continue
        field = to_number(latest.get(key)) if isinstance(latest, dict) else None
        if field is not None:
            out[label] = lineage(
                field,
                origin="observed",
                period=str(latest.get("fiscal_period") or latest.get("report_date") or ""),
                source=str(latest.get("source") or "earnings_print"),
                quality="primary",
                note=f"latest print {label.replace('_', ' ')}",
                display=display_margin(field),
            )
            continue
        out[label] = lineage(None, origin="missing", quality="weak", note=f"{label} not in pack")

    if out["net_margin"].get("value") is None:
        revenue = to_number(latest.get("revenue"))
        net_income = to_number(latest.get("earnings") or latest.get("net_income"))
        derived = None
        if revenue not in (None, 0) and net_income is not None:
            derived = round(100.0 * float(net_income) / float(revenue), 1)
            period = str(latest.get("fiscal_period") or "latest print")
            source = "earnings_print_ni_over_revenue"
        else:
            revs = [to_number(row.get("revenue")) for row in earnings[:4]]
            nis = [to_number(row.get("earnings") or row.get("net_income")) for row in earnings[:4]]
            if revs and nis and all(item not in (None, 0) for item in revs) and all(item is not None for item in nis):
                derived = round(100.0 * sum(float(item) for item in nis) / sum(float(item) for item in revs), 1)
                period = "TTM from last four prints"
                source = "earnings_history_ni_over_revenue"
            else:
                period = None
                source = None
        if derived is not None:
            out["net_margin"] = lineage(
                derived,
                origin="derived",
                period=period,
                source=source,
                quality="secondary",
                note="net income / revenue; not operating or gross margin",
                display=display_margin(derived),
            )
    return out


def resolve_diluted_shares(pack: dict[str, Any]) -> dict[str, Any]:
    """Prefer reported diluted WAS. Never back out shares from operating income / EPS."""
    profile = pack.get("company_profile") or {}
    earnings = list(pack.get("earnings_history") or [])
    latest = earnings[0] if earnings else {}
    value = to_number(profile.get("diluted_shares") or profile.get("diluted_weighted_average_shares"))
    if value not in (None, 0):
        origin = str(profile.get("diluted_shares_origin") or "companyfacts")
        quality = "primary" if origin in {"sec_10q", "sec_10k", "companyfacts", "earnings_release"} else "secondary"
        return lineage(
            value,
            origin=origin,
            period=str(profile.get("diluted_shares_period") or "TTM/latest"),
            source=str(profile.get("diluted_shares_source") or origin),
            source_url=profile.get("diluted_shares_source_url"),
            quality=quality,
            note="reported diluted weighted-average shares",
        )
    latest_shares = None
    if isinstance(latest, dict):
        latest_shares = to_number(latest.get("diluted_shares"))
        if latest_shares in (None, 0):
            latest_shares = to_number((latest.get("provider_fields") or {}).get("diluted_shares"))
    if latest_shares not in (None, 0):
        return lineage(
            latest_shares,
            origin="earnings_release",
            period=str(latest.get("fiscal_period") or latest.get("period_end") or ""),
            source=str(latest.get("source") or "earnings_print"),
            quality="primary",
            note="diluted shares on the earnings print",
        )
    ni = to_number(latest.get("earnings") or latest.get("net_income")) if isinstance(latest, dict) else None
    eps = to_number(latest.get("eps")) if isinstance(latest, dict) else None
    if ni not in (None, 0) and eps not in (None, 0):
        return lineage(
            float(ni) / float(eps),
            origin="derived_ni_eps",
            period=str(latest.get("fiscal_period") or "latest print"),
            source="earnings_print",
            quality="secondary",
            note="net income / diluted EPS for the same print; not operating income / EPS",
        )
    ttm_ni = to_number(profile.get("net_income_ttm"))
    ttm_eps = to_number(profile.get("eps_ttm"))
    if ttm_ni in (None, 0):
        nis = [to_number(row.get("earnings") or row.get("net_income")) for row in earnings[:4]]
        if nis and all(item is not None for item in nis) and len(nis) == 4:
            ttm_ni = sum(float(item) for item in nis)
    if ttm_ni not in (None, 0) and ttm_eps not in (None, 0):
        return lineage(
            float(ttm_ni) / float(ttm_eps),
            origin="derived_ni_eps",
            period="TTM",
            source="earnings_history",
            quality="secondary",
            note="TTM net income / TTM diluted EPS; not operating income / EPS",
        )
    market_cap = to_number(profile.get("market_cap"))
    last_close = to_number(profile.get("last_close"))
    if market_cap not in (None, 0) and last_close not in (None, 0):
        return lineage(
            float(market_cap) / float(last_close),
            origin="market_cap_price",
            period="spot",
            source="fundamentals_snapshot",
            quality="weak",
            note="market cap / last close; low-quality fallback, not weighted-average diluted shares",
        )
    return lineage(None, origin="missing", quality="weak", note="no diluted share count")


def consensus_forward_eps(pack: dict[str, Any]) -> dict[str, Any]:
    profile = pack.get("company_profile") or {}
    pe_fwd = to_number(profile.get("pe_forward"))
    last_close = to_number(profile.get("last_close"))
    if pe_fwd not in (None, 0) and last_close not in (None, 0):
        eps = float(last_close) / float(pe_fwd)
        return lineage(
            round(eps, 2),
            origin="consensus",
            period="NTM",
            source="fundamentals_snapshot",
            quality="secondary",
            note="last close / forward PE",
            display=f"~{round(eps, 1)}",
        )
    return lineage(None, origin="missing", quality="weak", note="no forward PE")


def ttm_net_income(pack: dict[str, Any]) -> float | None:
    profile = pack.get("company_profile") or {}
    direct = to_number(profile.get("net_income_ttm"))
    if direct is not None:
        return direct
    earnings = list(pack.get("earnings_history") or [])
    nis = [to_number(row.get("earnings") or row.get("net_income")) for row in earnings[:4]]
    if len(nis) == 4 and all(item is not None for item in nis):
        return sum(float(item) for item in nis)
    return None
