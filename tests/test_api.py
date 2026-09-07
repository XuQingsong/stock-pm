from __future__ import annotations

from fastapi.testclient import TestClient

from stock_pm import api


WATCH = [
    {"symbol": s, "name": s, "primary_exchange": "NASDAQ", "asset_class": "stocks",
     "sector": None, "themes": [], "rate_sensitivity": "medium", "active": True,
     "added_at": None}
    for s in ["MU", "INTC", "AAPL", "GOOGL", "NVDA", "SKHY", "NOK", "AVGO", "QQQ"]
]


class FakeDatabase:
    def __init__(self):
        self.added = []
        self.deactivated = []
        self.macro = []

    def ping(self):
        return True

    def initialize(self):
        return None

    def watchlist_rows(self, include_inactive=False):
        return WATCH

    def active_symbols(self):
        return [row["symbol"] for row in WATCH]

    def upsert_watchlist(self, row):
        self.added.append(row)

    def deactivate_watchlist(self, symbol):
        self.deactivated.append(symbol)

    def latest_snapshots(self, symbols=None):
        return [{"symbol": (symbols or ["AAPL"])[0], "last_price": 250, "source": "alpaca_iex"}]

    def live_signals(self, symbols=None):
        return [{"symbol": (symbols or ["AAPL"])[0], "signal": "VWAP上方"}]

    def technical_summary(self, symbols=None):
        return [{"symbol": "AAPL", "signal": "均线多头排列"}]

    def history(self, symbol, limit, bar_size="1d"):
        return [{"symbol": symbol.upper(), "bar_size": bar_size, "close_price": 250}]

    def chart_history(self, symbol, limit=260):
        return [{"symbol": symbol.upper(), "close_price": 250}]

    def intraday_history(self, symbol, limit=600):
        return [{"symbol": symbol.upper(), "close_price": 251}]

    def segments(self, symbol, date=None):
        return [{"symbol": symbol.upper(), "seg_no": 1, "direction": "up", "change_pct": 1.2}]

    def segment_dates(self, symbol):
        return [{"trade_date": "2026-09-04"}]

    def large_trades(self, symbol, date=None, min_notional=None, limit=500):
        return [{"symbol": symbol.upper(), "notional": 500000, "side_inferred": "buy"}]

    def market_events(self, symbol=None, limit=100):
        return [{"symbol": symbol or "NVDA", "event_type": "large_trade"}]

    def news(self, symbols=None, limit=60):
        return [{"symbol": (symbols or ["AAPL"])[0], "headline": "x", "themes": ["semis"]}]

    def recent_earnings(self, limit=8):
        return [{"symbol": "AVGO", "report_date": "2026-09-02"}][:limit]

    def latest_fundamentals(self, symbol):
        return {"symbol": symbol.upper(), "pe_ttm": 25.4}

    def earnings_history(self, symbol):
        return [{"symbol": symbol.upper(), "fiscal_period": "Q2"}]

    def sentiment_summary(self, symbol):
        return {"symbol": symbol.upper(), "score": 18.5, "label": "中性"}

    def option_wall(self, symbol):
        return []

    def latest_reviews(self, symbol=None):
        return [{"symbol": symbol or "NVDA", "score": 45}]

    def investment_overview(self, symbol):
        return {
            "symbol": symbol.upper(),
            "technical": {"signal": "均线多头排列"},
            "sentiment": self.sentiment_summary(symbol),
            "valuation": self.latest_fundamentals(symbol),
            "earnings": self.earnings_history(symbol),
        }

    def sync_status(self):
        return {"status": "success"}

    def market_impact(self, days=14):
        return {"macro": [], "macro_unanalyzed": [], "upcoming": [], "news_themes": []}

    def replay_day(self, date):
        return {"date": date, "reviews": [], "segments_summary": [], "segments": [],
                "events": [], "macro": []}

    def daily_range(self, symbol, start, end):
        return {"symbol": symbol.upper(), "bars": [], "stats": None}

    def events_between(self, start, end, symbol=None, limit=300):
        return []

    def macro_events_between(self, start, end):
        return self.macro

    def store_macro_event(self, event):
        self.macro.append(event)

    def ingest(self, payload):
        return {}


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api, "database", FakeDatabase())
    return TestClient(api.app)


def test_health(monkeypatch):
    response = client(monkeypatch).get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "connected"


def test_pages_render(monkeypatch):
    c = client(monkeypatch)
    for path in ("/", "/stock/NVDA", "/replay", "/settings"):
        assert c.get(path).status_code == 200, path
    assert c.get("/live", follow_redirects=False).status_code == 307
    assert c.get("/review", follow_redirects=False).status_code == 307


def test_watchlist_from_database(monkeypatch):
    response = client(monkeypatch).get("/api/watchlist")
    assert [row["symbol"] for row in response.json()] == [row["symbol"] for row in WATCH]


def test_watchlist_add_and_remove(monkeypatch):
    fake = FakeDatabase()
    monkeypatch.setattr(api, "database", fake)
    c = TestClient(api.app)
    assert c.post("/api/watchlist", json={"symbol": "bad symbol"}).status_code == 400
    response = c.post("/api/watchlist", json={"symbol": "amd", "themes": ["semis"]})
    assert response.status_code == 201
    assert fake.added[0]["symbol"] == "AMD"
    assert c.delete("/api/watchlist/AMD").json()["status"] == "deactivated"
    assert fake.deactivated == ["AMD"]


def test_market_group(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/api/market/snapshot?symbols=NVDA").json()[0]["symbol"] == "NVDA"
    assert c.get("/api/market/signals").json()[0]["signal"] == "VWAP上方"
    assert c.get("/api/market/technicals").json()[0]["signal"] == "均线多头排列"
    assert c.get("/api/market/impact").json()["macro"] == []


def test_stock_group(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/api/stock/NVDA/history").json()[0]["bar_size"] == "1d"
    assert c.get("/api/stock/NVDA/segments").json()["segments"][0]["direction"] == "up"
    assert c.get("/api/stock/NVDA/large-trades").json()[0]["side_inferred"] == "buy"
    assert c.get("/api/stock/MU/overview").json()["valuation"]["pe_ttm"] == 25.4
    assert c.get("/api/stock/NVDA/reviews").json()[0]["score"] == 45


def test_replay_endpoints(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/api/replay/day?date=2026-09-04").json()["date"] == "2026-09-04"
    assert c.get("/api/replay/day?date=bad").status_code == 400
    body = c.get("/api/replay/range?symbol=NVDA&from=2026-09-01&to=2026-09-05").json()
    assert body["symbol"] == "NVDA"


def test_macro_events(monkeypatch):
    fake = FakeDatabase()
    monkeypatch.setattr(api, "database", fake)
    c = TestClient(api.app)
    assert c.post("/api/macro/events", json={"event_type": "nfp"}).status_code == 400
    response = c.post(
        "/api/macro/events",
        json={"event_type": "nfp", "event_time": "2026-09-04T12:30:00+00:00",
              "name": "非农", "actual": 142, "consensus": 160, "surprise": "below"},
    )
    assert response.status_code == 200
    assert c.get("/api/macro/events").json()[0]["name"] == "非农"
