"""Serialize kernel objects into the stock-page causal-chain view model."""

from __future__ import annotations

from typing import Any, Iterable

from .causal import CausalImpact, MarketConfirmation, canonical_metric
from .change import ChangeSnapshot, NO_MATERIAL_CHANGE
from .expectation import ExpectationGap
from .path import BACKGROUND_METRICS, LABOR_METRICS, RISK_METRICS
from .tension import PriceExpectationTension
from .thesis import Driver, ThesisSnapshot
from .types import FactRef
from .what_changed import NO_MATERIAL_CHANGE_THESIS, WhatChanged


CHAIN_STEPS = (
    ("what_changed", "What Changed", "事实发生了什么变化"),
    ("expectation", "Expectation Change", "相对预期如何变化"),
    ("tension", "Price / Expectation Tension", "价格已经反映了多少、事实/预期与价格是否背离"),
    ("causal_impact", "Causal Impact", "市场是否确认，以及通过什么机制传导"),
    ("thesis_impact", "Thesis Impact", "是否改变当前判断，以及具体改变了什么"),
)


def ref_view(ref: FactRef) -> dict[str, Any]:
    return {
        "ref_table": ref.ref_table,
        "ref_id": None if ref.ref_id is None else str(ref.ref_id),
        "as_of": ref.as_of,
        "source": ref.source,
        "text": ref.text,
        "synthetic": ref.synthetic,
        "http_source": getattr(ref, "http_source", None),
        "unit": getattr(ref, "unit", None),
        "status": getattr(ref, "status", None),
        "origin": getattr(ref, "origin", None),
    }


def _primary_ref(refs: Iterable[FactRef]) -> dict[str, Any] | None:
    rows = [ref_view(ref) for ref in refs]
    return rows[0] if rows else None


def change_view(change: ChangeSnapshot) -> dict[str, Any]:
    refs = [ref_view(ref) for ref in change.fact_refs]
    primary = refs[0] if refs else None
    if change.materiality == "material":
        status = "ok"
    elif change.materiality == "immaterial":
        status = "immaterial"
    else:
        status = "insufficient"
    return {
        "id": change.id,
        "metric": change.metric,
        "current": change.current_value,
        "previous": change.previous_value,
        "delta": change.delta,
        "delta_pct": change.delta_pct,
        "window": change.comparison_window,
        "direction": change.direction,
        "materiality": change.materiality,
        "summary": change.summary,
        "why": change.summary,
        "affects": change.subject or change.metric,
        "scope": change.scope,
        "subject": change.subject,
        "as_of": change.current_as_of,
        "previous_as_of": change.previous_as_of,
        "source": primary["source"] if primary else None,
        "ref": primary,
        "refs": refs,
        "status": status,
        "counter": None,
        "unit": change.unit,
        "series": None,
        "formula": None,
        "comparison": None,
        "origin": "primary",
        "http_source": getattr(primary, "get", lambda *_: None)("http_source") if primary else None,
    }


def gap_view(gap: ExpectationGap) -> dict[str, Any]:
    refs = [ref_view(ref) for ref in gap.fact_refs]
    primary = refs[0] if refs else None
    has_actual = gap.actual is not None
    current = gap.actual if has_actual else gap.latest_consensus
    previous = gap.latest_consensus if has_actual else gap.prior_consensus
    if has_actual:
        delta = gap.surprise_pct
        as_of = gap.actual_as_of or gap.latest_consensus_as_of
        previous_as_of = gap.latest_consensus_as_of
    else:
        delta = None if current is None or previous is None else current - previous
        as_of = gap.latest_consensus_as_of
        previous_as_of = gap.prior_consensus_as_of
    return {
        "id": gap.id,
        "metric": gap.metric,
        "fiscal_period": gap.fiscal_period,
        "current": current,
        "previous": previous,
        "prior": gap.prior_consensus,
        "latest": gap.latest_consensus,
        "actual": gap.actual,
        "delta": delta,
        "delta_pct": gap.surprise_pct if has_actual else gap.revision_pct,
        "revision_pct": gap.revision_pct,
        "revision_trend": gap.revision_trend,
        "window": gap.fiscal_period,
        "direction": gap.revision_trend,
        "status": gap.status,
        "code": gap.code,
        "summary": gap.reason,
        "why": gap.reason,
        "affects": gap.subject or gap.metric,
        "scope": gap.scope,
        "subject": gap.subject,
        "as_of": as_of,
        "previous_as_of": previous_as_of,
        "source": primary["source"] if primary else None,
        "ref": primary,
        "refs": refs,
        "counter": None if gap.status == "ok" else gap.reason,
    }


def tension_view(tension: PriceExpectationTension | None) -> dict[str, Any]:
    if tension is None:
        return {
            "status": "insufficient",
            "tension": "insufficient",
            "code": "insufficient",
            "reason": "缺少价格或预期变动，不能描述价格/预期张力",
            "why": "缺少价格或预期变动，不能描述价格/预期张力",
            "price_change": None,
            "fundamentals_change": None,
            "valuation_change": None,
            "evidence_quality": "insufficient",
            "divergence_kind": None,
            "affects": "price / expectation",
            "window": "price vs expectation",
            "direction": None,
        }
    return {
        "status": tension.tension,
        "tension": tension.tension,
        "code": tension.code,
        "reason": tension.reason,
        "why": tension.reason,
        "price_change": tension.price_change,
        "fundamentals_change": tension.fundamentals_change,
        "valuation_change": tension.valuation_change,
        "evidence_quality": tension.evidence_quality,
        "divergence_kind": tension.divergence_kind,
        "current": tension.price_change,
        "previous": tension.fundamentals_change,
        "delta": None
        if tension.price_change is None or tension.fundamentals_change is None
        else tension.price_change - tension.fundamentals_change,
        "window": "price vs expectation",
        "direction": tension.tension,
        "affects": "price / expectation",
    }


def confirmation_view(confirmation: MarketConfirmation | None) -> dict[str, Any]:
    if confirmation is None:
        return {
            "path": None,
            "status": "insufficient",
            "code": "missing_confirmation",
            "reason": "未评估市场确认",
            "channels": [],
            "used": [],
            "series": [],
        }
    return {
        "path": confirmation.path,
        "status": confirmation.status,
        "code": confirmation.code,
        "reason": confirmation.reason,
        "channels": list(confirmation.channels),
        "used": [change_view(row) for row in confirmation.used],
        "series": [change_view(row) for row in confirmation.series],
    }


def impact_view(impact: CausalImpact) -> dict[str, Any]:
    refs = [ref_view(ref) for ref in impact.fact_refs]
    primary = refs[0] if refs else None
    exposure = impact.exposure
    cause = change_view(impact.cause) if impact.cause else None
    if primary is None and cause and cause.get("ref"):
        primary = cause["ref"]
        refs = list(cause.get("refs") or [primary])
    return {
        "id": impact.id,
        "status": impact.status,
        "code": impact.code,
        "direction": impact.direction,
        "mechanism": impact.mechanism,
        "chain": list(impact.chain),
        "reason": impact.reason,
        "why": impact.reason,
        "affects": impact.effect_target,
        "horizon": impact.horizon,
        "counter": list(impact.counter_evidence),
        "current": None if cause is None else cause["current"],
        "previous": None if cause is None else cause["previous"],
        "delta": None if cause is None else cause["delta"],
        "delta_pct": None if cause is None else cause["delta_pct"],
        "window": None if cause is None else cause["window"],
        "exposure": None
        if exposure is None
        else {
            "target": exposure.target,
            "target_kind": exposure.target_kind,
            "channel": exposure.channel,
            "theme": exposure.theme,
        },
        "confirmation": confirmation_view(impact.market_confirmation),
        "cause": cause,
        "as_of": impact.cause.current_as_of if impact.cause else None,
        "source": primary["source"] if primary else None,
        "ref": primary,
        "refs": refs,
    }


def driver_view(driver: Driver) -> dict[str, Any]:
    return {"text": driver.text, "based_on": list(driver.based_on)}


def thesis_view(thesis: ThesisSnapshot) -> dict[str, Any]:
    return {
        "direction": thesis.direction,
        "status": thesis.status,
        "code": thesis.code,
        "reason": thesis.reason,
        "evidence_quality": thesis.evidence_quality,
        "key_disagreement": thesis.key_disagreement,
        "invalidation": thesis.invalidation,
        "bull_drivers": [driver_view(row) for row in thesis.bull_drivers],
        "bear_drivers": [driver_view(row) for row in thesis.bear_drivers],
        "based_on_change_ids": list(thesis.based_on_change_ids),
        "based_on_expectation_ids": list(thesis.based_on_expectation_ids),
        "based_on_causal_impact_ids": list(thesis.based_on_causal_impact_ids),
        "generated_at": thesis.generated_at,
        "symbol": thesis.symbol,
        "synthetic": thesis.synthetic,
    }


def what_changed_view(report: WhatChanged) -> dict[str, Any]:
    return {
        "summary": report.summary,
        "thesis_changed": report.thesis_changed,
        "changed_fields": list(report.changed_fields),
        "items": [
            {
                "kind": item.kind,
                "what": item.what,
                "why_it_matters": item.why_it_matters,
                "affects": item.affects,
                "thesis_effect": item.thesis_effect,
                "why_thesis_effect": item.why_thesis_effect,
                "derived_reason": item.why_thesis_effect,
                "ref_id": item.ref_id,
                "as_of": item.as_of,
                "material": item.material,
                "ref": None
                if not item.ref_id and not item.as_of
                else {
                    "ref_table": None,
                    "ref_id": item.ref_id,
                    "as_of": item.as_of,
                    "source": None,
                },
            }
            for item in report.items
        ],
    }


def _step(key: str, status: str, items: list[dict[str, Any]], *, empty_reason: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    title_en, title_zh = next((en, zh) for item, en, zh in CHAIN_STEPS if item == key)
    payload = {
        "id": key,
        "title": title_en,
        "title_zh": title_zh,
        "status": status,
        "items": items,
        "empty_reason": empty_reason,
    }
    if extra:
        payload.update(extra)
    return payload


def render_decision_view(
    *,
    symbol: str,
    changes: Iterable[ChangeSnapshot],
    expectations: Iterable[ExpectationGap],
    confirmation: MarketConfirmation | None,
    impacts: Iterable[CausalImpact],
    thesis: ThesisSnapshot,
    what_changed: WhatChanged,
    data_gaps: list[dict[str, str]],
    facts: list[dict[str, Any]],
    clues: list[dict[str, Any]] | None = None,
    synthetic: bool = False,
    preview: str | None = None,
    as_of: str | None = None,
    compared_to: dict[str, Any] | None = None,
    clock_status: str = "ok",
    tension: PriceExpectationTension | None = None,
    rates_chain_blocked: bool = False,
    graded: dict[str, Any] | None = None,
    rates_path: dict[str, Any] | None = None,
    risk_state: dict[str, Any] | None = None,
    market_background: list[dict[str, Any]] | None = None,
    inject: list[str] | None = None,
) -> dict[str, Any]:
    change_rows = [change_view(row) for row in changes]
    gap_rows = [gap_view(row) for row in expectations]
    impact_rows = [impact_view(row) for row in impacts]
    catalog = list(facts or []) + list(market_background or [])
    fact_by_metric = {
        canonical_metric(str(row.get("metric") or "")): row
        for row in catalog
        if row.get("metric")
    }
    for row in change_rows:
        extra = fact_by_metric.get(canonical_metric(str(row.get("metric") or "")))
        if not extra:
            continue
        row["series"] = extra.get("series")
        row["formula"] = extra.get("formula")
        row["comparison"] = extra.get("comparison")
        row["unit"] = row.get("unit") or extra.get("unit")
        row["origin"] = extra.get("origin") or row.get("origin")
        row["http_source"] = extra.get("http_source") or row.get("http_source")
        row["period"] = extra.get("period")
        row["previous_period"] = extra.get("previous_period")
        if row.get("ref"):
            row["ref"]["http_source"] = extra.get("http_source") or row["ref"].get("http_source")
            row["ref"]["unit"] = extra.get("unit") or row["ref"].get("unit")
            row["ref"]["status"] = extra.get("status") or row["ref"].get("status")
            row["ref"]["origin"] = extra.get("origin") or row["ref"].get("origin")
    hidden_metrics = BACKGROUND_METRICS | LABOR_METRICS | RISK_METRICS
    visible_change_rows = [
        row
        for row in change_rows
        if canonical_metric(str(row.get("metric") or "")) not in hidden_metrics
    ]
    confirm = confirmation_view(confirmation)
    tension_row = tension_view(tension)
    report = what_changed_view(what_changed)
    visible_what_items = [
        item
        for item in report["items"]
        if canonical_metric(str(item.get("affects") or "")) not in hidden_metrics
    ]
    clues = list(clues or ())
    no_material = report["summary"] == NO_MATERIAL_CHANGE_THESIS

    if any(row["materiality"] == "material" for row in change_rows):
        changed_status = "ok"
        changed_empty = None
    elif change_rows:
        changed_status = "immaterial"
        changed_empty = NO_MATERIAL_CHANGE
    else:
        changed_status = "insufficient"
        changed_empty = "数据不足，没有可比较的事实变化"

    if gap_rows:
        statuses = {row["status"] for row in gap_rows}
        if "conflict" in statuses:
            expect_status = "conflict"
        elif statuses == {"ok"}:
            expect_status = "ok"
        else:
            expect_status = next((row["status"] for row in gap_rows if row["status"] != "ok"), "insufficient")
        expect_empty = None
    else:
        expect_status = "insufficient"
        expect_empty = next(
            (
                row["text"]
                for row in data_gaps
                if row.get("code")
                in {"missing_rate_path_expectation", "missing_prior_consensus", "missing_latest_consensus"}
            ),
            "数据不足：缺失可追溯的预期变化（current vs prior + as_of + source）",
        )

    tension_status = tension_row["status"]
    if tension_status == "insufficient":
        tension_empty = tension_row["reason"]
        tension_items: list[dict[str, Any]] = []
    else:
        tension_empty = None
        tension_items = [tension_row]

    if rates_chain_blocked:
        causal_status = "watch"
        trans_status = "watch"
        trans_empty = next(
            (row["text"] for row in data_gaps if row.get("code") == "rates_chain_incomplete"),
            "利率贴现机制缺少可追溯预期或价格/预期张力，不能形成方向性因果，只能观察",
        )
        for row in impact_rows:
            if row.get("status") == "valid":
                row["status"] = "watch"
                row["direction"] = None
                row["why"] = trans_empty
                row["reason"] = trans_empty
    elif impact_rows:
        trans_status = impact_rows[0]["status"]
        trans_empty = None
        causal_status = trans_status
    else:
        trans_status = "insufficient"
        trans_empty = next(
            (row["text"] for row in data_gaps if row.get("code") == "missing_mechanism"),
            "缺传导机制或 exposure，宏观不能直接跳到个股",
        )
        causal_status = "insufficient"

    if rates_chain_blocked or expect_status != "ok" or tension_status == "insufficient":
        if not no_material:
            causal_status = "watch" if rates_chain_blocked or impact_rows else causal_status

    if report["thesis_changed"]:
        impact_status = thesis.status if thesis.status != "ok" else "ok"
    elif no_material:
        impact_status = "immaterial"
    else:
        impact_status = thesis.status
    if rates_chain_blocked and impact_status == "ok":
        impact_status = "watch"

    chain = [
        _step("what_changed", changed_status, change_rows, empty_reason=changed_empty),
        _step("expectation", expect_status, gap_rows, empty_reason=expect_empty),
        _step(
            "tension",
            tension_status,
            tension_items,
            empty_reason=tension_empty,
            extra={"tension": tension_row},
        ),
        _step(
            "causal_impact",
            causal_status,
            impact_rows,
            empty_reason=trans_empty if not impact_rows else None,
            extra={
                "confirmation": confirm,
                "clues": clues,
                "transmission_status": trans_status,
                "transmission_empty": trans_empty,
            },
        ),
        _step(
            "thesis_impact",
            impact_status,
            report["items"],
            empty_reason=report["summary"] if not report["items"] else None,
            extra={
                "thesis_changed": report["thesis_changed"],
                "changed_fields": report["changed_fields"],
                "derived_reason": report["summary"],
                "summary": report["summary"],
                "tension_status": tension_status,
                "tension_code": tension_row.get("code"),
                "tension_reason": tension_row.get("reason"),
            },
        ),
    ]

    blocking = [row for row in data_gaps if row.get("code") == "clock_insufficient"]
    overall = (graded or {}).get("overall") or {}
    can_form_direction = bool((graded or {}).get("can_form_direction"))
    overall_level = overall.get("level") or "L0"
    cannot = clock_status == "clock_insufficient" or overall_level == "L0"
    reason = None
    if cannot:
        if clock_status == "clock_insufficient" and blocking:
            reason = blocking[0]["text"]
        else:
            reason = overall.get("cannot_determine") or "核心事实无效或不可追溯，不能分析"
        if not str(reason).startswith("目前不能形成判断"):
            reason = f"目前不能形成判断：{reason}"
    if overall_level == "L3" and can_form_direction:
        evidence_quality = "complete"
    elif overall_level in {"L2", "L3"}:
        evidence_quality = "partial"
    elif overall_level == "L1":
        evidence_quality = "partial"
    else:
        evidence_quality = "insufficient"
    return {
        "symbol": symbol,
        "as_of": None if clock_status == "clock_insufficient" else as_of,
        "clock_status": clock_status,
        "cannot_form_judgment": cannot,
        "cannot_form_judgment_reason": reason,
        "can_form_direction": can_form_direction,
        "overall": overall,
        "chains": list((graded or {}).get("chains") or ()),
        "evidence_quality": evidence_quality,
        "thesis": thesis_view(thesis),
        "updated_at": thesis.generated_at,
        "compared_to": compared_to or {"as_of": None, "changed_fields": report["changed_fields"]},
        "synthetic": synthetic,
        "preview": preview,
        "preview_label": "合成演示数据" if synthetic else None,
        "gaps": data_gaps,
        "chain": chain,
        "what_changed": report,
        "clues": clues,
        "facts": facts,
        "no_material_change": no_material,
        "rates_chain_blocked": rates_chain_blocked,
        "layers": [
            {"id": "fact", "title": "Fact", "title_zh": "事实", "items": facts},
            {"id": "change", "title": "Change", "title_zh": "相对什么变了", "items": visible_change_rows},
            {"id": "expectation", "title": "Expectation", "title_zh": "预期如何变", "items": gap_rows},
            {"id": "impact", "title": "Impact", "title_zh": "如何传导", "items": impact_rows, "path": rates_path, "risk_state": risk_state},
            {"id": "what_changes", "title": "What changes", "title_zh": "改变了哪个判断", "items": visible_what_items},
        ],
        "rates_path": rates_path,
        "risk_state": risk_state,
        "market_background": list(market_background or ()),
        "inject": list(inject or ()),
    }
