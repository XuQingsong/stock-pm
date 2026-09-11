"""Assemble a decision-chain view from existing DB rows. No new sources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .causal import (
    CHANNEL_DURATION,
    RATES_DISCOUNT_MECHANISM,
    ClaimSource,
    Exposure,
    MarketConfirmation,
    assess_market_confirmation,
    build_causal_impact,
    canonical_metric,
)
from .change import ChangeSnapshot, build_change_snapshot
from .expectation import ExpectationGap, ExpectationPoint, build_expectation_gap
from .facts import FactValidationError, ValidatedFact, require_valid_bar
from .thesis import Driver, ThesisSnapshot, build_thesis_snapshot
from .types import FactRef, MaterialityRule
from .viewmodel import render_decision_view
from .what_changed import build_what_changed


PRICE_RULE = MaterialityRule(pct_delta=2.0)
CPI_RULE = MaterialityRule(abs_delta=0.20)
NFP_RULE = MaterialityRule(abs_delta=50.0)
YIELD_RULE = MaterialityRule(abs_delta=0.05)
ODDS_RULE = MaterialityRule(abs_delta=5.0)
VIX_RULE = MaterialityRule(abs_delta=1.0)
EPS_RULE = MaterialityRule(abs_delta=0.05)

UNVERIFIED_HINTS = (
    "war",
    "sanction",
    "rumor",
    "unverified",
    "战争",
    "制裁",
    "传闻",
    "未核实",
)

MACRO_RULES = {
    "cpi": CPI_RULE,
    "core_cpi": CPI_RULE,
    "pce": CPI_RULE,
    "core_pce": CPI_RULE,
    "inflation": CPI_RULE,
    "nfp": NFP_RULE,
    "us2y": YIELD_RULE,
    "real_rate": YIELD_RULE,
    "cut_odds": ODDS_RULE,
    "vix": VIX_RULE,
}

INFLATION_TYPES = frozenset({"cpi", "core_cpi", "pce", "core_pce", "inflation"})
CONFIRM_TYPES = frozenset({"us2y", "real_rate", "cut_odds", "vix"})


def iso_stamp(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _gap(code: str, text: str) -> dict[str, str]:
    return {"code": code, "text": text}


def _watch_symbol(bundle: dict[str, Any]) -> str:
    watch = bundle.get("watch") or {}
    return str(bundle.get("symbol") or watch.get("symbol") or "").upper()


def _exposure(watch: dict[str, Any] | None, symbol: str) -> Exposure | None:
    row = watch or {}
    themes = [str(item) for item in (row.get("themes") or [])]
    rate = str(row.get("rate_sensitivity") or "medium")
    if rate == "high" or "high_valuation_growth" in themes:
        return Exposure(
            target=symbol,
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        )
    return None


def _make_ref(table: str, ref_id: Any, as_of: str, source: str, *, synthetic: bool) -> FactRef | None:
    try:
        return FactRef(
            ref_table=table,
            ref_id=ref_id,
            as_of=as_of,
            source=source,
            synthetic=synthetic,
        )
    except FactValidationError:
        return None


def _price_changes(symbol: str, bars: list[dict[str, Any]], *, synthetic: bool) -> tuple[list[ChangeSnapshot], list[dict[str, str]], list[dict[str, Any]]]:
    changes: list[ChangeSnapshot] = []
    gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []
    if len(bars) < 2:
        gaps.append(_gap("missing_price_baseline", "数据不足：缺失可比价格序列"))
        return changes, gaps, facts
    current_row, previous_row = bars[0], bars[1]
    current_as_of = iso_stamp(current_row.get("bar_time") or current_row.get("as_of"))
    previous_as_of = iso_stamp(previous_row.get("bar_time") or previous_row.get("as_of"))
    current_source = str(current_row.get("source") or "").strip()
    previous_source = str(previous_row.get("source") or "").strip()
    if not current_source or not previous_source or not current_as_of or not previous_as_of:
        gaps.append(_gap("missing_price_source", "价格事实缺少 source/as_of，不能进入判断"))
        return changes, gaps, facts
    current_ref = _make_ref("daily_price_bars", f"{symbol}|{current_as_of}", current_as_of, current_source, synthetic=synthetic)
    previous_ref = _make_ref("daily_price_bars", f"{symbol}|{previous_as_of}", previous_as_of, previous_source, synthetic=synthetic)
    if current_ref is None or previous_ref is None:
        gaps.append(_gap("invalid_price_ref", "价格 FactRef 不完整，不能进入判断"))
        return changes, gaps, facts
    try:
        current_bar = require_valid_bar(
            {
                "open": current_row.get("open_price") or current_row.get("open"),
                "high": current_row.get("high_price") or current_row.get("high"),
                "low": current_row.get("low_price") or current_row.get("low"),
                "close": current_row.get("close_price") or current_row.get("close"),
                "volume": current_row.get("volume"),
                "as_of": current_as_of,
                "symbol": symbol,
                "synthetic": synthetic,
            },
            refs=(current_ref,),
        )
        previous_bar = require_valid_bar(
            {
                "open": previous_row.get("open_price") or previous_row.get("open"),
                "high": previous_row.get("high_price") or previous_row.get("high"),
                "low": previous_row.get("low_price") or previous_row.get("low"),
                "close": previous_row.get("close_price") or previous_row.get("close"),
                "volume": previous_row.get("volume"),
                "as_of": previous_as_of,
                "symbol": symbol,
                "synthetic": synthetic,
            },
            refs=(previous_ref,),
        )
    except (FactValidationError, TypeError):
        gaps.append(_gap("invalid_ohlc", "价格 OHLC 未通过事实校验，不能进入 Change"))
        return changes, gaps, facts
    change = build_change_snapshot(
        metric="close",
        current_bar=current_bar,
        previous_bar=previous_bar,
        comparison_window="1d",
        materiality_rule=PRICE_RULE,
        synthetic=synthetic,
    )
    changes.append(change)
    facts.append(
        {
            "kind": "bar",
            "metric": "close",
            "subject": symbol,
            "as_of": current_as_of,
            "source": current_source,
            "ref": {
                "ref_table": "daily_price_bars",
                "ref_id": f"{symbol}|{current_as_of}",
                "as_of": current_as_of,
                "source": current_source,
            },
        }
    )
    return changes, gaps, facts


def _macro_changes(events: Iterable[dict[str, Any]], *, synthetic: bool) -> tuple[list[ChangeSnapshot], list[dict[str, str]], list[dict[str, Any]]]:
    changes: list[ChangeSnapshot] = []
    gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []
    for event in events:
        metric = canonical_metric(str(event.get("event_type") or ""))
        rule = MACRO_RULES.get(metric)
        if rule is None:
            continue
        as_of = iso_stamp(event.get("event_time"))
        source = str(event.get("source") or "").strip()
        if not as_of or not source:
            continue
        current = event.get("actual")
        previous = event.get("prior")
        if current is None or previous is None:
            gaps.append(_gap("missing_macro_baseline", f"{metric} 缺 actual/prior，不能声称变化"))
            continue
        ref = _make_ref("macro_events", f"{metric}|{as_of}", as_of, source, synthetic=synthetic)
        if ref is None:
            continue
        try:
            current_fact = ValidatedFact(
                metric=metric,
                value=float(current),
                as_of=as_of,
                refs=(ref,),
                synthetic=synthetic,
            )
            previous_fact = ValidatedFact(
                metric=metric,
                value=float(previous),
                as_of=as_of,
                refs=(ref,),
                synthetic=synthetic,
            )
        except (FactValidationError, TypeError, ValueError):
            continue
        changes.append(
            build_change_snapshot(
                metric=metric,
                current_fact=current_fact,
                previous_fact=previous_fact,
                comparison_window="event",
                materiality_rule=rule,
                synthetic=synthetic,
            )
        )
        facts.append(
            {
                "kind": "macro",
                "metric": metric,
                "as_of": as_of,
                "source": source,
                "name": event.get("name"),
                "ref": {"ref_table": "macro_events", "ref_id": f"{metric}|{as_of}", "as_of": as_of, "source": source},
            }
        )
    return changes, gaps, facts


def _expectation_gaps(symbol: str, earnings: list[dict[str, Any]], *, synthetic: bool) -> tuple[list[ExpectationGap], list[dict[str, str]], list[dict[str, Any]]]:
    gaps_out: list[ExpectationGap] = []
    data_gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []
    if not earnings:
        data_gaps.append(_gap("missing_earnings", "数据不足：缺失财报对照"))
        data_gaps.append(_gap("missing_prior_consensus", "缺失前次一致预期"))
        return gaps_out, data_gaps, facts
    row = earnings[0]
    actual = row.get("eps_actual")
    latest = row.get("eps_estimate")
    period = row.get("fiscal_period")
    actual_as_of = iso_stamp(row.get("report_date"))
    source = str(row.get("source") or "").strip() or "fmp"
    if actual is None or latest is None:
        data_gaps.append(_gap("missing_latest_consensus", "数据不足：缺失最新一致预期或实际值"))
        return gaps_out, data_gaps, facts
    if not actual_as_of:
        data_gaps.append(_gap("missing_earnings_as_of", "财报缺少 as_of，不能比较预期"))
        return gaps_out, data_gaps, facts
    data_gaps.append(_gap("missing_prior_consensus", "缺失前次一致预期"))
    actual_ref = _make_ref("earnings_reports", f"{symbol}|{period}|actual", actual_as_of, source, synthetic=synthetic)
    # Honest: we do not invent a pre-print consensus timestamp. The estimate
    # exists as a number but has no distinct as_of, so the kernel stays insufficient.
    latest_point = ExpectationPoint(
        value=float(latest),
        as_of=None,
        source="street",
        currency="USD",
        basis="gaap",
        fiscal_period=period,
        subject=symbol,
        synthetic=synthetic,
    )
    actual_point = ExpectationPoint(
        value=float(actual),
        as_of=actual_as_of,
        source="company",
        currency="USD",
        basis="gaap",
        fiscal_period=period,
        fact_ref=actual_ref,
        subject=symbol,
        synthetic=synthetic,
    )
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period=period,
        actual=actual_point,
        latest_consensus=latest_point,
        synthetic=synthetic,
    )
    gaps_out.append(gap)
    facts.append(
        {
            "kind": "earnings",
            "metric": "eps",
            "subject": symbol,
            "as_of": actual_as_of,
            "source": source,
            "fiscal_period": period,
            "ref": {
                "ref_table": "earnings_reports",
                "ref_id": f"{symbol}|{period}|actual",
                "as_of": actual_as_of,
                "source": source,
            },
        }
    )
    return gaps_out, data_gaps, facts


def _unverified_clues(news: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    clues: list[dict[str, Any]] = []
    for item in news:
        text = f"{item.get('headline') or ''} {item.get('summary') or ''}".lower()
        if not any(hint in text for hint in UNVERIFIED_HINTS):
            continue
        as_of = iso_stamp(item.get("published_at"))
        clues.append(
            {
                "status": "unverified",
                "headline": item.get("headline"),
                "source": item.get("source"),
                "as_of": as_of,
                "why": "未核实新闻只能作为线索，不改变 Thesis",
                "ref": {
                    "ref_table": "news_articles",
                    "ref_id": item.get("id") or item.get("headline"),
                    "as_of": as_of,
                    "source": item.get("source"),
                },
            }
        )
    return clues


def _drivers(
    symbol: str,
    changes: list[ChangeSnapshot],
    expectations: list[ExpectationGap],
    impacts: list[Any],
) -> tuple[list[Driver], list[Driver], str | None, str | None]:
    bulls: list[Driver] = []
    bears: list[Driver] = []
    for impact in impacts:
        if impact.status != "valid" or not impact.direction:
            continue
        text = " → ".join(impact.chain) if impact.chain else (impact.reason or "因果")
        driver = Driver(text=text, based_on=(impact.id,))
        if impact.direction == "bullish":
            bulls.append(driver)
        elif impact.direction == "bearish":
            bears.append(driver)
    for change in changes:
        if change.materiality != "material" or change.scope != "symbol" or change.subject != symbol:
            continue
        if change.direction == "up":
            bulls.append(Driver(text=f"{change.metric} 上升且达到重要性阈值", based_on=(change.id,)))
        elif change.direction == "down":
            bears.append(Driver(text=f"{change.metric} 下降且达到重要性阈值", based_on=(change.id,)))
    for gap in expectations:
        if gap.status != "ok" or gap.subject != symbol:
            continue
        surprise = gap.surprise_pct or 0
        if surprise > 0:
            bulls.append(Driver(text=f"{gap.metric} 相对最新共识为正", based_on=(gap.id,)))
        elif surprise < 0:
            bears.append(Driver(text=f"{gap.metric} 相对最新共识为负", based_on=(gap.id,)))
    disagreement = None
    invalidation = None
    if bulls and bears:
        disagreement = "现有证据同时存在支持与反方，需看确认路径是否成立"
        invalidation = "若市场确认或公司基本面反向，则当前判断失效"
    return bulls[:3], bears[:3], disagreement, invalidation


def assemble_from_kernel(
    *,
    symbol: str,
    changes: list[ChangeSnapshot],
    expectations: list[ExpectationGap],
    confirmation: MarketConfirmation | None,
    impacts: list[Any],
    thesis: ThesisSnapshot,
    previous_thesis: ThesisSnapshot | None,
    data_gaps: list[dict[str, str]],
    facts: list[dict[str, Any]],
    clues: list[dict[str, Any]] | None = None,
    synthetic: bool = False,
    preview: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    report = build_what_changed(
        changes=changes,
        expectations=expectations,
        impacts=impacts,
        previous_thesis=previous_thesis,
        current_thesis=thesis,
        synthetic=synthetic,
    )
    compared = {
        "as_of": previous_thesis.generated_at if previous_thesis else None,
        "changed_fields": list(report.changed_fields),
        "thesis_changed": report.thesis_changed,
    }
    return render_decision_view(
        symbol=symbol,
        changes=changes,
        expectations=expectations,
        confirmation=confirmation,
        impacts=impacts,
        thesis=thesis,
        what_changed=report,
        data_gaps=data_gaps,
        facts=facts,
        clues=clues,
        synthetic=synthetic,
        preview=preview,
        as_of=as_of,
        compared_to=compared,
    )


def assemble_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    symbol = _watch_symbol(bundle)
    synthetic = bool(bundle.get("synthetic"))
    watch = bundle.get("watch") or {}
    data_gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []

    price_changes, price_gaps, price_facts = _price_changes(symbol, list(bundle.get("bars") or []), synthetic=synthetic)
    data_gaps.extend(price_gaps)
    facts.extend(price_facts)

    macro_changes, macro_gaps, macro_facts = _macro_changes(list(bundle.get("macro_events") or []), synthetic=synthetic)
    data_gaps.extend(macro_gaps)
    facts.extend(macro_facts)

    expect_rows, expect_gaps, expect_facts = _expectation_gaps(symbol, list(bundle.get("earnings") or []), synthetic=synthetic)
    data_gaps.extend(expect_gaps)
    facts.extend(expect_facts)

    if not any(canonical_metric(row.metric) in INFLATION_TYPES for row in macro_changes):
        data_gaps.append(_gap("missing_cpi", "缺失 CPI/PCE 原因序列"))
    confirm_have = {canonical_metric(row.metric) for row in macro_changes if canonical_metric(row.metric) in CONFIRM_TYPES}
    if "us2y" not in confirm_have or "real_rate" not in confirm_have:
        data_gaps.append(_gap("missing_rates_confirmation", "缺失利率确认通道（US2Y/实际利率/降息预期）"))
    if "vix" not in confirm_have:
        data_gaps.append(_gap("missing_vix", "缺失 VIX"))

    confirm_series = [row for row in macro_changes if canonical_metric(row.metric) in CONFIRM_TYPES]
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=tuple(confirm_series),
        synthetic=synthetic,
    )

    exposure = _exposure(watch, symbol)
    inflation_causes = [row for row in macro_changes if canonical_metric(row.metric) in INFLATION_TYPES and row.materiality == "material"]
    impacts = []
    if inflation_causes and exposure is not None:
        impacts.append(
            build_causal_impact(
                cause=inflation_causes[0],
                mechanism=RATES_DISCOUNT_MECHANISM,
                exposure=exposure,
                market_confirmation=confirmation,
                synthetic=synthetic,
            )
        )
    elif exposure is not None:
        data_gaps.append(_gap("missing_mechanism", "缺通胀原因，不能把非农或新闻直接跳到个股"))
        impacts.append(
            build_causal_impact(
                cause=None,
                mechanism=RATES_DISCOUNT_MECHANISM,
                exposure=exposure,
                market_confirmation=confirmation,
                synthetic=synthetic,
            )
        )
    else:
        data_gaps.append(_gap("missing_exposure", "该标的没有利率久期暴露，不把宏观直接写成个股方向"))

    clues = _unverified_clues(list(bundle.get("news") or []))
    if clues:
        data_gaps.append(_gap("unverified_news", "存在未核实新闻，仅作线索，不改变 Thesis"))
        headline = clues[0].get("headline") or "unverified news"
        impacts.append(
            build_causal_impact(
                cause=None,
                mechanism=RATES_DISCOUNT_MECHANISM,
                exposure=exposure,
                market_confirmation=confirmation,
                claim=ClaimSource(source_class="social", verified=False, text=str(headline)),
                synthetic=synthetic,
            )
        )

    changes = price_changes + macro_changes
    bulls, bears, disagreement, invalidation = _drivers(symbol, changes, expect_rows, impacts)
    stamp = iso_stamp(bundle.get("generated_at")) or datetime.now(timezone.utc).isoformat()
    thesis = build_thesis_snapshot(
        bull_drivers=bulls,
        bear_drivers=bears,
        key_disagreement=disagreement,
        invalidation=invalidation,
        changes=changes,
        expectations=expect_rows,
        impacts=impacts,
        generated_at=stamp,
        symbol=symbol,
        synthetic=synthetic,
    )

    as_of = price_changes[0].current_as_of if price_changes else (
        macro_changes[0].current_as_of if macro_changes else stamp
    )
    seen: set[str] = set()
    unique_gaps: list[dict[str, str]] = []
    for row in data_gaps:
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        unique_gaps.append(row)

    previous = None
    prior_bars = list(bundle.get("bars") or [])[1:]
    if not bundle.get("_skip_previous") and len(prior_bars) >= 2:
        nested = dict(bundle)
        nested["bars"] = prior_bars
        nested["_skip_previous"] = True
        nested["generated_at"] = iso_stamp(prior_bars[0].get("bar_time")) or stamp
        previous = _thesis_from_view(assemble_from_bundle(nested), symbol=symbol, synthetic=synthetic)

    return assemble_from_kernel(
        symbol=symbol,
        changes=changes,
        expectations=expect_rows,
        confirmation=confirmation,
        impacts=impacts,
        thesis=thesis,
        previous_thesis=previous,
        data_gaps=unique_gaps,
        facts=facts,
        clues=clues,
        synthetic=synthetic,
        as_of=as_of,
    )


def _thesis_from_view(view: dict[str, Any], *, symbol: str, synthetic: bool) -> ThesisSnapshot:
    thesis = view["thesis"]
    return ThesisSnapshot(
        direction=thesis["direction"],
        bull_drivers=tuple(Driver(text=row["text"], based_on=tuple(row["based_on"])) for row in thesis["bull_drivers"]),
        bear_drivers=tuple(Driver(text=row["text"], based_on=tuple(row["based_on"])) for row in thesis["bear_drivers"]),
        key_disagreement=thesis["key_disagreement"],
        invalidation=thesis["invalidation"],
        evidence_quality=thesis["evidence_quality"],
        based_on_change_ids=tuple(thesis["based_on_change_ids"]),
        based_on_expectation_ids=tuple(thesis["based_on_expectation_ids"]),
        based_on_causal_impact_ids=tuple(thesis["based_on_causal_impact_ids"]),
        generated_at=thesis["generated_at"],
        status=thesis["status"],
        reason=thesis["reason"],
        symbol=symbol,
        code=thesis["code"],
        synthetic=synthetic,
    )
