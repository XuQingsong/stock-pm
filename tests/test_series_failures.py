"""Per-series failure matrix for CPI, US2Y, VIX, gold, WTI, DXY, and broad_usd_proxy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, FetchResult
from stock_pm.series import (
    DXY_UNAVAILABLE,
    FRED_MARKET_SERIES,
    NORMALIZED_FIELDS,
    build_macro_event,
    dxy_unavailable_record,
    normalized_record,
    parse_fred_observations,
    sync_fred_market_series,
    validate_unit,
)

WIRED = tuple(FRED_MARKET_SERIES)
ALL_METRICS = WIRED + ("dxy",)
FETCHED = "2026-09-11T12:00:00+00:00"


def _fixture(metric: str) -> dict:
    spec = FRED_MARKET_SERIES[metric]
    payload = json.loads(Path(spec["fixture"]).read_text())
    assert "recorded fixture" in payload["label"]
    assert "live" in payload["label"]
    return payload


def _ok_result(metric: str, *, from_cache: bool = False, mutate=None) -> FetchResult:
    payload = _fixture(metric)
    if mutate:
        payload = mutate(payload)
    return FetchResult(
        payload=payload,
        status="stale" if from_cache else "ok",
        reason_code="record_stale" if from_cache else "within_threshold",
        fetched_at=FETCHED,
        from_cache=from_cache,
    )


def _sync_one(monkeypatch, metric: str, result):
    target = FRED_MARKET_SERIES[metric]["series_id"]

    def fake_fetch(series_id, api_key, **kwargs):
        if series_id != target:
            other_metric = next(name for name, spec in FRED_MARKET_SERIES.items() if spec["series_id"] == series_id)
            return _ok_result(other_metric)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("stock_pm.series.fetch_fred_series", fake_fetch)
    return sync_fred_market_series(Settings(fred_api_key="set"))


@pytest.mark.parametrize("metric", WIRED)
def test_empty_response_per_series(monkeypatch, metric):
    report = _sync_one(
        monkeypatch,
        metric,
        FetchResult(
            payload={"observations": []},
            status="ok",
            reason_code="within_threshold",
            fetched_at=FETCHED,
            from_cache=False,
        ),
    )
    row = report["series"][metric]
    assert row["status"] == "missing"
    assert row["reason_code"] == "upstream_empty"
    assert row["series_or_symbol"] == FRED_MARKET_SERIES[metric]["series_id"]
    assert report["series"]["dxy"]["status"] == "not_configured"


@pytest.mark.parametrize("metric", WIRED)
def test_timeout_without_cache_per_series(monkeypatch, metric):
    report = _sync_one(monkeypatch, metric, FetchError("timeout", "timed out"))
    row = report["series"][metric]
    assert row["status"] == "error"
    assert row["reason_code"] == "timeout"
    assert report["series"]["dxy"]["status"] in {"not_configured", "unavailable"}


@pytest.mark.parametrize("metric", WIRED)
def test_timeout_uses_stale_cache_per_series(monkeypatch, metric):
    report = _sync_one(monkeypatch, metric, _ok_result(metric, from_cache=True))
    row = report["series"][metric]
    assert row["status"] == "stale"
    assert row["from_cache"] is True
    rec = {key: row[key] for key in NORMALIZED_FIELDS}
    assert rec["status"] == "stale"
    assert rec["as_of"] != rec["observed_at"]


@pytest.mark.parametrize("metric", WIRED)
def test_429_without_cache_per_series(monkeypatch, metric):
    report = _sync_one(monkeypatch, metric, FetchError("rate_limited", "429"))
    row = report["series"][metric]
    assert row["status"] == "error"
    assert row["reason_code"] == "rate_limited"


@pytest.mark.parametrize("metric", WIRED)
def test_429_uses_stale_cache_per_series(monkeypatch, metric):
    report = _sync_one(monkeypatch, metric, _ok_result(metric, from_cache=True))
    row = report["series"][metric]
    assert row["status"] == "stale"
    assert row["reason_code"] == "record_stale"


@pytest.mark.parametrize("metric", WIRED)
def test_format_change_per_series(monkeypatch, metric):
    def mutate(payload):
        payload["observations"] = {"date": "2026-09-10"}
        return payload

    report = _sync_one(monkeypatch, metric, _ok_result(metric, mutate=mutate))
    row = report["series"][metric]
    assert row["status"] == "invalid"
    assert row["reason_code"] == "record_invalid"


@pytest.mark.parametrize("metric", WIRED)
def test_unit_error_per_series(metric):
    spec = FRED_MARKET_SERIES[metric]
    wrong = "percent" if spec["unit"] != "percent" else "index"
    with pytest.raises(FetchError) as exc:
        validate_unit(metric, wrong)
    assert exc.value.reason_code == "record_invalid"
    with pytest.raises(FetchError):
        build_macro_event(
            metric,
            {"period": "2026-08-01" if spec["frequency"] == "monthly" else "2026-09-10", "value": 1.0, "unit": wrong},
            spec,
            fetched_at=FETCHED,
            from_cache=False,
        )


@pytest.mark.parametrize("metric", WIRED)
def test_date_as_of_error_per_series(monkeypatch, metric):
    def mutate(payload):
        payload["observations"] = [{"date": "soon", "value": "1.25"}]
        return payload

    report = _sync_one(monkeypatch, metric, _ok_result(metric, mutate=mutate))
    row = report["series"][metric]
    assert row["status"] == "invalid"
    assert row["reason_code"] == "record_invalid"


@pytest.mark.parametrize("metric", WIRED)
def test_ok_fixture_persists_normalized_contract(monkeypatch, metric):
    stored = []
    spec = FRED_MARKET_SERIES[metric]

    def fake_fetch(series_id, api_key, **kwargs):
        name = next(item for item, row in FRED_MARKET_SERIES.items() if row["series_id"] == series_id)
        return _ok_result(name)

    monkeypatch.setattr("stock_pm.series.fetch_fred_series", fake_fetch)
    report = sync_fred_market_series(Settings(fred_api_key="set"), store=stored.append)
    row = report["series"][metric]
    assert row["status"] == "ok"
    for field in NORMALIZED_FIELDS:
        assert row[field] not in (None, ""), (metric, field)
    assert row["source"] == "FRED"
    assert row["series_or_symbol"] == spec["series_id"]
    assert row["unit"] == spec["unit"]
    assert row["frequency"] == spec["frequency"]
    assert row["as_of"] != row["observed_at"]
    event = next(item for item in stored if item["event_type"] == metric)
    rec = normalized_record(event)
    assert rec["series_or_symbol"] == spec["series_id"]
    if metric == "broad_usd_proxy":
        assert event["name"] == "广义美元代理"
        assert "DXY" not in event["name"]
        assert rec["series_or_symbol"] == "DTWEXBGS"


def test_dxy_stays_unavailable_for_every_failure_mode(monkeypatch):
    def fake_fetch(series_id, api_key, **kwargs):
        raise FetchError("timeout", "timed out")

    monkeypatch.setattr("stock_pm.series.fetch_fred_series", fake_fetch)
    report = sync_fred_market_series(Settings(fred_api_key="set"))
    dxy = report["series"]["dxy"]
    rec = dxy_unavailable_record(fetched_at=report["fetched_at"])
    assert dxy["status"] == DXY_UNAVAILABLE["status"]
    assert dxy["availability"] == "unavailable"
    assert dxy["series_or_symbol"] is None
    assert dxy["source"] == "ice"
    assert rec["status"] == "not_configured"
    assert "dxy" not in FRED_MARKET_SERIES


def test_monthly_cpi_fixture_is_not_a_daily_generalization():
    fixture = _fixture("cpi")
    rows = parse_fred_observations(fixture)
    assert fixture["frequency"] == "monthly"
    assert rows[0]["period"] == "2026-08-01"
    event = build_macro_event(
        "cpi",
        rows[0],
        FRED_MARKET_SERIES["cpi"],
        fetched_at=FETCHED,
        from_cache=False,
    )
    rec = normalized_record(event)
    assert rec["frequency"] == "monthly"
    assert rec["as_of"] == "2026-08-01"
    assert rec["unit"] == "index"
    assert rec["series_or_symbol"] == "CPIAUCSL"


def test_daily_vix_fixture_is_not_dgs2():
    fixture = _fixture("vix")
    rows = parse_fred_observations(fixture)
    assert fixture["series_id"] == "VIXCLS"
    assert fixture["frequency"] == "daily"
    assert rows[0]["period"] == "2026-09-10"
    assert rows[0]["value"] == 16.24
    event = build_macro_event(
        "vix",
        rows[0],
        FRED_MARKET_SERIES["vix"],
        fetched_at=FETCHED,
        from_cache=False,
    )
    rec = normalized_record(event)
    assert rec["frequency"] == "daily"
    assert rec["series_or_symbol"] == "VIXCLS"
    assert rec["as_of"] == "2026-09-10"
    assert rec["as_of"] != rec["observed_at"]
