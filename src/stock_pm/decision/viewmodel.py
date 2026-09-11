"""Serialize kernel objects into the stock-page causal-chain view model."""

from __future__ import annotations

from typing import Any, Iterable

from .causal import CausalImpact, MarketConfirmation
from .change import ChangeSnapshot, NO_MATERIAL_CHANGE
from .expectation import ExpectationGap
from .thesis import Driver, ThesisSnapshot
from .types import FactRef
from .what_changed import NO_MATERIAL_CHANGE_THESIS, WhatChanged


CHAIN_STEPS = (
    ("what_changed", "What Changed", "事实发生了什么变化"),
    ("expectation", "Expectation Change", "相对预期如何变化"),
    ("confirmation", "Market Confirmation", "市场是否确认"),
    ("transmission", "Transmission", "通过什么机制传导、该股票有什么暴露"),
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
    }


def gap_view(gap: ExpectationGap) -> dict[str, Any]:
    refs = [ref_view(ref) for ref in gap.fact_refs]
    primary = refs[0] if refs else None
    return {
        "id": gap.id,
        "metric": gap.metric,
        "fiscal_period": gap.fiscal_period,
        "current": gap.actual,
        "previous": gap.latest_consensus,
        "delta": gap.surprise_pct,
        "delta_pct": gap.surprise_pct,
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
        "as_of": gap.actual_as_of or gap.latest_consensus_as_of,
        "previous_as_of": gap.latest_consensus_as_of,
        "source": primary["source"] if primary else None,
        "ref": primary,
        "refs": refs,
        "counter": None if gap.status == "ok" else gap.reason,
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
) -> dict[str, Any]:
    change_rows = [change_view(row) for row in changes]
    gap_rows = [gap_view(row) for row in expectations]
    impact_rows = [impact_view(row) for row in impacts]
    confirm = confirmation_view(confirmation)
    report = what_changed_view(what_changed)
    clues = list(clues or ())

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
            expect_status = next(iter(statuses))
        expect_empty = None
    else:
        expect_status = "insufficient"
        expect_empty = next(
            (row["text"] for row in data_gaps if row.get("code") in {"missing_prior_consensus", "missing_latest_consensus"}),
            "数据不足：缺失前次一致预期",
        )

    if impact_rows:
        trans_status = impact_rows[0]["status"]
        trans_empty = None
    else:
        trans_status = "insufficient"
        trans_empty = next(
            (row["text"] for row in data_gaps if row.get("code") == "missing_mechanism"),
            "缺传导机制或 exposure，宏观不能直接跳到个股",
        )

    if report["thesis_changed"]:
        impact_status = thesis.status if thesis.status != "ok" else "ok"
    elif report["summary"] == NO_MATERIAL_CHANGE_THESIS:
        impact_status = "immaterial"
    else:
        impact_status = thesis.status

    chain = [
        _step("what_changed", changed_status, change_rows, empty_reason=changed_empty),
        _step("expectation", expect_status, gap_rows, empty_reason=expect_empty),
        _step(
            "confirmation",
            confirm["status"],
            confirm["used"] or confirm["series"],
            empty_reason=None if (confirm["used"] or confirm["series"] or clues) else confirm["reason"],
            extra={"confirmation": confirm, "clues": clues},
        ),
        _step("transmission", trans_status, impact_rows, empty_reason=trans_empty),
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
            },
        ),
    ]

    blocking = [row for row in data_gaps if row.get("code") == "clock_insufficient"]
    cannot = clock_status == "clock_insufficient" or (
        thesis.status == "incomplete" and report["summary"] != NO_MATERIAL_CHANGE_THESIS
    )
    reason = None
    if cannot:
        reason = (blocking[0]["text"] if blocking else None) or thesis.reason or "现有证据不足以形成有效判断"
    return {
        "symbol": symbol,
        "as_of": None if clock_status == "clock_insufficient" else as_of,
        "clock_status": clock_status,
        "cannot_form_judgment": cannot,
        "cannot_form_judgment_reason": reason,
        "evidence_quality": thesis.evidence_quality,
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
        "no_material_change": report["summary"] == NO_MATERIAL_CHANGE_THESIS,
    }
