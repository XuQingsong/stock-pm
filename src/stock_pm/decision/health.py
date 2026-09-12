"""Read-only data health / coverage. Explains evidence availability, never grades."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from stock_pm.config import Settings
from stock_pm.gold import (
    GOLD_ENV_VAR,
    GOLD_LIVE,
    historical_gold_fields,
    is_deprecated_fred_gold,
)
from stock_pm.series import FRED_MARKET_SERIES

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
STATUS_UNAVAILABLE = "upstream_unavailable"

REASON_SOURCE_NOT_CONFIGURED = "source_not_configured"
REASON_UPSTREAM_EMPTY = "upstream_empty"
REASON_RECORD_STALE = "record_stale"
REASON_RECORD_INVALID = "record_invalid"
REASON_QUERY_ERROR = "query_error"
REASON_WITHIN_THRESHOLD = "within_threshold"
REASON_MISSING_OBSERVATION = "missing_observation"
REASON_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
REASON_DEPRECATED = "deprecated"

# Catch-all UI copy is forbidden. Each reason_code maps to a distinct label.
REASON_LABELS = {
    REASON_SOURCE_NOT_CONFIGURED: "源未配置",
    REASON_UPSTREAM_EMPTY: "上游无记录",
    REASON_RECORD_STALE: "记录过旧",
    REASON_RECORD_INVALID: "记录格式非法",
    REASON_QUERY_ERROR: "查询异常",
    REASON_WITHIN_THRESHOLD: "在新鲜度阈值内",
    REASON_MISSING_OBSERVATION: "缺少观察时间",
    REASON_UPSTREAM_UNAVAILABLE: "上游已不可用",
    REASON_DEPRECATED: "序列已停更",
}

FRESHNESS_DAYS = {
    "close": 7,
    "eps": 120,
    "eps_prior": 120,
    "nfp": 45,
    "cpi": 50,
    "us2y": 14,
    "vix": 7,
    "gold": 7,
    "wti": 7,
    "broad_usd_proxy": 7,
    "usd_broad": 7,
    "dxy": 7,
}

DATASET_TITLES = {
    "daily_price_bars": ("Daily price bars", "日线价格"),
    "earnings_reports": ("Earnings reports", "盈利报告"),
    "earnings_prior_consensus": ("Prior consensus", "前次共识"),
    "macro_nfp": ("NFP", "非农"),
    "macro_cpi": ("CPI-U", "CPI"),
    "macro_rates_confirm": ("US 2Y", "美债2年"),
    "macro_gold": ("Gold", "黄金"),
    "macro_wti": ("WTI", "WTI 原油"),
    "macro_broad_usd_proxy": ("USD broad proxy", "广义美元代理"),
    "macro_dxy": ("ICE DXY", "ICE 美元指数"),
    "macro_vix": ("VIX", "VIX"),
}

HEALTH_PREVIEW_LABELS = {
    "HEALTHY": "SYNTHETIC SCENARIO · 数据健康·全面可用（合成演示数据，非实时）",
    "PARTIAL": "SYNTHETIC SCENARIO · 数据健康·部分缺失（合成演示数据，非实时）",
    "MISSING": "SYNTHETIC SCENARIO · 数据健康·全面缺失（合成演示数据，非实时）",
    "STALE": "SYNTHETIC SCENARIO · 数据健康·陈旧（合成演示数据，非实时）",
    "INVALID": "SYNTHETIC SCENARIO · 数据健康·非法记录（合成演示数据，非实时）",
    "ERROR": "SYNTHETIC SCENARIO · 数据健康·查询异常（合成演示数据，非实时）",
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
        # Official fredgraph.csv is keyless. An API key is preferred, not required.
        return True
    if family == "fmp":
        return bool(settings.fmp_api_key)
    if family == "alpha_vantage":
        return bool(settings.alpha_vantage_api_key)
    return True


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
    required: bool = True,
    series: str | None = None,
    series_or_symbol: str | None = None,
    as_of: str | None = None,
    fetched_at: str | None = None,
    unit: str | None = None,
    frequency: str | None = None,
    value: Any = None,
    http_source: str | None = None,
    transport: str | None = None,
    title: str | None = None,
    title_zh: str | None = None,
) -> dict[str, Any]:
    en, zh = DATASET_TITLES.get(dataset, (dataset, dataset))
    return {
        "dataset": dataset,
        "metric": metric,
        "title": title or en,
        "title_zh": title_zh or zh,
        "source": source,
        "series": series_or_symbol or series,
        "series_or_symbol": series_or_symbol or series,
        "status": status,
        "latest_observed_at": latest_observed_at,
        "latest_ingested_at": latest_ingested_at,
        "as_of": as_of,
        "fetched_at": fetched_at,
        "unit": unit,
        "frequency": frequency,
        "value": value,
        "http_source": http_source,
        "transport": transport,
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
        "required": required,
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


def _row_provenance(row: dict[str, Any] | None) -> dict[str, Any]:
    latest = row or {}
    series = latest.get("series_or_symbol") or latest.get("series") or latest.get("symbol")
    as_of = latest.get("as_of")
    if as_of is None and latest.get("event_time"):
        event_time = latest.get("event_time")
        as_of = event_time.isoformat()[:10] if hasattr(event_time, "isoformat") else str(event_time)[:10]
    value = latest.get("value")
    if value is None:
        value = latest.get("actual")
    return {
        "series": series,
        "series_or_symbol": series,
        "as_of": as_of,
        "fetched_at": latest.get("fetched_at") or latest.get("observed_at"),
        "unit": latest.get("unit"),
        "frequency": latest.get("frequency"),
        "value": value,
        "http_source": latest.get("http_source"),
        "transport": latest.get("transport"),
    }


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
    required: bool = True,
) -> dict[str, Any]:
    configured = _source_configured(settings, family)
    thresh = FRESHNESS_DAYS.get(metric) if threshold is None else threshold
    latest = rows[0] if rows else {}
    provenance = _row_provenance(latest)
    spec = FRED_MARKET_SERIES.get(metric) or {}
    if metric == "gold":
        spec = {
            "series_id": GOLD_LIVE["symbol"],
            "unit": GOLD_LIVE["unit"],
            "frequency": GOLD_LIVE["frequency"],
        }
    if not provenance.get("series_or_symbol") and spec.get("series_id"):
        provenance["series"] = spec["series_id"]
        provenance["series_or_symbol"] = spec["series_id"]
    if not provenance.get("unit") and spec.get("unit"):
        provenance["unit"] = spec["unit"]
    if not provenance.get("frequency") and spec.get("frequency"):
        provenance["frequency"] = spec["frequency"]
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
            required=required,
            **provenance,
        )
    if invalid:
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
            required=required,
            **provenance,
        )
    if not rows:
        wired = spec.get("series_id") or provenance.get("series_or_symbol")
        if not configured:
            return _dataset_row(
                dataset=dataset,
                metric=metric,
                source=source,
                status=STATUS_NOT_CONFIGURED,
                reason_code=REASON_SOURCE_NOT_CONFIGURED,
                affects_chain=chain,
                affects_stage=stage,
                next_action=(
                    empty_action
                    if metric == "gold"
                    else f"配置 {source} 后重新同步（不在页面展示密钥）"
                ),
                freshness_threshold=thresh,
                coverage_window=coverage_window,
                configured=False,
                required=required,
                series=wired,
                series_or_symbol=wired,
                unit=spec.get("unit"),
                frequency=spec.get("frequency"),
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
            required=required,
            series=wired,
            series_or_symbol=wired,
            unit=spec.get("unit"),
            frequency=spec.get("frequency"),
        )
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
            required=required,
            **provenance,
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
            required=required,
            **provenance,
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
        required=required,
        **provenance,
    )


def _price_health(bundle: dict[str, Any], clock: date | None, settings: Settings | None, errors: set[str]) -> dict[str, Any]:
    bars = list(bundle.get("bars_all") or bundle.get("bars") or [])
    window = _window_payload(clock, days=FRESHNESS_DAYS["close"])
    latest = bars[0] if bars else None
    invalid = bool(latest) and _bar_invalid(latest)
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
    required: bool = True,
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
        required=required,
    )


def _chain_payload(chain_id: str, datasets: list[dict[str, Any]]) -> dict[str, Any]:
    owned = [row for row in datasets if row["affects_chain"] == chain_id]
    core = [row for row in owned if row.get("required", True)]
    statuses = {row["status"] for row in (core or owned)}
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
        _gold_health(
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
        ),
        _macro_metric_health(
            metric="wti",
            dataset="macro_wti",
            stage="confirmation",
            family="fred",
            source="FRED",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="同步 WTI 观察（FRED DCOILWTICO）",
            stale_action="更新 WTI 观察；缺失原油不得伪造利率链",
            required=False,
        ),
        _macro_metric_health(
            metric="broad_usd_proxy",
            dataset="macro_broad_usd_proxy",
            stage="confirmation",
            family="fred",
            source="FRED",
            parts_inside=parts.inside,
            parts_stale=parts.stale,
            all_events=macros,
            clock=clock,
            settings=settings,
            errors=errors,
            empty_action="同步广义美元代理 broad_usd_proxy（FRED DTWEXBGS）；不得写成 DXY",
            stale_action="更新广义美元代理观察；单项缺失不得删除其他事实，也不得冒充 ICE DXY",
            required=False,
        ),
        _dxy_unavailable_health(),
        _macro_metric_health(
            metric="vix",
            dataset="macro_vix",
            stage="confirmation",
            family="fred",
            source="FRED",
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


def _gold_health(
    *,
    parts_inside: list[dict[str, Any]],
    parts_stale: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    clock: date | None,
    settings: Settings | None,
    errors: set[str],
) -> dict[str, Any]:
    window = _window_payload(clock)
    inside = [row for row in _macros_of(parts_inside, "gold") if not is_deprecated_fred_gold(row)]
    stale = [row for row in _macros_of(parts_stale, "gold") if not is_deprecated_fred_gold(row)]
    any_rows = [row for row in _macros_of(all_events, "gold") if not is_deprecated_fred_gold(row)]
    coverage_stale = bool(stale) and not inside
    rows = inside or stale or any_rows
    row = _evaluate_rows(
        dataset="macro_gold",
        metric="gold",
        source="alpha_vantage",
        family="alpha_vantage",
        chain="macro_rates",
        stage="confirmation",
        rows=rows,
        clock=clock,
        settings=settings,
        kind="macro",
        empty_action=f"配置 {GOLD_ENV_VAR} 后同步 Alpha Vantage {GOLD_LIVE['symbol']} 日度金价（不在页面展示密钥）",
        stale_action="更新 Alpha Vantage 黄金观察；不得把已停更的 FRED LBMA 价格当作当前金价",
        coverage_stale=coverage_stale,
        query_error="macro_gold" in errors or "gold" in errors,
        coverage_window=window,
        required=False,
    )
    row.update(historical_gold_fields())
    if row["status"] in {STATUS_NOT_CONFIGURED, STATUS_UNAVAILABLE, STATUS_MISSING, STATUS_ERROR}:
        if not rows:
            row["value"] = None
    if is_deprecated_fred_gold({"series_or_symbol": row.get("series_or_symbol"), "source": row.get("source")}):
        row["value"] = None
        row["status"] = STATUS_UNAVAILABLE
        row["reason_code"] = REASON_DEPRECATED
        row["reason_label"] = REASON_LABELS[REASON_DEPRECATED]
        row["series_or_symbol"] = GOLD_LIVE["symbol"]
        row["series"] = GOLD_LIVE["symbol"]
        row["source"] = "alpha_vantage"
    return row


def _dxy_unavailable_health() -> dict[str, Any]:
    return _dataset_row(
        dataset="macro_dxy",
        metric="dxy",
        source="ice",
        status=STATUS_NOT_CONFIGURED,
        reason_code=REASON_SOURCE_NOT_CONFIGURED,
        affects_chain="macro_rates",
        affects_stage="confirmation",
        next_action="ICE DXY 未合法稳定接入；不得把 FRED DTWEXBGS 写成 DXY 或用代理冒充健康",
        freshness_threshold=FRESHNESS_DAYS["dxy"],
        configured=False,
        required=False,
        series=None,
        series_or_symbol=None,
    )


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
            "macro_gold",
            "macro_wti",
            "macro_broad_usd_proxy",
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
        "series": symbol,
        "observed_at": as_of,
        "source_as_of": as_of,
        "as_of": as_of[:10],
        "fetched_at": as_of,
        "frequency": "daily",
        "status": "ok",
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
        "source": "fmp",
        "synced_at": "2026-08-28T20:00:00+00:00",
        "observed_at": "2026-08-28T20:00:00+00:00",
    }
    if with_prior:
        row["prior_consensus"] = 0.70
        row["prior_consensus_as_of"] = "2026-07-15T00:00:00+00:00"
    return row


def _macro(
    event_type: str,
    actual: float,
    prior: float,
    event_time: str,
    observed: str,
    source: str = "FRED",
    *,
    series: str | None = None,
    unit: str | None = None,
    frequency: str = "daily",
) -> dict[str, Any]:
    return _stamp_row(
        {
            "event_type": event_type,
            "event_time": event_time,
            "actual": actual,
            "prior": prior,
            "source": source,
            "name": "广义美元代理" if event_type in {"usd_broad", "broad_usd_proxy"} else event_type.upper(),
            "series": series or event_type,
            "series_or_symbol": series or event_type,
            "as_of": event_time[:10],
            "fetched_at": observed,
            "unit": unit,
            "frequency": frequency,
            "status": "ok",
        },
        observed,
        observed,
    )


def _healthy_bundle(symbol: str = "NVDA") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "bars": [
            _valid_bar("2026-09-10T20:00:00+00:00", 122, symbol),
            _valid_bar("2026-09-09T20:00:00+00:00", 116, symbol),
        ],
        "earnings": [_earnings_row(symbol, with_prior=True)],
        "macro_events": [
            _macro("nfp", 220, 140, "2026-09-05T12:30:00+00:00", "2026-09-05T14:00:00+00:00", series="PAYEMS", unit="thousands"),
            _macro("cpi", 3.1, 3.0, "2026-09-01T12:30:00+00:00", "2026-09-01T14:00:00+00:00", series="CPIAUCSL", unit="index", frequency="monthly"),
            _macro("us2y", 3.9, 3.7, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", series="DGS2", unit="percent"),
            _macro("broad_usd_proxy", 121.4, 120.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", series="DTWEXBGS", unit="index"),
            _macro("vix", 16.2, 15.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", "cboe", series="VIXCLS", unit="index"),
        ],
        "synthetic": True,
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
        alpha_vantage_api_key="set",
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
            _macro("nfp", 220, 140, "2026-09-05T12:30:00+00:00", "2026-09-05T14:00:00+00:00", series="PAYEMS", unit="thousands"),
            _macro("cpi", 3.1, 3.0, "2025-12-01T12:30:00+00:00", "2025-12-01T14:00:00+00:00", series="CPIAUCSL", unit="index", frequency="monthly"),
            _macro("us2y", 3.9, 3.7, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", series="DGS2", unit="percent"),
            _macro("broad_usd_proxy", 121.4, 120.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", series="DTWEXBGS", unit="index"),
            _macro("vix", 16.2, 15.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", "cboe", series="VIXCLS", unit="index"),
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

    # Preview health never calls the 3-A assembler. Judgment stays empty;
    # the page continues to read L0–L3 from /decision.
    return build_data_health(
        bundle,
        settings=settings,
        judgment=None,
        query_errors=errors,
        synthetic=True,
        preview=scene,
    )
