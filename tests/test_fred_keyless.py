"""Official FRED keyless CSV fallback. Fixtures must not enter real runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.config import Settings
from stock_pm.fetch import FetchError, FetchResult
from stock_pm.series import (
    FRED_GRAPH_CSV,
    FRED_MARKET_SERIES,
    collect_live_macro_events,
    collect_live_macro_overlay,
    fetch_fred_series,
    parse_fred_csv,
    sync_fred_market_series,
)

from test_api import FakeDatabase


FETCHED = "2026-09-12T05:52:57+00:00"


def _csv(series_id: str, period: str = "2026-09-10", value: str = "1.25") -> str:
    return f"observation_date,{series_id}\n{period},{value}\n"


def _series_id_from_url(url: str) -> str:
    for spec in FRED_MARKET_SERIES.values():
        if spec["series_id"] in url:
            return spec["series_id"]
    if "PAYEMS" in url:
        return "PAYEMS"
    raise AssertionError(url)


def _csv_for_url(url: str, default_value: str = "2.5") -> str:
    series_id = _series_id_from_url(url)
    if series_id == "PAYEMS":
        return "observation_date,PAYEMS\n2026-08-01,159832\n2026-07-01,159612\n"
    period = "2026-08-01" if series_id == "CPIAUCSL" else "2026-09-10"
    return _csv(series_id, period, default_value)


def _text_result(url: str, payload: str) -> FetchResult:
    return FetchResult(
        payload=payload,
        status="ok",
        reason_code="within_threshold",
        fetched_at=FETCHED,
        from_cache=False,
        http_source=url,
        transport="text",
    )


def test_keyless_uses_official_fredgraph_csv(monkeypatch):
    seen: list[str] = []

    def fake_text(url, **kwargs):
        seen.append(url)
        assert url.startswith(FRED_GRAPH_CSV)
        assert "id=DGS2" in url
        return _text_result(url, _csv("DGS2", "2026-09-10", "4.56"))

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    monkeypatch.setattr(
        "stock_pm.series.json_get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("API path must not run without a key")),
    )
    result = fetch_fred_series("DGS2", "")
    rows = result.payload["observations"]
    assert rows[0]["date"] == "2026-09-10"
    assert rows[0]["value"] == "4.56"
    assert result.transport == "fredgraph_csv"
    assert result.http_source.startswith(FRED_GRAPH_CSV)
    assert "api_key" not in (result.http_source or "")
    assert seen


def test_api_failure_falls_back_to_official_csv(monkeypatch):
    def boom(*_args, **_kwargs):
        raise FetchError("query_error", "api down")

    def fake_text(url, **kwargs):
        assert url.startswith(FRED_GRAPH_CSV)
        assert "id=CPIAUCSL" in url
        return _text_result(url, _csv("CPIAUCSL", "2026-08-01", "334.131"))

    monkeypatch.setattr("stock_pm.series.json_get", boom)
    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    result = fetch_fred_series("CPIAUCSL", "present-but-invalid")
    assert result.transport == "fredgraph_csv"
    assert result.payload["observations"][0]["value"] == "334.131"
    assert "api_key" not in (result.http_source or "")


def test_keyless_csv_parse_error():
    with pytest.raises(FetchError) as exc:
        parse_fred_csv("not,a,fred,header\n1,2,3", "DGS2")
    assert exc.value.reason_code == "record_invalid"
    with pytest.raises(FetchError) as exc:
        parse_fred_csv("observation_date,DGS2\nsoon,4.56", "DGS2")
    assert exc.value.reason_code == "record_invalid"
    with pytest.raises(FetchError) as exc:
        parse_fred_csv("observation_date,DGS2\n2026-09-10,not-a-number", "DGS2")
    assert exc.value.reason_code == "record_invalid"


def test_fred_sync_does_not_fetch_discontinued_gold(monkeypatch):
    seen: list[str] = []

    def fake_text(url, **kwargs):
        seen.append(url)
        return _text_result(url, _csv_for_url(url))

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    report = sync_fred_market_series(Settings(fred_api_key=""))
    assert "gold" not in FRED_MARKET_SERIES
    assert "gold" not in report["series"]
    assert all("GOLDPMGBD228NLBM" not in url for url in seen)
    assert "IQ12260" not in str(report)
    assert report["series"]["cpi"]["status"] == "ok"
    assert report["series"]["dxy"]["status"] == "not_configured"


def test_collect_live_never_reads_test_fixtures(monkeypatch):
    reads: list[str] = []
    original = Path.read_text

    def spy(self, *args, **kwargs):
        reads.append(str(self))
        return original(self, *args, **kwargs)

    def fake_text(url, **kwargs):
        return _text_result(url, _csv_for_url(url, "3.5"))

    monkeypatch.setattr(Path, "read_text", spy)
    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    events = collect_live_macro_events(Settings(fred_api_key="", alpha_vantage_api_key=""))
    assert events
    assert not any("tests/fixtures" in path for path in reads)
    assert all(row.get("source") == "FRED" for row in events)
    assert all(row.get("transport") == "fredgraph_csv" for row in events)


def test_data_health_overlays_live_fred_and_keeps_dxy_unavailable(monkeypatch):
    live = [
        {
            "event_type": "cpi",
            "event_time": "2026-08-01T00:00:00+00:00",
            "actual": 334.131,
            "value": 334.131,
            "source": "FRED",
            "series_or_symbol": "CPIAUCSL",
            "series": "CPIAUCSL",
            "as_of": "2026-08-01",
            "fetched_at": FETCHED,
            "observed_at": FETCHED,
            "unit": "index",
            "frequency": "monthly",
            "http_source": f"{FRED_GRAPH_CSV}?id=CPIAUCSL&cosd=2024-01-01",
            "transport": "fredgraph_csv",
            "status": "ok",
        },
        {
            "event_type": "us2y",
            "event_time": "2026-09-10T00:00:00+00:00",
            "actual": 4.56,
            "value": 4.56,
            "source": "FRED",
            "series_or_symbol": "DGS2",
            "series": "DGS2",
            "as_of": "2026-09-10",
            "fetched_at": FETCHED,
            "observed_at": FETCHED,
            "unit": "percent",
            "frequency": "daily",
            "http_source": f"{FRED_GRAPH_CSV}?id=DGS2&cosd=2024-01-01",
            "transport": "fredgraph_csv",
            "status": "ok",
        },
        {
            "event_type": "broad_usd_proxy",
            "event_time": "2026-09-04T00:00:00+00:00",
            "actual": 118.0732,
            "value": 118.0732,
            "source": "FRED",
            "series_or_symbol": "DTWEXBGS",
            "series": "DTWEXBGS",
            "as_of": "2026-09-04",
            "fetched_at": FETCHED,
            "observed_at": FETCHED,
            "unit": "index",
            "frequency": "daily",
            "http_source": f"{FRED_GRAPH_CSV}?id=DTWEXBGS&cosd=2024-01-01",
            "transport": "fredgraph_csv",
            "status": "ok",
            "name": "广义美元代理",
        },
    ]
    report = {
        "fetched_at": FETCHED,
        "series": {
            "cpi": {
                "source": "FRED",
                "series_or_symbol": "CPIAUCSL",
                "as_of": "2026-08-01",
                "value": 334.131,
                "unit": "index",
                "status": "ok",
                "http_source": f"{FRED_GRAPH_CSV}?id=CPIAUCSL&cosd=2024-01-01",
                "transport": "fredgraph_csv",
            },
            "dxy": {"source": "ice", "series_or_symbol": None, "status": "not_configured"},
            "broad_usd_proxy": {
                "source": "FRED",
                "series_or_symbol": "DTWEXBGS",
                "as_of": "2026-09-04",
                "value": 118.0732,
                "status": "ok",
                "http_source": f"{FRED_GRAPH_CSV}?id=DTWEXBGS&cosd=2024-01-01",
            },
        },
    }
    monkeypatch.setattr(api, "database", FakeDatabase())
    monkeypatch.setattr(
        "stock_pm.series.collect_live_macro_overlay",
        lambda settings=None: (live, set(), report),
    )
    health = TestClient(api.app).get("/api/stock/NVDA/data-health").json()
    assert health["synthetic"] is False
    assert health["runtime"] == "real"
    dumped = str(health).lower()
    assert "tests/fixtures" not in dumped
    assert "api_key=" not in dumped
    assert "apikey=" not in dumped
    by_dataset = {row["dataset"]: row for row in health["datasets"]}
    assert by_dataset["macro_cpi"]["status"] == "ok"
    assert by_dataset["macro_cpi"]["value"] == 334.131
    assert by_dataset["macro_cpi"]["series_or_symbol"] == "CPIAUCSL"
    assert by_dataset["macro_cpi"]["http_source"].startswith(FRED_GRAPH_CSV)
    assert by_dataset["macro_rates_confirm"]["value"] == 4.56
    proxy = by_dataset["macro_broad_usd_proxy"]
    assert proxy["metric"] == "broad_usd_proxy"
    assert proxy["series_or_symbol"] == "DTWEXBGS"
    assert proxy["title_zh"] == "广义美元代理"
    assert "DXY" not in (proxy["title"] or "")
    dxy = by_dataset["macro_dxy"]
    assert dxy["status"] == "not_configured"
    assert dxy["source"] == "ice"
    assert dxy["series_or_symbol"] is None
    assert by_dataset["daily_price_bars"]["status"] == "not_configured"


def test_fred_without_api_key_is_missing_not_not_configured():
    from stock_pm.decision.health import build_data_health

    health = build_data_health(
        {"symbol": "NVDA", "bars": [], "earnings": [], "macro_events": []},
        settings=Settings(
            alpaca_api_key_id="",
            alpaca_api_secret_key="",
            fred_api_key="",
            fmp_api_key="",
            alpha_vantage_api_key="",
        ),
    )
    by_dataset = {row["dataset"]: row for row in health["datasets"]}
    assert by_dataset["macro_cpi"]["status"] == "missing"
    assert by_dataset["macro_cpi"]["series_or_symbol"] == "CPIAUCSL"
    assert by_dataset["macro_rates_confirm"]["series_or_symbol"] == "DGS2"
    assert by_dataset["macro_vix"]["series_or_symbol"] == "VIXCLS"
    assert by_dataset["macro_broad_usd_proxy"]["series_or_symbol"] == "DTWEXBGS"
    assert by_dataset["daily_price_bars"]["status"] == "not_configured"
    assert by_dataset["macro_dxy"]["status"] == "not_configured"
    assert by_dataset["macro_dxy"]["series_or_symbol"] is None
    assert by_dataset["macro_gold"]["status"] == "not_configured"
    assert by_dataset["macro_gold"]["series_or_symbol"] == "XAU"
    assert by_dataset["macro_gold"]["value"] is None
    assert by_dataset["macro_gold"]["required_env"] == "ALPHA_VANTAGE_API_KEY"


def test_overlay_reports_gold_unconfigured_without_dropping_other_series(monkeypatch):
    def fake_text(url, **kwargs):
        return _text_result(url, _csv_for_url(url))

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    events, errors, report = collect_live_macro_overlay(
        Settings(fred_api_key="", alpha_vantage_api_key="")
    )
    assert "macro_gold" not in errors
    assert report["series"]["gold"]["status"] == "not_configured"
    assert report["series"]["gold"]["series_or_symbol"] == "XAU"
    assert report["series"]["gold"]["value"] is None
    assert report["series"]["gold_fred_historical"]["status"] == "upstream_unavailable"
    assert any(row["event_type"] == "cpi" for row in events)
    assert all(row["event_type"] != "gold" for row in events)


def test_data_health_overlays_live_alpaca_bars_without_postgres(monkeypatch):
    from stock_pm.alpaca import daily_bars_http_source

    live_bar = {
        "symbol": "NVDA",
        "bar_time": "2026-09-11T20:00:00+00:00",
        "open_price": 217.0,
        "high_price": 219.5,
        "low_price": 216.4,
        "close_price": 218.29,
        "value": 218.29,
        "as_of": "2026-09-11",
        "unit": "USD",
        "source": "alpaca_sip",
        "series_or_symbol": "NVDA",
        "fetched_at": FETCHED,
        "observed_at": "2026-09-11T20:00:00+00:00",
        "http_source": daily_bars_http_source("NVDA", "sip"),
        "transport": "alpaca",
        "status": "ok",
        "frequency": "daily",
    }
    rec = {
        "source": "alpaca_sip",
        "series_or_symbol": "NVDA",
        "as_of": "2026-09-11",
        "value": 218.29,
        "unit": "USD",
        "status": "ok",
        "reason_code": "within_threshold",
        "http_source": daily_bars_http_source("NVDA", "sip"),
        "transport": "alpaca",
    }

    offline = FakeDatabase()
    offline.ping = lambda: False
    monkeypatch.setattr(api, "database", offline)
    monkeypatch.setattr(api, "_database_reachable", False)
    monkeypatch.setattr(
        "stock_pm.series.collect_live_macro_overlay",
        lambda settings=None: ([], set(), {"fetched_at": FETCHED, "series": {}}),
    )
    monkeypatch.setattr(
        "stock_pm.alpaca.collect_live_daily_bars",
        lambda symbol, settings=None, **kwargs: ([live_bar], set(), {"fetched_at": FETCHED, "daily_price_bars": rec}),
    )

    health = TestClient(api.app).get("/api/stock/NVDA/data-health").json()
    dumped = str(health).lower()
    assert "apikey=" not in dumped
    assert "apca-api-" not in dumped
    assert health["database"]["status"] == "error"
    assert health["persistence"]["status"] == "skipped"
    by_dataset = {row["dataset"]: row for row in health["datasets"]}
    price = by_dataset["daily_price_bars"]
    assert price["status"] == "ok"
    assert price["as_of"] == "2026-09-11"
    assert price["value"] == 218.29
    assert price["unit"] == "USD"
    assert price["series_or_symbol"] == "NVDA"
    assert price["http_source"] == daily_bars_http_source("NVDA", "sip")


def test_data_health_overlays_live_fmp_earnings_without_postgres(monkeypatch):
    from stock_pm.providers import earnings_http_source

    live_row = {
        "symbol": "NVDA",
        "report_date": "2026-08-26",
        "eps_actual": 2.22,
        "eps_estimate": 2.09,
        "as_of": "2026-08-26",
        "value": 2.22,
        "unit": "USD/share",
        "source": "fmp",
        "series_or_symbol": "NVDA",
        "synced_at": FETCHED,
        "observed_at": FETCHED,
        "fetched_at": FETCHED,
        "http_source": earnings_http_source("NVDA"),
        "transport": "fmp",
    }
    rec = {
        "source": "fmp",
        "series_or_symbol": "NVDA",
        "as_of": "2026-08-26",
        "value": 2.22,
        "unit": "USD/share",
        "status": "ok",
        "reason_code": "within_threshold",
        "http_source": earnings_http_source("NVDA"),
        "transport": "fmp",
    }
    offline = FakeDatabase()
    offline.ping = lambda: False
    monkeypatch.setattr(api, "database", offline)
    monkeypatch.setattr(api, "_database_reachable", False)
    monkeypatch.setattr(
        "stock_pm.series.collect_live_macro_overlay",
        lambda settings=None: ([], set(), {"fetched_at": FETCHED, "series": {}}),
    )
    monkeypatch.setattr(
        "stock_pm.alpaca.collect_live_daily_bars",
        lambda symbol, settings=None, **kwargs: ([], set(), {"fetched_at": FETCHED, "daily_price_bars": {"status": "not_configured"}}),
    )
    monkeypatch.setattr(
        "stock_pm.providers.collect_live_earnings",
        lambda symbol, settings=None, **kwargs: ([live_row], set(), {"fetched_at": FETCHED, "earnings_reports": rec}),
    )
    health = TestClient(api.app).get("/api/stock/NVDA/data-health").json()
    dumped = str(health).lower()
    assert "apikey=" not in dumped
    assert health["database"]["status"] == "error"
    by_dataset = {row["dataset"]: row for row in health["datasets"]}
    facts = by_dataset["earnings_reports"]
    assert facts["status"] == "ok"
    assert facts["as_of"] == "2026-08-26"
    assert facts["value"] == 2.22
    assert facts["unit"] == "USD/share"
    assert facts["series_or_symbol"] == "NVDA"
    assert facts["http_source"] == earnings_http_source("NVDA")
    assert by_dataset["earnings_prior_consensus"]["status"] in {"missing", "not_configured"}
