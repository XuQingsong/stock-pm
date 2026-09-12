"""Assemble a decision-chain view from existing DB rows. No new sources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .causal import (
    CHANNEL_DURATION,
    RATE_PATH_EXPECTATION_METRICS,
    RATES_DISCOUNT_MECHANISM,
    ClaimSource,
    Exposure,
    MarketConfirmation,
    assess_market_confirmation,
    build_causal_impact,
    canonical_metric,
    mechanism_requires_expectation,
)
from .clock import classify_macros, dataset_as_of
from .change import ChangeSnapshot, build_change_snapshot
from .expectation import ExpectationGap, ExpectationPoint, build_expectation_gap
from .facts import FactValidationError, ValidatedFact, require_valid_bar
from .tension import PriceExpectationTension, build_price_expectation_tension
from .thesis import Driver, ThesisSnapshot, build_thesis_snapshot
from .types import PRICE_METRICS, FactRef, MaterialityRule
from .grading import GAP_EFFECTS, annotate_gaps, grade_decision, _is_symbol_price
from .path import build_rates_path, build_risk_state, split_display_facts
from .viewmodel import render_decision_view
from .what_changed import build_what_changed
from stock_pm.config import DEFAULT_WATCHLIST
from stock_pm.nfp import NFP_FORMULA


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


def _gap(code: str, text: str, *, affects_chain: str | None = None, affects_stage: str | None = None) -> dict[str, str]:
    meta = GAP_EFFECTS.get(code, {})
    return {
        "code": code,
        "text": text,
        "affects_chain": affects_chain or meta.get("chain") or "page",
        "affects_stage": affects_stage or meta.get("stage") or "unspecified",
    }


def _macro_coverage_gaps(
    macro_changes: list[ChangeSnapshot],
    stale_events: Iterable[dict[str, Any]],
    mismatch_events: Iterable[dict[str, Any]],
    scheduled_events: Iterable[dict[str, Any]] = (),
) -> list[dict[str, str]]:
    in_metrics = {canonical_metric(row.metric) for row in macro_changes}
    stale_metrics = {canonical_metric(str(event.get("event_type") or "")) for event in stale_events}
    mismatch_metrics = {
        canonical_metric(str(event.get("event_type") or "")) for event in mismatch_events
    }
    scheduled_metrics = {
        canonical_metric(str(event.get("event_type") or "")) for event in scheduled_events
    }

    gaps: list[dict[str, str]] = []
    if not (in_metrics & set(INFLATION_TYPES)):
        if stale_metrics & set(INFLATION_TYPES):
            gaps.append(
                _gap(
                    "stale_dataset",
                    "CPI/PCE 原因序列存在于决策窗口之前，不是数据缺失",
                    affects_chain="macro_rates",
                    affects_stage="what_changed",
                )
            )
        elif scheduled_metrics & set(INFLATION_TYPES):
            pass
        elif mismatch_metrics & set(INFLATION_TYPES):
            gaps.append(
                _gap(
                    "window_mismatch",
                    "CPI/PCE 原因序列存在但落在决策窗口之外，不是数据缺失",
                    affects_chain="macro_rates",
                    affects_stage="what_changed",
                )
            )
        else:
            gaps.append(_gap("missing_cpi", "缺失 CPI/PCE 原因序列"))
    rate_keys = {"us2y", "real_rate", "cut_odds"}
    if in_metrics & rate_keys:
        pass
    elif stale_metrics & rate_keys:
        gaps.append(_gap("stale_dataset", "利率确认通道存在于决策窗口之前，不是数据缺失", affects_chain="macro_rates", affects_stage="confirmation"))
    elif scheduled_metrics & rate_keys:
        pass
    elif mismatch_metrics & rate_keys:
        gaps.append(_gap("window_mismatch", "利率确认通道存在但落在决策窗口之外，不是数据缺失", affects_chain="macro_rates", affects_stage="confirmation"))
    else:
        gaps.append(_gap("missing_rates_confirmation", "缺失利率确认通道（US2Y/实际利率/降息预期）"))
    if "vix" not in in_metrics:
        if "vix" in stale_metrics:
            gaps.append(_gap("stale_dataset", "VIX 存在于决策窗口之前，不是数据缺失", affects_chain="risk_sentiment", affects_stage="confirmation"))
        elif "vix" in scheduled_metrics:
            pass
        elif "vix" in mismatch_metrics:
            gaps.append(_gap("window_mismatch", "VIX 存在但落在决策窗口之外，不是数据缺失", affects_chain="risk_sentiment", affects_stage="confirmation"))
        else:
            gaps.append(_gap("missing_vix", "缺失 VIX"))
    return gaps


def _scheduled_gaps(scheduled: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    rows = list(scheduled)
    if not rows:
        return []
    names = sorted({str(row.get("event_type") or row.get("name") or "event") for row in rows})
    return [_gap("not_observed", f"未来日程 {', '.join(names)} 尚未被观察，不能当作已发生事实")]


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


def _make_ref(
    table: str,
    ref_id: Any,
    as_of: str,
    source: str,
    *,
    synthetic: bool,
    http_source: str | None = None,
    unit: str | None = None,
    status: str | None = None,
    origin: str | None = None,
) -> FactRef | None:
    try:
        return FactRef(
            ref_table=table,
            ref_id=ref_id,
            as_of=as_of,
            source=source,
            synthetic=synthetic,
            http_source=http_source,
            unit=unit,
            status=status,
            origin=origin,
        )
    except FactValidationError:
        return None


def _validated_bar(symbol: str, row: dict[str, Any], *, synthetic: bool):
    as_of = iso_stamp(row.get("bar_time") or row.get("as_of") or row.get("source_as_of"))
    source = str(row.get("source") or "").strip()
    if not source or not as_of:
        return None, _gap("missing_price_source", "价格事实缺少 source/as_of，不能进入判断")
    ref = _make_ref("daily_price_bars", f"{symbol}|{as_of}", as_of, source, synthetic=synthetic)
    if ref is None:
        return None, _gap("invalid_price_ref", "价格 FactRef 不完整，不能进入判断")
    try:
        bar = require_valid_bar(
            {
                "open": row.get("open_price") or row.get("open"),
                "high": row.get("high_price") or row.get("high"),
                "low": row.get("low_price") or row.get("low"),
                "close": row.get("close_price") or row.get("close"),
                "volume": row.get("volume"),
                "as_of": as_of,
                "symbol": symbol,
                "synthetic": synthetic,
            },
            refs=(ref,),
        )
    except (FactValidationError, TypeError):
        return None, _gap("invalid_ohlc", "价格 OHLC 未通过事实校验，不能进入 Change")
    return (bar, as_of, source, ref), None


def _exclude_price_changes_if_invalid_ohlc(
    changes: Iterable[ChangeSnapshot],
    gaps: Iterable[dict[str, Any]],
) -> list[ChangeSnapshot]:
    rows = list(changes)
    if not any(item.get("code") == "invalid_ohlc" for item in gaps):
        return rows
    return [row for row in rows if not _is_symbol_price(row)]


def _price_changes(symbol: str, bars: list[dict[str, Any]], *, synthetic: bool) -> tuple[list[ChangeSnapshot], list[dict[str, str]], list[dict[str, Any]]]:
    changes: list[ChangeSnapshot] = []
    gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []
    valid: list[tuple[Any, str, str, Any]] = []
    seen_codes: set[str] = set()
    for row in bars:
        parsed, gap = _validated_bar(symbol, row, synthetic=synthetic)
        if parsed is None:
            if gap and gap["code"] not in seen_codes:
                seen_codes.add(gap["code"])
                gaps.append(gap)
            continue
        valid.append(parsed)
    if any(row["code"] == "invalid_ohlc" for row in gaps):
        return [], gaps, []
    if len(valid) < 2:
        if "missing_price_baseline" not in seen_codes:
            gaps.append(_gap("missing_price_baseline", "数据不足：缺失可比价格序列"))
        return changes, gaps, facts
    current_bar, current_as_of, current_source, current_ref = valid[0]
    previous_bar, _previous_as_of, _previous_source, _previous_ref = valid[1]
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
            "id": f"fact|close|{symbol}|{current_as_of}",
            "kind": "bar",
            "metric": "close",
            "subject": symbol,
            "as_of": current_as_of,
            "source": current_source,
            "value": current_bar.price_for("close") if hasattr(current_bar, "price_for") else None,
            "unit": "USD",
            "status": "ok",
            "origin": "primary",
            "http_source": bars[0].get("http_source") if bars else None,
            "ref": {
                "ref_table": "daily_price_bars",
                "ref_id": f"{symbol}|{current_as_of}",
                "as_of": current_as_of,
                "source": current_source,
                "http_source": bars[0].get("http_source") if bars else None,
                "unit": "USD",
                "status": "ok",
                "origin": "primary",
            },
        }
    )
    return changes, gaps, facts


def _macro_fact_payload(
    *,
    metric: str,
    as_of: str,
    source: str,
    current: Any,
    previous: Any,
    unit: str | None,
    series: str,
    formula: str,
    event: dict[str, Any],
    http_source: Any,
    status: str = "ok",
    delta: float | None = None,
) -> dict[str, Any]:
    prior_as_of = iso_stamp(event.get("prior_as_of") or event.get("prior_period"))
    return {
        "id": f"fact|{metric}|{as_of}",
        "kind": "macro",
        "metric": metric,
        "as_of": as_of,
        "source": source,
        "name": event.get("name"),
        "value": current,
        "previous": previous,
        "delta": delta,
        "unit": unit,
        "series": series or None,
        "period": as_of[:10],
        "previous_period": str(prior_as_of)[:10] if prior_as_of else None,
        "formula": formula or None,
        "comparison": event.get("comparison"),
        "status": status,
        "origin": "primary",
        "http_source": http_source,
        "transport": event.get("transport"),
        "ref": {
            "ref_table": "macro_events",
            "ref_id": f"{metric}|{as_of}",
            "as_of": as_of,
            "source": source,
            "http_source": http_source,
            "unit": unit,
            "status": status,
            "origin": "primary",
        },
    }


def _leftover_macro_facts(
    events: Iterable[dict[str, Any]],
    already: set[str],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for event in events:
        metric = canonical_metric(str(event.get("event_type") or ""))
        if not metric or metric in already:
            continue
        as_of = iso_stamp(event.get("event_time"))
        source = str(event.get("source") or "").strip()
        if not as_of or not source:
            continue
        current = event.get("actual")
        if current is None:
            current = event.get("value")
        facts.append(
            _macro_fact_payload(
                metric=metric,
                as_of=as_of,
                source=source,
                current=current,
                previous=event.get("prior"),
                unit=str(event.get("unit") or "") or None,
                series=str(event.get("series_or_symbol") or event.get("series") or ""),
                formula=str(event.get("formula") or ""),
                event=event,
                http_source=event.get("http_source"),
                status=str(event.get("status") or "ok"),
            )
        )
    return facts


def _inject_gaps(tokens: Iterable[str]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    wanted = {str(item).strip().lower() for item in tokens}
    if "missing_gold" in wanted:
        gaps.append(_gap("missing_gold", "注入：黄金缺失，只影响商品链，不撤销价格/利率/盈利结论"))
    if "missing_nfp" in wanted:
        gaps.append(_gap("missing_nfp", "注入：NFP 缺失，只影响劳动链，不撤销全部股票结论"))
    if "missing_prior_consensus" in wanted:
        gaps.append(_gap("missing_prior_consensus", "注入：前次盈利共识缺失，只限制盈利预期链"))
    if "missing_news" in wanted:
        gaps.append(_gap("missing_news", "注入：新闻缺失，只影响新闻线索，不改变已成立事实链"))
    if "missing_options" in wanted:
        gaps.append(_gap("missing_options", "注入：期权缺失，只影响期权层，不撤销宏观/价格结论"))
    return gaps


def _watch_from_seed(symbol: str, watch: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(watch or {})
    seed = DEFAULT_WATCHLIST.get(symbol.upper())
    if seed is not None:
        row.setdefault("themes", list(seed.themes))
        row.setdefault("rate_sensitivity", seed.rate_sensitivity)
    return row


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
        try:
            current_n = float(current)
            previous_n = float(previous)
        except (TypeError, ValueError):
            continue
        unit = str(event.get("unit") or "") or None
        series = str(event.get("series_or_symbol") or event.get("series") or "")
        formula = str(event.get("formula") or "") or (NFP_FORMULA if metric == "nfp" else "")
        http_source = event.get("http_source")
        if metric == "nfp" and abs(previous_n) >= 10000 and abs(current_n) < 5000:
            gaps.append(
                _gap(
                    "nfp_unit_mismatch",
                    "NFP 只能比较同口径月度差分，禁止用 就业存量 当 prior",
                    affects_chain="labor",
                    affects_stage="what_changed",
                )
            )
            facts.append(
                _macro_fact_payload(
                    metric=metric,
                    as_of=as_of,
                    source=source,
                    current=current_n,
                    previous=None,
                    unit=unit,
                    series=series,
                    formula=formula or NFP_FORMULA,
                    event=event,
                    http_source=http_source,
                    status="nfp_unit_mismatch",
                )
            )
            continue
        prior_as_of = iso_stamp(event.get("prior_as_of") or event.get("prior_period")) or as_of
        ref = _make_ref(
            "macro_events",
            f"{metric}|{as_of}",
            as_of,
            source,
            synthetic=synthetic,
            http_source=http_source,
            unit=unit,
            status=str(event.get("status") or "ok"),
            origin="primary",
        )
        if ref is None:
            continue
        try:
            current_fact = ValidatedFact(
                metric=metric,
                value=current_n,
                as_of=as_of,
                unit=unit,
                refs=(ref,),
                synthetic=synthetic,
            )
            previous_fact = ValidatedFact(
                metric=metric,
                value=previous_n,
                as_of=prior_as_of,
                unit=unit,
                refs=(ref,),
                synthetic=synthetic,
            )
        except (FactValidationError, TypeError, ValueError):
            continue
        change = build_change_snapshot(
            metric=metric,
            current_fact=current_fact,
            previous_fact=previous_fact,
            comparison_window="event",
            materiality_rule=rule,
            unit=unit,
            synthetic=synthetic,
        )
        changes.append(change)
        facts.append(
            _macro_fact_payload(
                metric=metric,
                as_of=as_of,
                source=source,
                current=current_n,
                previous=previous_n,
                unit=unit,
                series=series,
                formula=formula,
                event=event,
                http_source=http_source,
                status=str(event.get("status") or "ok"),
                delta=change.delta,
            )
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
            "id": f"fact|eps|{symbol}|{actual_as_of}",
            "kind": "earnings",
            "metric": "eps",
            "subject": symbol,
            "as_of": actual_as_of,
            "source": source,
            "value": float(actual),
            "unit": "USD/share",
            "status": "ok",
            "origin": "primary",
            "fiscal_period": period,
            "http_source": row.get("http_source"),
            "ref": {
                "ref_table": "earnings_reports",
                "ref_id": f"{symbol}|{period}|actual",
                "as_of": actual_as_of,
                "source": source,
                "http_source": row.get("http_source"),
                "unit": "USD/share",
                "status": "ok",
                "origin": "primary",
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


def ok_rate_path_expectation(expectations: Iterable[ExpectationGap]) -> ExpectationGap | None:
    for gap in expectations:
        if gap.status == "ok" and canonical_metric(gap.metric) in RATE_PATH_EXPECTATION_METRICS:
            return gap
    return None


def _symbol_price_change(changes: Iterable[ChangeSnapshot]) -> ChangeSnapshot | None:
    for change in changes:
        if change.metric in PRICE_METRICS and change.scope == "symbol":
            return change
    return None


def resolve_price_expectation_tension(
    changes: Iterable[ChangeSnapshot],
    expectations: Iterable[ExpectationGap],
    *,
    synthetic: bool,
) -> PriceExpectationTension:
    price = _symbol_price_change(changes)
    fund: ExpectationGap | ChangeSnapshot | None = ok_rate_path_expectation(expectations)
    if fund is None:
        fund = next((gap for gap in expectations if gap.status == "ok"), None)
    return build_price_expectation_tension(
        fundamentals_change=fund,
        price_change=price,
        synthetic=synthetic,
    )


def rates_chain_incomplete(
    impacts: Iterable[Any],
    expectations: Iterable[ExpectationGap],
    tension: PriceExpectationTension | None,
) -> bool:
    has_valid_rates = any(
        mechanism_requires_expectation(getattr(impact, "mechanism", None))
        and getattr(impact, "status", None) == "valid"
        for impact in impacts
    )
    if not has_valid_rates:
        return False
    if ok_rate_path_expectation(expectations) is None:
        return True
    if tension is None or tension.tension == "insufficient" or tension.evidence_quality == "insufficient":
        return True
    return False


def directional_impacts(
    impacts: Iterable[Any],
    *,
    blocked: bool,
) -> list[Any]:
    rows = list(impacts)
    if not blocked:
        return rows
    return [
        impact
        for impact in rows
        if not (
            mechanism_requires_expectation(getattr(impact, "mechanism", None))
            and getattr(impact, "status", None) == "valid"
        )
    ]


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
    clock_status: str = "ok",
    rates_path: dict[str, Any] | None = None,
    risk_state: dict[str, Any] | None = None,
    market_background: list[dict[str, Any]] | None = None,
    inject: list[str] | None = None,
) -> dict[str, Any]:
    changes = _exclude_price_changes_if_invalid_ohlc(changes, data_gaps)
    seed_watch = _watch_from_seed(symbol, None)
    if rates_path is None:
        rates_path = build_rates_path(
            symbol=symbol,
            watch=seed_watch,
            changes=changes,
            confirmation=confirmation,
            facts=facts,
        )
    if risk_state is None:
        risk_state = build_risk_state(changes)
    if not market_background:
        _main_facts, market_background = split_display_facts(facts, changes, seed_watch, symbol)
        if _main_facts:
            facts = _main_facts
    tension = resolve_price_expectation_tension(changes, expectations, synthetic=synthetic)
    blocked = rates_chain_incomplete(impacts, expectations, tension)
    gaps = list(data_gaps)
    if blocked:
        if not any(row.get("code") == "rates_chain_incomplete" for row in gaps):
            gaps.append(
                _gap(
                    "rates_chain_incomplete",
                    "通胀→利率机制缺少可追溯预期或价格/预期张力，不能形成方向性判断，市场确认不能代替这两层",
                )
            )
        if ok_rate_path_expectation(expectations) is None and not any(
            row.get("code") == "missing_rate_path_expectation" for row in gaps
        ):
            gaps.append(
                _gap(
                    "missing_rate_path_expectation",
                    "利率路径/降息概率缺少可追溯的 current vs prior（含 as_of 与 source），不能形成有效方向",
                )
            )
        thesis_impacts = directional_impacts(impacts, blocked=True)
        bulls, bears, disagreement, invalidation = _drivers(symbol, changes, expectations, thesis_impacts)
        thesis = build_thesis_snapshot(
            bull_drivers=bulls,
            bear_drivers=bears,
            key_disagreement=disagreement,
            invalidation=invalidation,
            changes=changes,
            expectations=expectations,
            impacts=thesis_impacts,
            generated_at=thesis.generated_at,
            symbol=symbol,
            synthetic=synthetic,
        )
        report_impacts = thesis_impacts
    else:
        report_impacts = impacts
    report = build_what_changed(
        changes=changes,
        expectations=expectations,
        impacts=report_impacts,
        previous_thesis=previous_thesis,
        current_thesis=thesis,
        synthetic=synthetic,
    )
    compared = {
        "as_of": previous_thesis.generated_at if previous_thesis else None,
        "changed_fields": list(report.changed_fields),
        "thesis_changed": report.thesis_changed,
    }
    gaps = annotate_gaps(gaps)
    graded = grade_decision(
        symbol=symbol,
        changes=changes,
        expectations=expectations,
        confirmation=confirmation,
        tension=tension,
        impacts=impacts,
        data_gaps=gaps,
        clues=clues,
        clock_status=clock_status,
    )
    return render_decision_view(
        symbol=symbol,
        changes=changes,
        expectations=expectations,
        confirmation=confirmation,
        impacts=impacts,
        thesis=thesis,
        what_changed=report,
        data_gaps=graded["gaps"],
        facts=facts,
        clues=clues,
        synthetic=synthetic,
        preview=preview,
        as_of=as_of,
        compared_to=compared,
        clock_status=clock_status,
        tension=tension,
        rates_chain_blocked=blocked,
        graded=graded,
        rates_path=rates_path,
        risk_state=risk_state,
        market_background=market_background or [],
        inject=inject or [],
    )


def assemble_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    symbol = _watch_symbol(bundle)
    synthetic = bool(bundle.get("synthetic"))
    watch = _watch_from_seed(symbol, bundle.get("watch") or {})
    data_gaps: list[dict[str, str]] = []
    facts: list[dict[str, Any]] = []

    price_changes, price_gaps, price_facts = _price_changes(symbol, list(bundle.get("bars") or []), synthetic=synthetic)
    data_gaps.extend(price_gaps)
    facts.extend(price_facts)

    collected_macros: list[dict[str, Any]] = []
    for key in (
        "macro_events",
        "macro_events_stale",
        "macro_events_window_mismatch",
        "macro_events_scheduled",
        "macro_events_out_of_window",
    ):
        collected_macros.extend(list(bundle.get(key) or ()))
    clock = dataset_as_of(
        bars=list(bundle.get("bars") or []),
        earnings=list(bundle.get("earnings") or []),
        macros=collected_macros,
    )
    clock_status = "ok" if clock is not None else "clock_insufficient"
    if clock is None:
        data_gaps.append(_gap("clock_insufficient", "无可靠观察时间，不能猜测今天或用未来事件日代替，目前不能形成判断"))
    parts = classify_macros(collected_macros, clock)
    macro_changes, macro_gaps, macro_facts = _macro_changes(parts.inside, synthetic=synthetic)
    data_gaps.extend(macro_gaps)
    facts.extend(macro_facts)
    already = {canonical_metric(str(row.get("metric") or "")) for row in macro_facts}
    facts.extend(_leftover_macro_facts(parts.inside, already))
    data_gaps.extend(_scheduled_gaps(parts.scheduled))
    data_gaps.extend(_inject_gaps(list(bundle.get("inject") or [])))

    expect_rows, expect_gaps, expect_facts = _expectation_gaps(symbol, list(bundle.get("earnings") or []), synthetic=synthetic)
    data_gaps.extend(expect_gaps)
    facts.extend(expect_facts)

    data_gaps.extend(_macro_coverage_gaps(macro_changes, parts.stale, parts.mismatch, parts.scheduled))

    confirm_series = [row for row in macro_changes if canonical_metric(row.metric) in {"us2y", "real_rate", "cut_odds"}]
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=tuple(confirm_series),
        synthetic=synthetic,
    )

    exposure = _exposure(watch, symbol)
    inflation_causes = [row for row in macro_changes if canonical_metric(row.metric) in INFLATION_TYPES]
    material_inflation = [row for row in inflation_causes if row.materiality == "material"]
    impacts = []
    cause = (material_inflation or inflation_causes or [None])[0]
    if cause is not None and exposure is not None:
        impacts.append(
            build_causal_impact(
                cause=cause,
                mechanism=RATES_DISCOUNT_MECHANISM,
                exposure=exposure,
                market_confirmation=confirmation,
                synthetic=synthetic,
            )
        )
    elif exposure is not None and not inflation_causes:
        data_gaps.append(_gap("missing_mechanism", "缺通胀原因，不能把非农或新闻直接跳到个股"))
    elif exposure is None:
        data_gaps.append(_gap("missing_exposure", "该标的没有利率久期暴露，不把宏观直接写成个股方向"))

    clues = _unverified_clues(list(bundle.get("news") or []))
    for event in parts.scheduled:
        clues.append(
            {
                "status": "not_observed",
                "headline": event.get("name") or event.get("event_type"),
                "source": event.get("source"),
                "as_of": iso_stamp(event.get("event_time")),
                "why": "未来日程 / 尚未观察，不能当作已发生事实",
                "ref": {
                    "ref_table": "macro_events",
                    "ref_id": f"{event.get('event_type')}|{event.get('event_time')}",
                    "as_of": iso_stamp(event.get("event_time")),
                    "source": event.get("source"),
                },
            }
        )
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
    main_facts, background_facts = split_display_facts(facts, changes, watch, symbol)
    rates_path = build_rates_path(
        symbol=symbol,
        watch=watch,
        changes=changes,
        confirmation=confirmation,
        facts=facts,
    )
    risk_state = build_risk_state(changes)
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

    as_of = clock.isoformat() if clock is not None else None
    if as_of is None and price_changes:
        as_of = price_changes[0].current_as_of
    seen: set[tuple[str, str]] = set()
    unique_gaps: list[dict[str, str]] = []
    for row in data_gaps:
        key = (str(row.get("code") or ""), str(row.get("affects_chain") or ""))
        if key in seen:
            continue
        seen.add(key)
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
        facts=main_facts,
        clues=clues,
        synthetic=synthetic,
        as_of=as_of,
        clock_status=clock_status,
        rates_path=rates_path,
        risk_state=risk_state,
        market_background=background_facts,
        inject=list(bundle.get("inject") or []),
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
