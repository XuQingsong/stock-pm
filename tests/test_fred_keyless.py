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


def test_gold_official_csv_404_is_error_not_substitute(monkeypatch):
    def fake_text(url, **kwargs):
        if "GOLDPMGBD228NLBM" in url:
            raise FetchError("query_error", "HTTP Error 404")
        series_id = next(
            spec["series_id"] for spec in FRED_MARKET_SERIES.values() if spec["series_id"] in url
        )
        period = "2026-08-01" if series_id == "CPIAUCSL" else "2026-09-10"
        return _text_result(url, _csv(series_id, period, "2.5"))

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    report = sync_fred_market_series(Settings(fred_api_key=""))
    gold = report["series"]["gold"]
    assert gold["status"] == "error"
    assert gold["reason_code"] == "query_error"
    assert gold["series_or_symbol"] == "GOLDPMGBD228NLBM"
    assert gold["http_source"].endswith("id=GOLDPMGBD228NLBM") or "GOLDPMGBD228NLBM" in (gold["http_source"] or "")
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
        series_id = "DGS2"
        for spec in FRED_MARKET_SERIES.values():
            if spec["series_id"] in url:
                series_id = spec["series_id"]
                break
        if series_id == "GOLDPMGBD228NLBM":
            raise FetchError("query_error", "HTTP Error 404")
        period = "2026-08-01" if series_id == "CPIAUCSL" else "2026-09-10"
        return _text_result(url, _csv(series_id, period, "3.5"))

    monkeypatch.setattr(Path, "read_text", spy)
    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    events = collect_live_macro_events(Settings(fred_api_key=""))
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
    assert "api_key" not in dumped
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
        settings=Settings(alpaca_api_key_id="", alpaca_api_secret_key="", fred_api_key="", fmp_api_key=""),
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


def test_overlay_reports_gold_error_without_dropping_other_series(monkeypatch):
    def fake_text(url, **kwargs):
        if "GOLDPMGBD228NLBM" in url:
            raise FetchError("query_error", "HTTP Error 404")
        series_id = next(
            spec["series_id"] for spec in FRED_MARKET_SERIES.values() if spec["series_id"] in url
        )
        period = "2026-08-01" if series_id == "CPIAUCSL" else "2026-09-10"
        return _text_result(url, _csv(series_id, period, "2.5"))

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    events, errors, report = collect_live_macro_overlay(Settings(fred_api_key=""))
    assert "macro_gold" in errors
    assert report["series"]["gold"]["series_or_symbol"] == "GOLDPMGBD228NLBM"
    assert any(row["event_type"] == "cpi" for row in events)
    assert all(row["event_type"] != "gold" for row in events)
