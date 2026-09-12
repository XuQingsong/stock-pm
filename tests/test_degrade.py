from __future__ import annotations

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.errors import DatabaseError

from test_api import FakeDatabase, _empty_live_overlay


class DownDatabase(FakeDatabase):
    def ping(self):
        return False

    def monitor_status(self):
        return {
            "status": "error",
            "reachable": False,
            "database": "unavailable",
            "reason_code": "query_error",
            "note": "PostgreSQL unreachable; live overlay does not hide this",
            "dsn": "postgresql://stock_pm:***@localhost:5432/stock_pm",
        }

    def watchlist_rows(self, include_inactive=False):
        raise DatabaseError("postgres down")

    def latest_snapshots(self, symbols=None):
        raise DatabaseError("postgres down")

    def chart_history(self, symbol, limit=260, interval="1d"):
        raise DatabaseError("postgres down")

    def earnings_summary_view(self, symbol):
        raise DatabaseError("postgres down")

    def investment_overview(self, symbol):
        raise DatabaseError("postgres down")

    def news(self, symbols=None, limit=60):
        raise DatabaseError("postgres down")

    def option_wall(self, symbol):
        raise DatabaseError("postgres down")

    def decision_bundle(self, symbol):
        raise DatabaseError("postgres down")


def _client(monkeypatch, database) -> TestClient:
    monkeypatch.setattr(api, "database", database)
    monkeypatch.setattr(api, "_database_reachable", bool(database.ping()))
    monkeypatch.setattr("stock_pm.series.collect_live_macro_overlay", _empty_live_overlay)
    return TestClient(api.app)


def test_health_errors_when_database_is_down(monkeypatch):
    response = _client(monkeypatch, DownDatabase()).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["database"] == "unavailable"
    assert body["database_status"] == "error"
    assert body["reason_code"] == "query_error"
    assert "overlay" in (body.get("note") or "").lower()


def test_core_pages_render_when_database_is_down(monkeypatch):
    c = _client(monkeypatch, DownDatabase())
    for path in ("/", "/stock/NVDA", "/health"):
        assert c.get(path).status_code == 200, path


def test_core_reads_degrade_locally_instead_of_global_503(monkeypatch):
    c = _client(monkeypatch, DownDatabase())
    watch = c.get("/api/watchlist")
    assert watch.status_code == 200
    assert watch.json() == []
    chart = c.get("/api/stock/NVDA/chart")
    assert chart.status_code == 200
    body = chart.json()
    assert body["status"] == "error"
    assert body["bars"] == []
    assert body["reason_code"] == "query_error"
    news = c.get("/api/stock/NVDA/news")
    assert news.status_code == 200
    assert news.json() == []
    earnings = c.get("/api/stock/NVDA/earnings/summary")
    assert earnings.status_code == 200
    assert earnings.json()["status"] == "error"


def test_data_health_keeps_overlay_but_marks_database_error(monkeypatch):
    monkeypatch.setattr(
        "stock_pm.alpaca.collect_live_daily_bars",
        lambda symbol, settings=None, **kwargs: (
            [{
                "symbol": "NVDA",
                "bar_time": "2026-09-11T20:00:00+00:00",
                "open_price": 217,
                "high_price": 219,
                "low_price": 216,
                "close_price": 218.29,
                "as_of": "2026-09-11",
                "source": "alpaca_sip",
            }],
            set(),
            {
                "fetched_at": "2026-09-12T00:00:00+00:00",
                "daily_price_bars": {
                    "source": "alpaca_sip",
                    "series_or_symbol": "NVDA",
                    "as_of": "2026-09-11",
                    "value": 218.29,
                    "unit": "USD",
                    "status": "ok",
                },
            },
        ),
    )
    health = _client(monkeypatch, DownDatabase()).get("/api/stock/NVDA/data-health").json()
    assert health["database"]["status"] == "error"
    assert health["database"]["reachable"] is False
    assert health["persistence"]["status"] == "skipped"
    by_dataset = {row["dataset"]: row for row in health["datasets"]}
    assert by_dataset["daily_price_bars"]["status"] == "ok"
    assert by_dataset["daily_price_bars"]["value"] == 218.29
