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
    decorate_macro_row,
    map_earnings_health,
    normalized_record,
    parse_fred_observations,
    sync_fred_market_series,
)


def assert_normalized_record(row, *, series, unit, frequency, source="FRED"):
    rec = normalized_record(row) if "notes" in row or "event_type" in row else row
    for field in NORMALIZED_FIELDS:
        assert field in rec, field
        assert rec[field] not in (None, ""), field
    assert rec["source"] == source
    assert rec["series"] == series
    assert rec.get("symbol") == series
    assert rec["unit"] == unit
    assert rec["frequency"] == frequency
    assert rec["status"] in {"ok", "stale", "missing", "invalid", "error", "not_configured"}
    assert rec["as_of"]
    assert rec["observed_at"]
    assert rec["fetched_at"]
    # Period label is not the fetch/observation clock.
    assert rec["as_of"] != rec["observed_at"]
    assert rec["as_of"] != rec["fetched_at"]


def test_parse_fred_observations_skips_dots_and_keeps_values():
    rows = parse_fred_observations(
        {
            "observations": [
                {"date": "2026-09-10", "value": "3.71"},
                {"date": "2026-09-09", "value": "."},
            ]
        }
    )
    assert rows == [{"period": "2026-09-10", "value": 3.71, "realtime_start": None}]


def test_parse_fred_observations_empty_list():
    assert parse_fred_observations({"observations": []}) == []


def test_parse_fred_format_change_is_invalid():
    with pytest.raises(FetchError) as exc:
        parse_fred_observations({"observations": {"date": "2026-09-10"}})
    assert exc.value.reason_code == "record_invalid"


def test_parse_fred_bad_date_is_invalid():
    with pytest.raises(FetchError) as exc:
        parse_fred_observations({"observations": [{"date": "soon", "value": "1"}]})
    assert exc.value.reason_code == "record_invalid"


def test_build_macro_event_does_not_use_period_as_observed_clock():
    event = build_macro_event(
        "us2y",
        {"period": "2026-09-10", "value": 3.71},
        {"series_id": "DGS2", "unit": "percent", "frequency": "daily", "name": "US 2Y"},
        fetched_at="2026-09-11T12:00:00+00:00",
        from_cache=False,
    )
    notes = json.loads(event["notes"])
    assert notes["observed_at"] == "2026-09-11T12:00:00+00:00"
    assert notes["as_of"] == "2026-09-10"
    assert "2099" not in notes["observed_at"]
    decorated = decorate_macro_row(event)
    assert decorated["observed_at"] == "2026-09-11T12:00:00+00:00"
    assert decorated["as_of"].startswith("2026-09-10")


def test_map_earnings_does_not_invent_prior_or_edgar():
    row = map_earnings_health(
        {
            "eps_actual": 0.81,
            "eps_estimate": 0.74,
            "synced_at": "2026-09-10T20:05:00+00:00",
            "source": "fmp",
        }
    )
    assert row["latest_consensus"] == 0.74
    assert row["latest_consensus_as_of"] == "2026-09-10T20:05:00+00:00"
    assert row["prior_consensus"] is None
    assert row["prior_consensus_as_of"] is None
    assert row["edgar_status"] == "not_integrated"


def test_sync_unconfigured_is_not_empty_or_error():
    report = sync_fred_market_series(Settings(fred_api_key=""))
    assert report["series"]["us2y"]["reason_code"] == "source_not_configured"
    assert report["series"]["cpi"]["status"] == "not_configured"
    assert report["series"]["usd_broad"]["status"] == "not_configured"
    assert report["series"]["dxy"]["status"] == "not_configured"
    assert report["series"]["dxy"]["reason_code"] == "source_not_configured"


def test_recorded_fred_fixture_is_labeled():
    fixture = json.loads(Path("tests/fixtures/fred_dgs2.json").read_text())
    rows = parse_fred_observations(fixture)
    assert rows[0]["value"] == 3.71
    assert rows[0]["period"] == "2026-09-10"


def test_recorded_monthly_cpi_fixture_is_labeled():
    fixture = json.loads(Path("tests/fixtures/fred_cpiaucsl.json").read_text())
    assert "recorded fixture" in fixture["label"]
    rows = parse_fred_observations(fixture)
    assert rows[0]["period"] == "2026-08-01"
    assert rows[0]["value"] == 323.228
    event = build_macro_event(
        "cpi",
        rows[0],
        FRED_MARKET_SERIES["cpi"],
        fetched_at="2026-09-11T12:00:00+00:00",
        from_cache=False,
    )
    assert_normalized_record(event, series="CPIAUCSL", unit="index", frequency="monthly")
    rec = normalized_record(event)
    assert rec["as_of"] == "2026-08-01"
    assert rec["observed_at"] == "2026-09-11T12:00:00+00:00"


def test_parse_fred_non_numeric_is_invalid():
    with pytest.raises(FetchError) as exc:
        parse_fred_observations({"observations": [{"date": "2026-08-01", "value": "n.a."}]})
    assert exc.value.reason_code == "record_invalid"


def test_normalized_record_contract_for_wired_series():
    fetched = "2026-09-11T12:00:00+00:00"
    samples = {
        "cpi": {"period": "2026-08-01", "value": 323.2},
        "us2y": {"period": "2026-09-10", "value": 3.71},
        "vix": {"period": "2026-09-10", "value": 16.2},
        "gold": {"period": "2026-09-10", "value": 2300.0},
        "wti": {"period": "2026-09-10", "value": 78.2},
        "usd_broad": {"period": "2026-09-10", "value": 121.4},
    }
    assert "dxy" not in FRED_MARKET_SERIES
    for metric, observation in samples.items():
        spec = FRED_MARKET_SERIES[metric]
        event = build_macro_event(
            metric,
            observation,
            spec,
            fetched_at=fetched,
            from_cache=False,
        )
        assert_normalized_record(
            event,
            series=spec["series_id"],
            unit=spec["unit"],
            frequency=spec["frequency"],
        )
        rec = normalized_record(event)
        assert rec["as_of"] == observation["period"]
        assert rec["observed_at"] == fetched
        assert rec["fetched_at"] == fetched
        if metric == "usd_broad":
            assert event["name"] == "广义美元代理"
            assert rec["series"] == "DTWEXBGS"


def test_legacy_dtwexbgs_row_is_relabeled_proxy_not_dxy():
    row = decorate_macro_row(
        {
            "event_type": "dxy",
            "event_time": "2026-09-10T00:00:00+00:00",
            "actual": 121.4,
            "source": "FRED",
            "unit": "index",
            "notes": json.dumps(
                {
                    "series": "DTWEXBGS",
                    "observed_at": "2026-09-11T12:00:00+00:00",
                    "fetched_at": "2026-09-11T12:00:00+00:00",
                    "as_of": "2026-09-10",
                    "unit": "index",
                    "frequency": "daily",
                    "status": "ok",
                }
            ),
        }
    )
    assert row["event_type"] == "usd_broad"
    assert row["name"] == "广义美元代理"
    rec = normalized_record(row)
    assert rec["series"] == "DTWEXBGS"
    assert rec["as_of"] == "2026-09-10"


def test_sync_empty_observations_is_upstream_empty(monkeypatch):
    monkeypatch.setattr(
        "stock_pm.series.fetch_fred_series",
        lambda *a, **k: FetchResult(
            payload={"observations": []},
            status="ok",
            reason_code="within_threshold",
            fetched_at="2026-09-11T12:00:00+00:00",
            from_cache=False,
        ),
    )
    report = sync_fred_market_series(Settings(fred_api_key="set"))
    assert report["series"]["cpi"]["reason_code"] == "upstream_empty"
    assert report["series"]["us2y"]["reason_code"] == "upstream_empty"
    assert report["series"]["dxy"]["status"] == "not_configured"


def test_sync_reports_dxy_unavailable_even_when_fred_configured(monkeypatch):
    stored = []

    def fake_fetch(series_id, api_key, **kwargs):
        return FetchResult(
            payload={"observations": [{"date": "2026-09-10", "value": "1.25"}]},
            status="ok",
            reason_code="within_threshold",
            fetched_at="2026-09-11T12:00:00+00:00",
            from_cache=False,
        )

    monkeypatch.setattr("stock_pm.series.fetch_fred_series", fake_fetch)
    report = sync_fred_market_series(Settings(fred_api_key="set"), store=stored.append)
    assert "dxy" not in FRED_MARKET_SERIES
    assert report["series"]["dxy"]["status"] == DXY_UNAVAILABLE["status"]
    assert report["series"]["dxy"]["series_id"] is None
    assert report["series"]["usd_broad"]["status"] == "ok"
    assert report["series"]["usd_broad"]["series_id"] == "DTWEXBGS"
    assert all(event["event_type"] != "dxy" for event in stored)
    assert any(event["event_type"] == "usd_broad" for event in stored)
