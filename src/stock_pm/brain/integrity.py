"""Deterministic financial input checks. LLM never owns these numbers."""

from __future__ import annotations

from typing import Any

from stock_pm.research.extract import to_number
from stock_pm.research.live_fetch import dedupe_earnings_prints


REVENUE_TOLERANCE = 0.03
EPS_TOLERANCE = 0.10


def _delta(left: float | None, right: float | None) -> float | None:
    if left in (None, 0) or right is None:
        return None
    return abs(float(left) - float(right)) / abs(float(left))


def _field(
    *,
    value: Any,
    source: str | None,
    source_date: str | None,
    cross_checked: bool,
    status: str,
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    row = {
        "value": value,
        "source": source,
        "source_date": source_date,
        "cross_checked": cross_checked,
        "status": status,
        "reason": reason,
    }
    row.update(extra)
    return row


def _header_metric(header: dict[str, Any], *path: str) -> Any:
    cur: Any = header
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if isinstance(cur, dict) and "value" in cur:
        return to_number(cur.get("value"))
    return to_number(cur)


def _compare(
    name: str,
    primary: float | None,
    secondary: float | None,
    tolerance: float,
    source: str | None,
    source_date: str | None,
    *,
    mismatch_status: str = "inconsistent",
    mismatch_reason: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if primary is None and secondary is None:
        return _field(value=None, source=source, source_date=source_date, cross_checked=False, status="missing", reason=f"{name} unavailable"), False
    if primary is not None and secondary is not None:
        gap = _delta(primary, secondary)
        if gap is not None and gap > tolerance:
            return (
                _field(
                    value=primary,
                    source=source,
                    source_date=source_date,
                    cross_checked=True,
                    status=mismatch_status,
                    reason=mismatch_reason or f"{name} sources disagree by {round(100.0 * gap, 1)}%",
                    secondary_value=secondary,
                    gap_pct=round(100.0 * gap, 1),
                ),
                True,
            )
        return (
            _field(
                value=primary,
                source=source,
                source_date=source_date,
                cross_checked=True,
                status="ok",
                reason=f"{name}: companyfacts and earnings release/Nasdaq agree within tolerance",
            ),
            False,
        )
    return (
        _field(
            value=primary if primary is not None else secondary,
            source=source,
            source_date=source_date,
            cross_checked=False,
            status="single_source",
            reason="only one trusted source is present",
        ),
        False,
    )


def assess_financial_integrity(pack: dict[str, Any] | None, header: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = pack or {}
    header = header or {}
    earnings = dedupe_earnings_prints(
        [row for row in (payload.get("earnings_history") or []) if isinstance(row, dict)]
    )
    latest = earnings[0] if earnings else {}
    fields = latest.get("provider_fields") if isinstance(latest.get("provider_fields"), dict) else {}
    facts_rev = to_number(fields.get("companyfacts_revenue"))
    nasdaq_rev = to_number(fields.get("nasdaq_revenue"))
    facts_eps = to_number(fields.get("companyfacts_eps"))
    nasdaq_eps = to_number(fields.get("nasdaq_eps"))
    header_rev = _header_metric(header, "latest_quarter", "revenue") or to_number(latest.get("revenue"))
    header_eps = _header_metric(header, "latest_quarter", "eps") or to_number(latest.get("eps"))
    period_end = str(latest.get("period_end") or "")[:10] or None
    fiscal_year = latest.get("fiscal_year") or (header.get("latest_quarter") or {}).get("fiscal_year")
    fiscal_period = latest.get("fiscal_period") or (header.get("latest_quarter") or {}).get("fiscal_period")
    source = str(latest.get("source") or ((header.get("latest_quarter") or {}).get("source") or ""))
    warnings: list[dict[str, str]] = []

    revenue, rev_bad = _compare("quarter_revenue", facts_rev or header_rev, nasdaq_rev, REVENUE_TOLERANCE, source, period_end)
    eps, eps_gap = _compare(
        "quarter_eps",
        facts_eps or header_eps,
        nasdaq_eps,
        EPS_TOLERANCE,
        source,
        period_end,
        mismatch_status="warning",
        mismatch_reason="GAAP companyfacts EPS vs Nasdaq print (often non-GAAP) differ; companyfacts GAAP is the Brain number. This does not block Core Claims.",
    )
    inconsistent = rev_bad
    ttm = _header_metric(header, "growth", "revenue_ttm") or to_number((payload.get("company_profile") or {}).get("revenue_ttm"))
    eps_ttm = _header_metric(header, "growth", "eps_ttm") or to_number((payload.get("company_profile") or {}).get("eps_ttm"))
    price = _header_metric(header, "price")
    price_ts = str(header.get("price_timestamp") or "") or None
    pe_header = _header_metric(header, "valuation", "pe_ttm")
    pe_calc = round(float(price) / float(eps_ttm), 2) if price not in (None, 0) and eps_ttm not in (None, 0) else None
    pe_value = pe_calc if pe_calc is not None else pe_header
    missing_core = header_rev is None or ttm is None or eps_ttm is None
    if inconsistent:
        warnings.append({"code": "financial_input_inconsistent", "reason": "Latest-quarter companyfacts and earnings-release revenue disagree beyond tolerance."})
    if eps_gap:
        warnings.append({"code": "eps_gaap_vs_nongaap", "reason": str(eps.get("reason") or "EPS sources differ")})
        eps["status"] = "warning"
    if missing_core:
        warnings.append({"code": "financial_input_incomplete", "reason": "TTM or latest-quarter revenue is missing."})

    def _simple(name: str, value: Any, *, reason: str, checked: bool = False, src: str | None = None, stamp: str | None = None) -> dict[str, Any]:
        return _field(
            value=to_number(value) if not isinstance(value, str) else value,
            source=src or source,
            source_date=stamp or period_end,
            cross_checked=checked,
            status="ok" if value not in (None, "") else "missing",
            reason=reason,
        )

    gm = _header_metric(header, "latest_quarter", "gross_margin") or to_number(latest.get("gross_margin_pct") or fields.get("gross_margin_pct"))
    om = _header_metric(header, "latest_quarter", "operating_margin") or to_number(latest.get("operating_margin_pct") or fields.get("operating_margin_pct"))
    rev_yoy = _header_metric(header, "latest_quarter", "revenue_yoy")
    eps_yoy = _header_metric(header, "latest_quarter", "eps_yoy")

    return {
        "ticker": payload.get("ticker") or header.get("ticker"),
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "inconsistent": inconsistent,
        "block_core_claims": inconsistent,
        "data_poor": missing_core and not inconsistent,
        "warnings": warnings,
        "fields": {
            "latest_quarter_revenue": revenue,
            "latest_quarter_eps": eps,
            "latest_quarter_revenue_yoy": _simple(
                "revenue_yoy",
                rev_yoy,
                reason="YoY uses the same fiscal period in the prior year (period_end ± ~365d)",
                checked=bool(period_end and rev_yoy is not None),
            ),
            "latest_quarter_eps_yoy": _simple(
                "eps_yoy",
                eps_yoy,
                reason="YoY uses the same fiscal period in the prior year (period_end ± ~365d)",
                checked=bool(period_end and eps_yoy is not None),
            ),
            "latest_quarter_gross_margin": _simple(
                "gross_margin",
                gm,
                reason="Gross profit / quarterly revenue from companyfacts",
                checked=gm is not None,
            ),
            "latest_quarter_operating_margin": _simple(
                "operating_margin",
                om,
                reason="Operating income / quarterly revenue from companyfacts",
                checked=om is not None,
            ),
            "ttm_revenue": _field(
                value=ttm,
                source=str((payload.get("company_profile") or {}).get("source") or "fundamentals"),
                source_date=str(payload.get("updated_at") or "") or period_end,
                cross_checked=bool(ttm and header_rev),
                status="ok" if ttm is not None else "missing",
                reason="TTM is the sum of four contiguous period_end quarters (missing Q4 is not filled with prior-year Q3)",
            ),
            "ttm_eps": _field(
                value=eps_ttm,
                source=str((payload.get("company_profile") or {}).get("source") or "fundamentals"),
                source_date=str(payload.get("updated_at") or "") or period_end,
                cross_checked=bool(eps_ttm and header_eps),
                status="ok" if eps_ttm is not None else "missing",
                reason="TTM EPS is the sum of the same four contiguous quarters",
            ),
            "price": _field(
                value=price,
                source="price_bars",
                source_date=price_ts,
                cross_checked=False,
                status="ok" if price is not None else "missing",
                reason="Python-owned last close",
            ),
            "price_timestamp": _field(
                value=price_ts,
                source="price_bars",
                source_date=price_ts,
                cross_checked=False,
                status="ok" if price_ts else "missing",
                reason="Session date of last close",
            ),
            "pe_ttm": _field(
                value=pe_value,
                source="calculated: last_close / eps_ttm" if pe_calc is not None else str((payload.get("company_profile") or {}).get("source") or "fundamentals"),
                source_date=price_ts or period_end,
                cross_checked=bool(price is not None and eps_ttm is not None),
                status="ok" if pe_value is not None else "missing",
                reason="PE = current price / TTM diluted EPS from companyfacts quarters",
                inputs={"price": price, "eps_ttm": eps_ttm},
            ),
        },
        "reason": "financial_input_inconsistent" if inconsistent else ("financial_input_incomplete" if missing_core else None),
    }
