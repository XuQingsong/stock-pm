"""Read-only data health / coverage. Explains evidence availability, never grades."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from stock_pm.config import Settings

from .causal import canonical_metric
from .clock import (
    EVENT_TIME_FIELDS,
    MACRO_LOOKBACK_DAYS,
    as_date,
    classify_macros,
    dataset_as_of,
    macro_window,
    observation_date,
)
from .facts import ohlc_constraint_errors
from .timeparse import parse_as_of

CHAIN_IDS = ("price", "earnings", "macro_rates", "risk_sentiment")
CHAIN_TITLES = {
    "price": ("Price", "价格"),
    "earnings": ("Earnings", "盈利预期"),
    "macro_rates": ("Macro / Rates", "宏观利率"),
    "risk_sentiment": ("Risk Sentiment", "风险情绪"),
}

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_STALE = "stale"
STATUS_INVALID = "invalid"
STATUS_ERROR = "error"
STATUS_NOT_CONFIGURED = "not_configured"

REASON_SOURCE_NOT_CONFIGURED = "source_not_configured"
REASON_UPSTREAM_EMPTY = "upstream_empty"
REASON_RECORD_STALE = "record_stale"
REASON_RECORD_INVALID = "record_invalid"
REASON_QUERY_ERROR = "query_error"
REASON_WITHIN_THRESHOLD = "within_threshold"
REASON_MISSING_OBSERVATION = "missing_observation"

# Catch-all UI copy is forbidden. Each reason_code maps to a distinct label.
REASON_LABELS = {
    REASON_SOURCE_NOT_CONFIGURED: "源未配置",
    REASON_UPSTREAM_EMPTY: "上游无记录",
    REASON_RECORD_STALE: "记录过旧",
    REASON_RECORD_INVALID: "记录格式非法",
    REASON_QUERY_ERROR: "查询异常",
    REASON_WITHIN_THRESHOLD: "在新鲜度阈值内",
    REASON_MISSING_OBSERVATION: "缺少观察时间",
}

FRESHNESS_DAYS = {
    "close": 7,
    "eps": 120,
    "eps_prior": 120,
    "nfp": 45,
    "cpi": 50,
    "us2y": 14,
    "vix": 7,
}

SECRET_HINTS = ("api_key", "apikey", "secret", "token", "password", "authorization", "traceback")

HEALTH_PREVIEW_LABELS = {
    "HEALTHY": "数据健康·全面可用（合成演示数据）",
    "PARTIAL": "数据健康·部分缺失（合成演示数据）",
    "MISSING": "数据健康·全面缺失（合成演示数据）",
    "STALE": "数据健康·陈旧（合成演示数据）",
    "INVALID": "数据健康·非法记录（合成演示数据）",
    "ERROR": "数据健康·查询异常（合成演示数据）",
}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = parse_as_of(str(value))
    if parsed is None or parsed == "invalid":
        return None
    return parsed.isoformat()


def _first_stamp(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for key in fields:
        if key in EVENT_TIME_FIELDS:
            continue
        if key not in row or row.get(key) is None:
            continue
        stamp = _iso(row.get(key))
        if stamp:
            return stamp
    return None


def _observed_iso(row: dict[str, Any], *, kind: str) -> str | None:
    stamp = observation_date(row, kind=kind)
    return stamp.isoformat() if stamp else None


def _ingested_iso(row: dict[str, Any]) -> str | None:
    return _first_stamp(row, ("ingested_at", "synced_at", "captured_at"))


def _age_days(clock: date | None, observed: str | None) -> int | None:
    if clock is None or not observed:
        return None
    when = as_date(observed)
    if when is None:
        return None
    age = (clock - when).days
    return max(age, 0)


def _source_configured(settings: Settings | None, family: str) -> bool:
    if settings is None:
        settings = Settings()
    if family == "alpaca":
        return bool(settings.alpaca_api_key_id and settings.alpaca_api_secret_key)
    if family == "fred":
        return bool(settings.fred_api_key)
    if family == "fmp":
        return bool(settings.fmp_api_key)
    return True


def _safe_query_reason(exc: BaseException | str | None) -> str:
    if exc is None:
        return "查询失败"
    text = exc if isinstance(exc, str) else type(exc).__name__
    lowered = text.lower()
    if any(hint in lowered for hint in SECRET_HINTS):
        return "查询失败"
    return "查询失败"


def _dataset_row(
    *,
    dataset: str,
    metric: str,
    source: str,
    status: str,
    reason_code: str,
    affects_chain: str,
    affects_stage: str,
    next_action: str,
    latest_observed_at: str | None = None,
    latest_ingested_at: str | None = None,
    freshness_age: int | None = None,
    freshness_threshold: int | None = None,
    coverage_window: dict[str, str] | None = None,
    sample_count: int = 0,
    configured: bool = True,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "metric": metric,
        "source": source,
        "status": status,
        "latest_observed_at": latest_observed_at,
        "latest_ingested_at": latest_ingested_at,
        "freshness_age": freshness_age,
        "freshness_threshold": freshness_threshold,
        "coverage_window": coverage_window,
        "sample_count": sample_count,
        "reason_code": reason_code,
        "reason_label": REASON_LABELS.get(reason_code, reason_code),
        "affects_chain": affects_chain,
        "affects_stage": affects_stage,
        "next_action": next_action,
        "configured": configured,
    }


def _window_payload(clock: date | None, *, days: int = MACRO_LOOKBACK_DAYS) -> dict[str, str] | None:
    if clock is None:
        return None
    start, end = macro_window(clock, days=days)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dataset_as_of": clock.isoformat(),
    }


def _bar_invalid(row: dict[str, Any]) -> bool:
    errors = ohlc_constraint_errors(
        row.get("open_price") or row.get("open"),
        row.get("high_price") or row.get("high"),
        row.get("low_price") or row.get("low"),
        row.get("close_price") or row.get("close"),
    )
    return bool(errors)


def _collect_macros(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "macro_events",
        "macro_events_stale",
        "macro_events_window_mismatch",
        "macro_events_scheduled",
        "macro_events_out_of_window",
    ):
        rows.extend(list(bundle.get(key) or ()))
    return rows


def _macros_of(events: Iterable[dict[str, Any]], *metrics: str) -> list[dict[str, Any]]:
    wanted = {canonical_metric(item) for item in metrics}
    return [row for row in events if canonical_metric(str(row.get("event_type") or row.get("metric") or "")) in wanted]


def _evaluate_rows(
    *,
    dataset: str,
    metric: str,
    source: str,
    family: str,
    chain: str,
    stage: str,
    rows: list[dict[str, Any]],
    clock: date | None,
    settings: Settings | None,
    kind: str,
    empty_action: str,
    stale_action: str,
    invalid: bool = False,
    coverage_stale: bool = False,
    query_error: bool = False,
    threshold: int | None = None,
    coverage_window: dict[str, str] | None = None,
) -> dict[str, Any]:
    configured = _source_configured(settings, family)
    thresh = FRESHNESS_DAYS.get(metric) if threshold is None else threshold
    if query_error:
        return _dataset_row(
            dataset=dataset,
            metric=metric,
            source=source,
            status=STATUS_ERROR,
            reason_code=REASON_QUERY_ERROR,
            affects_chain=chain,
            affects_stage=stage,
            next_action="稍后重试该数据集查询，不要用猜测填补",
            freshness_threshold=thresh,
            coverage_window=coverage_window,
            configured=configured,
        )
    if invalid:
        latest = rows[0] if rows else {}
        return _dataset_row(
            dataset=dataset,
            metric=metric,
            source=source or latest.get("source") or "unknown",
            status=STATUS_INVALID,
            reason_code=REASON_RECORD_INVALID,
            affects_chain=chain,
            affects_stage=stage,
            next_action="丢弃非法记录并补可校验事实，不能把该记录写入 Change",
            latest_observed_at=_observed_iso(latest, kind=kind) if latest else None,
            latest_ingested_at=_ingested_iso(latest) if latest else None,
            freshness_threshold=thresh,
            coverage_window=coverage_window,
            sample_count=len(rows),
            configured=configured,
        )
    if not rows:
        if not configured:
            return _dataset_row(
                dataset=dataset,
                metric=metric,
                source=source,
                status=STATUS_NOT_CONFIGURED,
                reason_code=REASON_SOURCE_NOT_CONFIGURED,
                affects_chain=chain,
                affects_stage=stage,
                next_action=f"配置 {source} 后重新同步（不在页面展示密钥）",
                freshness_threshold=thresh,
                coverage_window=coverage_window,
                configured=False,
            )
        return _dataset_row(
            dataset=dataset,
            metric=metric,
            source=source,
            status=STATUS_MISSING,
            reason_code=REASON_UPSTREAM_EMPTY,
            affects_chain=chain,
            affects_stage=stage,
            next_action=empty_action,
            freshness_threshold=thresh,
            coverage_window=coverage_window,
            configured=configured,
        )
    latest = rows[0]
    observed = _observed_iso(latest, kind=kind)
    ingested = _ingested_iso(latest)
    age = _age_days(clock, observed)
    stale_by_age = age is not None and thresh is not None and age > thresh
    if coverage_stale or stale_by_age:
        return _dataset_row(
            dataset=dataset,
            metric=metric,
            source=str(latest.get("source") or source),
            status=STATUS_STALE,
            reason_code=REASON_RECORD_STALE,
            affects_chain=chain,
            affects_stage=stage,
            next_action=stale_action,
            latest_observed_at=observed,
            latest_ingested_at=ingested,
            freshness_age=age,
            freshness_threshold=thresh,
            coverage_window=coverage_window,
            sample_count=len(rows),
            configured=configured,
        )
    if observed is None and kind != "bar":
        return _dataset_row(
            dataset=dataset,
            metric=metric,
            source=str(latest.get("source") or source),
            status=STATUS_OK,
            reason_code=REASON_MISSING_OBSERVATION,
            affects_chain=chain,
            affects_stage=stage,
            next_action="记录存在，但缺少观察时间，不能用事件日冒充新鲜度",
            latest_observed_at=None,
            latest_ingested_at=ingested,
            freshness_age=None,
            freshness_threshold=thresh,
            coverage_window=coverage_window,
            sample_count=len(rows),
            configured=configured,
        )
    return _dataset_row(
        dataset=dataset,
        metric=metric,
        source=str(latest.get("source") or source),
        status=STATUS_OK,
        reason_code=REASON_WITHIN_THRESHOLD,
        affects_chain=chain,
        affects_stage=stage,
        next_action="无需恢复；该数据集当前可用于其链",
        latest_observed_at=observed,
        latest_ingested_at=ingested,
        freshness_age=age,
        freshness_threshold=thresh,
        coverage_window=coverage_window,
        sample_count=len(rows),
        configured=configured,
    )


def _price_health(bundle: dict[str, Any], clock: date | None, settings: Settings | None, errors: set[str]) -> dict[str, Any]:
    bars = list(bundle.get("bars") or [])
    window = _window_payload(clock, days=FRESHNESS_DAYS["close"])
    invalid = any(_bar_invalid(row) for row in bars)
    return _evaluate_rows(
        dataset="daily_price_bars",
        metric="close",
        source="alpaca",
        family="alpaca",
        chain="price",
        stage="facts",
        rows=bars,
        clock=clock,
        settings=settings,
        kind="bar",
        empty_action="同步可校验日线 OHLC（source + bar_time）",
        stale_action="同步更新的日线，过旧价格不能当作今日事实",
        invalid=invalid,
        query_error="daily_price_bars" in errors,
        coverage_window=window,
    )


def _earnings_health(bundle: dict[str, Any], clock: date | None, settings: Settings | None, errors: set[str]) -> list[dict[str, Any]]:
    rows = list(bundle.get("earnings") or [])
    window = _window_payload(clock, days=FRESHNESS_DAYS["eps"])
    facts = _evaluate_rows(
        dataset="earnings_reports",
        metric="eps",
        source="fmp",
        family="fmp",
        chain="earnings",
        stage="facts",
        rows=rows,
        clock=clock,
        settings=settings,
        kind="earnings",
        empty_action="同步带 synced_at 的财报实际值/最新共识",
        stale_action="同步更新的财报观察，不能用未来 report_date 假装新鲜",
        query_error="earnings_reports" in errors,
        coverage_window=window,
    )
    prior_rows = [
        row
        for row in rows
        if row.get("prior_consensus") is not None and row.get("prior_consensus_as_of")
    ]
    prior = _evaluate_rows(
        dataset="earnings_prior_consensus",
        metric="eps_prior",
        source="fmp",
        family="fmp",
        chain="earnings",
        stage="expectation",
        rows=prior_rows,
        clock=clock,
        settings=settings,
        kind="earnings",
        empty_action="补前次一致预期的独立 as_of 与 source，才能比较 surprise",
        stale_action="更新前次共识观察时间",
        query_error="earnings_prior_consensus" in errors,
        coverage_window=window,
    )
    if rows and not prior_rows and prior["status"] == STATUS_MISSING:
        prior["next_action"] = "补前次一致预期的独立 as_of 与 source，才能比较 surprise"
    return [facts, prior]


def _macro_metric_health(
    *,
    metric: str,
    dataset: str,
    stage: str,
    family: str,
    source: str,
    parts_inside: list[dict[str, Any]],
    parts_stale: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    clock: date | None,
    settings: Settings | None,
    errors: set[str],
    empty_action: str,
    stale_action: str,
) -> dict[str, Any]:
    window = _window_payload(clock)
    inside = _macros_of(parts_inside, metric)
    stale = _macros_of(parts_stale, metric)
    any_rows = _macros_of(all_events, metric)
    coverage_stale = bool(stale) and not inside
    rows = inside or stale or any_rows
    return _evaluate_rows(
        dataset=dataset,
        metric=metric,
        source=source,
        family=family,
        chain="risk_sentiment" if metric == "vix" else "macro_rates",
        stage=stage,
        rows=rows,
        clock=clock,
        settings=settings,
        kind="macro",
        empty_action=empty_action,
        stale_action=stale_action,
        coverage_stale=coverage_stale,
        query_error=dataset in errors or metric in errors,
        coverage_window=window,
    )


def _chain_payload(chain_id: str, datasets: list[dict[str, Any]]) -> dict[str, Any]:
    owned = [row for row in datasets if row["affects_chain"] == chain_id]
    statuses = {row["status"] for row in owned}
    if STATUS_INVALID in statuses or STATUS_ERROR in statuses:
        health = "unavailable"
    elif not owned or statuses <= {STATUS_MISSING, STATUS_NOT_CONFIGURED}:
        health = "unavailable"
    elif statuses & {STATUS_MISSING, STATUS_STALE, STATUS_NOT_CONFIGURED}:
        health = "limited"
    else:
        health = "available"
    title_en, title_zh = CHAIN_TITLES[chain_id]
    return {
        "id": chain_id,
        "title": title_en,
        "title_zh": title_zh,
        "health": health,
        "coverage": health,
        "datasets": [row["dataset"] for row in owned],
        "blocking": [
            row
            for row in owned
            if row["status"] != STATUS_OK
        ],
    }


def _overall(chains: list[dict[str, Any]]) -> dict[str, Any]:
    by = {row["id"]: row["health"] for row in chains}
    available = [row["id"] for row in chains if row["health"] == "available"]
    limited = [row["id"] for row in chains if row["health"] == "limited"]
    unavailable = [row["id"] for row in chains if row["health"] == "unavailable"]
    if unavailable and not available and not limited:
        status = "unavailable"
    elif limited or unavailable:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "kind": "operational_health",
        "available_chains": available,
        "limited_chains": limited,
        "unavailable_chains": unavailable,
        "note": "数据健康只描述证据可用性，不是投资结论，也不能提高 L0–L3 或生成方向",
        "chain_health": by,
    }


def build_data_health(
    bundle: dict[str, Any],
    *,
    settings: Settings | None = None,
    judgment: dict[str, Any] | None = None,
    query_errors: Iterable[str] | None = None,
    synthetic: bool = False,
    preview: str | None = None,
) -> dict[str, Any]:
    errors = {str(item) for item in (query_errors or ())}
    bars = list(bundle.get("bars") or [])
    earnings = list(bundle.get("earnings") or [])
    macros = _collect_macros(bundle)
    clock = dataset_as_of(bars=bars, earnings=earnings, macros=macros)
    parts = classify_macros(macros, clock)
    settings = settings or Settings()

    datasets = [
        _price_health(bundle, clock, settings, errors),
        *_earnings_health(bundle, clock, settings, errors),
        _macro_metric_health(
            metric="nfp",
            dataset="macro_nfp",
            stage="facts",
            family="fred",
            source="FRED",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="同步非农实际值（观察时间，不是事件日）",
            stale_action="同步更新的 NFP 观察；过旧事件日不能冒充新鲜",
        ),
        _macro_metric_health(
            metric="cpi",
            dataset="macro_cpi",
            stage="what_changed",
            family="fred",
            source="FRED",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="同步 CPI/PCE 原因序列，才能谈通胀/利率链",
            stale_action="同步更新的 CPI 观察；NFP 新鲜不能代替通胀原因",
        ),
        _macro_metric_health(
            metric="us2y",
            dataset="macro_rates_confirm",
            stage="confirmation",
            family="fred",
            source="FRED",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="补利率确认通道（US2Y/实际利率/降息概率）",
            stale_action="更新利率确认观察",
        ),
        _macro_metric_health(
            metric="vix",
            dataset="macro_vix",
            stage="confirmation",
            family="cboe",
            source="cboe",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="补可追溯 VIX Change（source + 观察时间）",
            stale_action="同步更新的 VIX 观察",
        ),
    ]
    chains = [_chain_payload(chain_id, datasets) for chain_id in CHAIN_IDS]
    overall = _overall(chains)
    grade = judgment or {}
    return {
        "symbol": bundle.get("symbol"),
        "as_of": clock.isoformat() if clock else None,
        "clock_status": "ok" if clock is not None else "clock_insufficient",
        "synthetic": bool(synthetic or bundle.get("synthetic")),
        "preview": preview,
        "preview_label": HEALTH_PREVIEW_LABELS.get(preview or "") if preview else None,
        "overall": overall,
        "chains": chains,
        "datasets": datasets,
        "judgment": {
            "level": grade.get("level"),
            "status": grade.get("status"),
            "direction": grade.get("direction"),
            "can_form_direction": bool(grade.get("can_form_direction")),
            "note": "评级仍由阶段三-A 内核决定；数据健康不能提高等级或生成方向/概率/目标价",
        },
        "does_not_form_conclusion": True,
    }


def empty_query_error_health(symbol: str) -> dict[str, Any]:
    bundle = {"symbol": symbol, "bars": [], "earnings": [], "macro_events": [], "synthetic": False}
    return build_data_health(
        bundle,
        query_errors={
            "daily_price_bars",
            "earnings_reports",
            "earnings_prior_consensus",
            "macro_nfp",
            "macro_cpi",
            "macro_rates_confirm",
            "macro_vix",
        },
    )


def _stamp_row(row: dict[str, Any], observed: str, ingested: str | None = None) -> dict[str, Any]:
    payload = dict(row)
    payload["observed_at"] = observed
    payload["synced_at"] = ingested or observed
    payload["source_as_of"] = observed
    return payload


def _valid_bar(as_of: str, close: float, symbol: str = "NVDA") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "open_price": close,
        "high_price": close + 2,
        "low_price": close - 1,
        "close_price": close,
        "volume": 10,
        "bar_time": as_of,
        "source": "alpaca_sip",
        "observed_at": as_of,
        "source_as_of": as_of,
    }


def _invalid_bar(as_of: str, symbol: str = "NVDA") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "open_price": 120,
        "high_price": 110,
        "low_price": 119,
        "close_price": 122,
        "volume": 10,
        "bar_time": as_of,
        "source": "alpaca_sip",
        "observed_at": as_of,
    }


def _earnings_row(symbol: str = "NVDA", *, with_prior: bool = False) -> dict[str, Any]:
    row = {
        "symbol": symbol,
        "eps_actual": 0.81,
        "eps_estimate": 0.74,
        "fiscal_period": "FY2026Q2",
        "report_date": "2026-08-28",
        "source": "fmp",
        "synced_at": "2026-08-28T20:00:00+00:00",
        "observed_at": "2026-08-28T20:00:00+00:00",
    }
    if with_prior:
        row["prior_consensus"] = 0.70
        row["prior_consensus_as_of"] = "2026-07-15T00:00:00+00:00"
    return row


def _macro(event_type: str, actual: float, prior: float, event_time: str, observed: str, source: str = "FRED") -> dict[str, Any]:
    return _stamp_row(
        {
            "event_type": event_type,
            "event_time": event_time,
            "actual": actual,
            "prior": prior,
            "source": source,
            "name": event_type.upper(),
        },
        observed,
        observed,
    )


def _healthy_bundle(symbol: str = "NVDA") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "watch": {"symbol": symbol, "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
        "bars": [
            _valid_bar("2026-09-10T20:00:00+00:00", 122, symbol),
            _valid_bar("2026-09-09T20:00:00+00:00", 116, symbol),
        ],
        "earnings": [_earnings_row(symbol, with_prior=True)],
        "macro_events": [
            _macro("nfp", 220, 140, "2026-09-05T12:30:00+00:00", "2026-09-05T14:00:00+00:00"),
            _macro("cpi", 3.1, 3.0, "2026-09-01T12:30:00+00:00", "2026-09-01T14:00:00+00:00"),
            _macro("us2y", 3.9, 3.7, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00"),
            _macro("vix", 16.2, 15.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", "cboe"),
        ],
        "synthetic": True,
        "_skip_previous": True,
    }


def _preview_settings(settings: Settings | None) -> Settings:
    # Synthetic scenes explain evidence gaps, not the host process's live keys.
    # Always use inert placeholders so MISSING stays upstream_empty.
    _ = settings
    return Settings(
        alpaca_api_key_id="set",
        alpaca_api_secret_key="set",
        fred_api_key="set",
        fmp_api_key="set",
    )


def build_health_preview(symbol: str, key: str, *, settings: Settings | None = None) -> dict[str, Any]:
    scene = key.strip().upper()
    symbol = symbol.upper()
    errors: set[str] = set()
    settings = _preview_settings(settings)
    bundle = _healthy_bundle(symbol)
    if scene == "PARTIAL":
        bundle["macro_events"] = [row for row in bundle["macro_events"] if row["event_type"] != "vix"]
    elif scene == "MISSING":
        bundle = {
            "symbol": symbol,
            "bars": [],
            "earnings": [],
            "macro_events": [],
            "synthetic": True,
        }
    elif scene == "STALE":
        bundle["macro_events"] = [
            _macro("nfp", 220, 140, "2026-09-05T12:30:00+00:00", "2026-09-05T14:00:00+00:00"),
            _macro("cpi", 3.1, 3.0, "2025-12-01T12:30:00+00:00", "2025-12-01T14:00:00+00:00"),
            _macro("us2y", 3.9, 3.7, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00"),
            _macro("vix", 16.2, 15.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", "cboe"),
        ]
    elif scene == "INVALID":
        bundle["bars"] = [
            _invalid_bar("2026-09-11T20:00:00+00:00", symbol),
            _valid_bar("2026-09-10T20:00:00+00:00", 122, symbol),
            _valid_bar("2026-09-09T20:00:00+00:00", 116, symbol),
        ]
    elif scene == "ERROR":
        errors.add("daily_price_bars")
    elif scene != "HEALTHY":
        bundle = _healthy_bundle(symbol)

    from .assemble import assemble_from_bundle

    view = assemble_from_bundle(bundle)
    health = build_data_health(
        bundle,
        settings=settings,
        judgment=view.get("overall"),
        query_errors=errors,
        synthetic=True,
        preview=scene,
    )
    health["preview_label"] = HEALTH_PREVIEW_LABELS.get(scene, "合成演示数据")
    return health


# Imported by tests that check price-move slogans never leak into health.
PRICE_MOVE_FORBIDDEN = ("今日无重大变化", "上升且达到重要性阈值", "下降且达到重要性阈值")
