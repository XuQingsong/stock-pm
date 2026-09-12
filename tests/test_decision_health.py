"""Phase 3-B: isolated data health / coverage. Does not change L0–L3 grading."""

from __future__ import annotations

import json

from stock_pm.config import Settings
from stock_pm.decision.assemble import assemble_from_bundle
from stock_pm.decision.change import NO_MATERIAL_CHANGE
from stock_pm.decision.health import (
    HEALTH_PREVIEW_LABELS,
    REASON_QUERY_ERROR,
    REASON_RECORD_INVALID,
    REASON_RECORD_STALE,
    REASON_SOURCE_NOT_CONFIGURED,
    REASON_UPSTREAM_EMPTY,
    build_data_health,
    build_health_preview,
    empty_query_error_health,
    _earnings_row,
    _healthy_bundle,
    _macro,
)
from stock_pm.decision.preview import build_preview
from stock_pm.decision.viewmodel import CHAIN_STEPS

PRICE_MOVE_FORBIDDEN = ("今日无重大变化", "上升且达到重要性阈值", "下降且达到重要性阈值")


def _ds(health, dataset):
    return next(row for row in health["datasets"] if row["dataset"] == dataset)


def _chain(health, chain_id):
    return next(row for row in health["chains"] if row["id"] == chain_id)


def _configured() -> Settings:
    return Settings(
        alpaca_api_key_id="set",
        alpaca_api_secret_key="set",
        fred_api_key="set",
        fmp_api_key="set",
        alpha_vantage_api_key="set",
    )


def _unconfigured() -> Settings:
    return Settings(
        alpaca_api_key_id="",
        alpaca_api_secret_key="",
        fred_api_key="",
        fmp_api_key="",
        alpha_vantage_api_key="",
    )


def test_missing_vix_limits_only_risk_sentiment():
    base = _healthy_bundle()
    with_vix = build_data_health(base, settings=_configured())
    missing = dict(base)
    missing["macro_events"] = [row for row in base["macro_events"] if row["event_type"] != "vix"]
    health = build_data_health(missing, settings=_configured())
    assert _chain(health, "risk_sentiment")["health"] == "unavailable"
    assert _ds(health, "macro_vix")["status"] == "missing"
    assert _ds(health, "macro_vix")["reason_code"] == REASON_UPSTREAM_EMPTY
    assert _ds(health, "macro_vix")["reason_label"] != "缺数据"
    for chain_id in ("price", "earnings", "macro_rates"):
        assert _chain(health, chain_id)["health"] == _chain(with_vix, chain_id)["health"], chain_id


def test_missing_prior_consensus_limits_only_earnings_expectation():
    bundle = _healthy_bundle()
    bundle["earnings"] = [_earnings_row(with_prior=False)]
    health = build_data_health(bundle, settings=_configured())
    prior = _ds(health, "earnings_prior_consensus")
    facts = _ds(health, "earnings_reports")
    assert facts["status"] == "ok"
    assert prior["status"] == "missing"
    assert prior["affects_chain"] == "earnings"
    assert prior["affects_stage"] == "expectation"
    assert _chain(health, "earnings")["health"] == "limited"
    assert _chain(health, "price")["health"] == "available"
    assert _chain(health, "risk_sentiment")["health"] == "available"


def test_invalid_ohlc_invalidates_price_facts_only():
    bundle = _healthy_bundle()
    bundle["bars"] = [
        {
            "symbol": "NVDA",
            "open_price": 120,
            "high_price": 110,
            "low_price": 119,
            "close_price": 122,
            "volume": 10,
            "bar_time": "2026-09-11T20:00:00+00:00",
            "source": "alpaca_sip",
        },
        *_healthy_bundle()["bars"],
    ]
    bundle["macro_events"] = [row for row in bundle["macro_events"] if row["event_type"] != "vix"]
    health = build_data_health(bundle, settings=_configured())
    view = assemble_from_bundle(bundle)
    price = _ds(health, "daily_price_bars")
    assert price["status"] == "invalid"
    assert price["reason_code"] == REASON_RECORD_INVALID
    assert price["affects_chain"] == "price"
    assert price["affects_stage"] == "facts"
    assert _chain(health, "price")["health"] == "unavailable"
    assert _chain(health, "earnings")["health"] == "available"
    assert _chain(health, "macro_rates")["health"] != "unavailable"
    dumped = json.dumps(health, ensure_ascii=False)
    assert NO_MATERIAL_CHANGE not in dumped
    price_view = next(row for row in view["chains"] if row["id"] == "price")
    assert price_view["level"] == "L0"
    for phrase in PRICE_MOVE_FORBIDDEN:
        assert phrase not in (price_view.get("validated_conclusion") or "")
    assert "今日无重大变化" not in (view["overall"].get("can_determine") or "")


def test_stale_cpi_fresh_nfp_are_split_and_nfp_is_not_rates_chain():
    health = build_health_preview("NVDA", "STALE", settings=_configured())
    view = assemble_from_bundle({
        **_healthy_bundle(),
        "macro_events": [
            _macro("nfp", 220, 140, "2026-09-05T12:30:00+00:00", "2026-09-05T14:00:00+00:00"),
            _macro("cpi", 3.1, 3.0, "2025-12-01T12:30:00+00:00", "2025-12-01T14:00:00+00:00"),
            _macro("us2y", 3.9, 3.7, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00"),
            _macro("vix", 16.2, 15.8, "2026-09-10T20:00:00+00:00", "2026-09-10T20:00:00+00:00", "cboe"),
        ],
    })
    cpi = _ds(health, "macro_cpi")
    nfp = _ds(health, "macro_nfp")
    assert cpi["status"] == "stale"
    assert cpi["reason_code"] == REASON_RECORD_STALE
    assert nfp["status"] == "ok"
    assert _chain(health, "macro_rates")["health"] == "limited"
    macro = next(row for row in view["chains"] if row["id"] == "macro_rates")
    text = macro["validated_conclusion"]
    assert "NFP" in text
    assert "不能" in text and "利率链已成立" in text
    assert "上升且达到重要性阈值" not in text


def test_not_configured_is_not_query_error_and_secrets_stay_out():
    empty = {"symbol": "NVDA", "bars": [], "earnings": [], "macro_events": []}
    missing_cfg = build_data_health(empty, settings=_unconfigured())
    failed = build_data_health(
        _healthy_bundle(),
        settings=_configured(),
        query_errors={"daily_price_bars"},
    )
    price_cfg = _ds(missing_cfg, "daily_price_bars")
    price_err = _ds(failed, "daily_price_bars")
    assert price_cfg["status"] == "not_configured"
    assert price_cfg["reason_code"] == REASON_SOURCE_NOT_CONFIGURED
    assert price_err["status"] == "error"
    assert price_err["reason_code"] == REASON_QUERY_ERROR
    assert price_cfg["reason_label"] != price_err["reason_label"]
    leaked = empty_query_error_health("NVDA")
    dumped = json.dumps({"a": missing_cfg, "b": failed, "c": leaked}, ensure_ascii=False).lower()
    assert "sk-" not in dumped
    assert "traceback" not in dumped
    assert "secret" not in dumped
    assert "api_key=" not in dumped
    assert "apikey=" not in dumped


def test_future_release_date_does_not_make_freshness_newer():
    bundle = _healthy_bundle()
    bundle["earnings"] = [{
        "symbol": "NVDA",
        "eps_actual": 0.81,
        "eps_estimate": 0.74,
        "fiscal_period": "FY2099Q1",
        "report_date": "2099-01-15",
        "release_date": "2099-01-15",
        "source": "fmp",
        "synced_at": "2026-01-02T00:00:00+00:00",
        "observed_at": "2026-01-02T00:00:00+00:00",
    }]
    health = build_data_health(bundle, settings=_configured())
    facts = _ds(health, "earnings_reports")
    assert facts["latest_observed_at"]
    assert "2099" not in (facts["latest_observed_at"] or "")
    assert facts["freshness_age"] is not None
    assert facts["freshness_age"] >= 200
    assert facts["status"] == "stale"
    assert health["as_of"] is None or "2099" not in health["as_of"]


def test_healthy_datasets_do_not_stack_l2_into_l3_or_mint_a_thesis():
    l2 = build_preview("NVDA", "L2")
    health = build_health_preview("NVDA", "HEALTHY", settings=_configured())
    view = assemble_from_bundle(_healthy_bundle())
    assert l2["overall"]["level"] == "L2"
    assert l2["can_form_direction"] is False
    assert health["does_not_form_conclusion"] is True
    assert health["overall"]["kind"] == "operational_health"
    assert health["judgment"]["level"] is None
    assert health["judgment"]["can_form_direction"] is False
    assert health["judgment"]["note"]
    assert view["overall"]["level"] != "L3" or view["can_form_direction"] is False
    assert _ds(health, "macro_dxy")["status"] == "not_configured"
    assert _ds(health, "macro_broad_usd_proxy")["status"] == "ok"
    assert _ds(health, "macro_broad_usd_proxy")["title_zh"] == "广义美元代理"
    assert _ds(health, "macro_broad_usd_proxy")["series_or_symbol"] == "DTWEXBGS"


def test_health_preview_scenes_and_chain_order_untouched():
    for key in HEALTH_PREVIEW_LABELS:
        health = build_health_preview("NVDA", key, settings=_configured())
        assert health["synthetic"] is True
        assert health["preview"] == key
        assert "合成演示数据" in (health["preview_label"] or "")
        assert "SYNTHETIC SCENARIO" in (health["preview_label"] or "")
        assert [row["id"] for row in health["chains"]] == ["price", "earnings", "macro_rates", "risk_sentiment"]
        for row in health["datasets"]:
            for field in (
                "dataset", "metric", "title", "title_zh", "source", "series",
                "series_or_symbol",
                "status", "latest_observed_at", "latest_ingested_at", "as_of",
                "fetched_at", "unit", "frequency", "value", "http_source",
                "transport", "freshness_age",
                "freshness_threshold", "coverage_window", "sample_count",
                "reason_code", "affects_chain", "affects_stage", "next_action",
            ):
                assert field in row, (key, row.get("dataset"), field)
            assert row["reason_label"] != "缺数据"
    view = assemble_from_bundle(_healthy_bundle())
    assert [step["id"] for step in view["chain"]] == [row[0] for row in CHAIN_STEPS]


def test_missing_preview_stays_upstream_empty_with_unconfigured_host_settings():
    health = build_health_preview("NVDA", "MISSING", settings=_unconfigured())
    assert health["overall"]["status"] == "unavailable"
    for row in health["datasets"]:
        if row["dataset"] == "macro_dxy":
            assert row["status"] == "not_configured", row
            assert row["reason_code"] == REASON_SOURCE_NOT_CONFIGURED
            continue
        assert row["status"] == "missing", row["dataset"]
        assert row["reason_code"] == REASON_UPSTREAM_EMPTY, row["dataset"]
        assert row["reason_label"] == "上游无记录"


def test_partial_and_missing_and_error_previews():
    partial = build_health_preview("NVDA", "PARTIAL", settings=_configured())
    missing = build_health_preview("NVDA", "MISSING", settings=_configured())
    error = build_health_preview("NVDA", "ERROR", settings=_configured())
    invalid = build_health_preview("NVDA", "INVALID", settings=_configured())
    assert _ds(partial, "macro_vix")["status"] == "missing"
    assert _ds(partial, "daily_price_bars")["status"] == "ok"
    assert all(
        row["status"] == "not_configured" if row["dataset"] == "macro_dxy" else row["status"] == "missing"
        for row in missing["datasets"]
    )
    assert _ds(partial, "macro_dxy")["status"] == "not_configured"
    assert _ds(partial, "macro_broad_usd_proxy")["title_zh"] == "广义美元代理"
    assert _ds(error, "daily_price_bars")["status"] == "error"
    assert _ds(error, "macro_nfp")["status"] == "ok"
    assert _ds(invalid, "daily_price_bars")["status"] == "invalid"
    assert NO_MATERIAL_CHANGE not in json.dumps(invalid, ensure_ascii=False)
