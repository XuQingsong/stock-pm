from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.config import Settings
from stock_pm.fetch import FetchError
from stock_pm.series import (
    build_macro_event,
    decorate_macro_row,
    map_earnings_health,
    parse_fred_observations,
    sync_fred_market_series,
)


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


def test_recorded_fred_fixture_is_labeled(tmp_path):
    fixture = json.loads(Path("tests/fixtures/fred_dgs2.json").read_text())
    rows = parse_fred_observations(fixture)
    assert rows[0]["value"] == 3.71
    assert rows[0]["period"] == "2026-09-10"
