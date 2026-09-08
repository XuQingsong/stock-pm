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
        self.patched = None

    def ping(self):
        return True

    def initialize(self):
        return None

    def watchlist_rows(self, include_inactive=False):
        return WATCH

    def active_symbols(self):
        return [row["symbol"] for row in WATCH]

    def _watchlist_symbol(self, symbol):
        return symbol.upper()

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

    def chart_history(self, symbol, limit=260, interval="1d"):
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "bars": [{"symbol": symbol.upper(), "close_price": 250, "ma5": None, "ma20": None, "ma50": None, "ma200": None}],
            "as_of": None,
            "source": "test",
            "delayed": interval in {"1m", "5m", "15m", "60m"},
            "daily_ma": {"ma50": 240, "ma200": 200},
        }

    def earnings_summary_view(self, symbol):
        return {
            "latest": {"symbol": symbol.upper(), "eps_actual": 1.2, "fiscal_period": "Q2"},
            "history": [{"symbol": symbol.upper(), "eps_actual": 1.2}],
            "highlights": ["EPS实际值高于市场预期"],
            "avg_abs_move_pct": 2.5,
            "provider": {"name": "fmp", "status": "ok", "message": "ok"},
        }

    def valuation_history(self, symbol, limit=260):
        return {
            "current": {"symbol": symbol.upper(), "pe_ttm": 25.4},
            "series": [{"captured_at": "2026-01-01", "pe_ttm": 20}],
            "metrics": {"pe_percentile": 80, "pe_low": 18, "pe_high": 30, "samples": 12},
            "coverage": {"count": 12, "band_ready": True},
        }

    def volume_profile_view(self, symbol, lookback=60):
        return {
            "buckets": [{"price": 100, "volume": 1, "volume_pct": 100}],
            "poc": 100,
            "lookback": lookback,
            "basis": "OHLCV估算",
        }

    def capital_flow_view(self, symbol, days=5):
        return {
            "tiers": [{"name": "100万以上", "count": 1, "net_notional": 10}],
            "timeline": [],
            "cmf20": 0.1,
            "disclaimer": "估算",
        }

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
        return {"symbol": symbol.upper(), "interval": "1m", "bars": [], "stats": None}

    def events_between(self, start, end, symbol=None, limit=300):
        return []

    def reviews_between(self, symbol, start, end):
        return [{
            "symbol": symbol.upper(), "review_date": start, "score": 45,
            "summary": "测试复盘", "short_trend": "偏多", "medium_trend": "资金流代理略偏正",
            "long_trend": "位于价值区", "support_price": 100, "resistance_price": 110,
            "breakout_status": "区间震荡",
        }]

    def segments_between(self, symbol, start, end):
        return [{"symbol": symbol.upper(), "seg_no": 1, "direction": "up", "change_pct": 1.2,
                 "start_time": f"{start}T13:30:00+00:00", "end_time": f"{start}T14:00:00+00:00",
                 "rel_volume": 1.5, "vwap_side": "above", "large_buy_notional": 1000000,
                 "large_sell_notional": 200000, "large_trade_count": 3}]

    def macro_events_between(self, start, end):
        return self.macro

    def store_macro_event(self, event):
        self.macro.append(event)

    def ingest(self, payload):
        return {}

    def latest_review_date(self):
        return "2026-09-04"

    def latest_bar_date(self):
        return "2026-09-04"

    def default_review_date(self):
        return "2026-09-04"

    def market_session(self, trade_date=None):
        day = trade_date or "2026-09-04"
        closed = day in {"2026-09-05", "2026-09-06", "2026-09-07"}
        return {
            "date": day,
            "is_trading_day": not closed,
            "status": "closed" if closed else "reviewed",
            "reason": "holiday" if day == "2026-09-07" else ("weekend" if closed else "trading"),
            "holiday_name": "劳动节" if day == "2026-09-07" else None,
            "label": "劳动节，美股休市" if day == "2026-09-07" else None,
            "last_trading_date": "2026-09-04",
            "default_review_date": "2026-09-04",
            "has_reviews": not closed,
            "review_count": 0 if closed else 9,
        }

    def reviews_by_date(self, date):
        return []

    def cboe_option_stats(self, trade_date=None):
        return {
            "trade_date": trade_date or "2026-09-04",
            "total_volume": 14248726,
            "total_put_call": 0.76,
            "total_call_put": 1.316,
            "buckets": [
                {"key": "index", "label": "指数期权", "volume": 6282484, "volume_pct": 44.1, "put_call": 0.89, "call_put": 1.124},
                {"key": "equity", "label": "个股期权", "volume": 5035169, "volume_pct": 35.3, "put_call": 0.58, "call_put": 1.724},
                {"key": "etp", "label": "ETF期权", "volume": 2931073, "volume_pct": 20.6, "put_call": 0.85, "call_put": 1.176},
            ],
            "vix_put_call": 0.21,
            "spx_put_call": 1.15,
            "source": "cboe",
            "disclaimer": "来源 Cboe",
        }

    def briefing(self, date=None):
        session = self.market_session(date)
        if not session["is_trading_day"]:
            return {
                "date": date or session["date"],
                "session": session,
                "has_reviews": False,
                "rows": [],
                "hit_rate": {"all": {"samples": 0, "hits": 0, "rate_pct": None},
                             "loop": {"samples": 0, "hits": 0, "rate_pct": None},
                             "confirmed": {"samples": 0, "hits": 0, "rate_pct": None},
                             "confirm_required": False,
                             "by_symbol": {}},
                "confirm_required": False,
            }
        return {
            "date": date or "2026-09-04",
            "session": session,
            "has_reviews": True,
            "rows": [{
                "symbol": "NVDA",
                "health": "趋势健康",
                "ma_position": "MA20上方 · MA50上方 · MA200上方",
                "volume_ratio_20d": 1.2,
                "return_5d_pct": 3.1,
                "breakout_status": "区间内",
                "has_review": True,
                "llm_status": "missing_key",
                "prior_outcome": {"outcome_vs_bias": "符合", "bias": "偏多"},
            }],
            "hit_rate": {
                "all": {"samples": 2, "hits": 1, "rate_pct": 50.0},
                "loop": {"samples": 2, "hits": 1, "rate_pct": 50.0},
                "confirmed": {"samples": 0, "hits": 0, "rate_pct": None},
                "confirm_required": False,
                "by_symbol": {},
            },
            "confirm_required": False,
        }

    def shell_state(self, date=None, symbol=None):
        from stock_pm.philosophy import build_shell

        briefing = self.briefing(date)
        options = self.cboe_option_stats(date)
        symbol_env = self.environment_payload(date, symbol) if symbol else None
        payload = build_shell(
            briefing=briefing,
            options={"status": "ok", **options} if options else {"status": "missing"},
            snapshots=self.latest_snapshots([symbol] if symbol else None),
            impact=self.market_impact(),
            sync=self.sync_status(),
            symbol=symbol,
            symbol_environment=symbol_env,
        )
        if symbol:
            payload["tape"] = self.tape_payload(date, symbol)
            payload["review_note"] = self.review_note_payload(date, symbol)
        return payload

    def environment_payload(self, date=None, symbol=None):
        from stock_pm.environment import synthesize_symbol_environment
        from stock_pm.philosophy import synthesize_environment

        briefing = self.briefing(date)
        if not symbol:
            options = self.cboe_option_stats(date)
            return synthesize_environment(
                as_of_date=date or briefing.get("date"),
                briefing_rows=briefing.get("rows") or [],
                options={"status": "ok", **options} if options else {"status": "missing"},
                impact=self.market_impact(),
                session=briefing.get("session"),
            )
        row = next(
            (
                item
                for item in briefing.get("rows") or []
                if str(item.get("symbol") or "").upper() == symbol.upper()
            ),
            {"symbol": symbol, "health": "观察"},
        )
        return synthesize_symbol_environment(
            as_of_date=date or briefing.get("date") or "2026-09-04",
            symbol=symbol,
            technical=row,
            briefing_row=row,
            session=self.market_session(date),
        )

    def environment_history(self, symbol, limit=30):
        return []

    def _sample_tape(self, symbol, date=None):
        from stock_pm.tape import synthesize_review_note, synthesize_tape_analysis

        env = self.environment_payload(date, symbol)
        tape = synthesize_tape_analysis(
            as_of_date=date or "2026-09-04",
            symbol=symbol,
            metrics={
                "day_change_pct": 3.2,
                "relative_volume": 1.6,
                "tape": "放量上攻，收盘靠近最高价，买盘主导",
                "breakout": "放量有效突破",
                "support_test": "未测试最近支撑",
                "close_location": 0.82,
                "poc_60d": 118.5,
                "value_area_low": 110,
                "value_area_high": 125,
                "support": 116,
                "resistance": 128,
                "position": "大部分60日成交筹码处于浮盈区，趋势占优但需防获利回吐",
                "ma5": 120,
                "ma20": 118,
                "ma50": 115,
                "ma200": 100,
                "close": 122,
            },
            environment=env,
            session=self.market_session(date),
            source="test",
        )
        return tape

    def tape_payload(self, date=None, symbol=None):
        return self._sample_tape(symbol or "NVDA", date)

    def tape_history(self, symbol, limit=30):
        return []

    def review_note_payload(self, date=None, symbol=None):
        from stock_pm.tape import synthesize_review_note

        tape = self.tape_payload(date, symbol)
        return synthesize_review_note(
            as_of_date=date or "2026-09-04",
            symbol=symbol or "NVDA",
            tape=tape,
            environment=self.environment_payload(date, symbol),
            session=self.market_session(date),
            source="test",
        )

    def review_note_history(self, symbol, limit=30):
        return []

    def job_runs(self, limit=20):
        return []

    def update_review_user(self, symbol, review_date, body):
        self.patched = {"symbol": symbol, "review_date": review_date, **body}
        return self.patched


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api, "database", FakeDatabase())
    return TestClient(api.app)


def test_health(monkeypatch):
    response = client(monkeypatch).get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "connected"


def test_pages_render(monkeypatch):
    c = client(monkeypatch)
    for path in ("/", "/stock/NVDA", "/replay", "/review", "/settings"):
        assert c.get(path).status_code == 200, path
    review_page = c.get("/review").text
    assert "每日复盘" in review_page
    assert "模型额度已用尽" in review_page
    assert "当日休市，暂无复盘" in review_page
    assert "toISOString" not in review_page
    assert "期权市场概览" in c.get("/").text
    assert "stock-pm-cboe" not in c.get("/").text
    assert "stock-pm-review" not in c.get("/").text
    assert "stock-pm-flow" not in c.get("/review").text
    assert "保存确认" not in c.get("/review").text
    assert "尚未确认" not in c.get("/review").text
    assert "保存备注" in c.get("/review").text
    assert "自动循环" in c.get("/review").text
    assert c.get("/live", follow_redirects=False).status_code == 307


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
    options = c.get("/api/market/options-overview?date=2026-09-04").json()
    assert options["status"] == "ok"
    assert options["total_put_call"] == 0.76
    assert options["buckets"][0]["key"] == "index"
    overview = c.get("/api/market/options-overview?date=2026-09-04").json()
    assert overview["status"] == "ok"
    assert overview["total_put_call"] == 0.76
    assert c.get("/api/market/options-overview?date=bad").status_code == 400


def test_stock_group(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/api/stock/NVDA/history").json()[0]["bar_size"] == "1d"
    chart = c.get("/api/stock/NVDA/chart?interval=1d").json()
    assert chart["interval"] == "1d"
    assert chart["bars"][0]["close_price"] == 250
    assert c.get("/api/stock/NVDA/earnings/summary").json()["provider"]["name"] == "fmp"
    assert c.get("/api/stock/NVDA/valuation/history").json()["metrics"]["samples"] == 12
    assert c.get("/api/stock/NVDA/volume-profile").json()["poc"] == 100
    assert c.get("/api/stock/NVDA/capital-flow").json()["cmf20"] == 0.1
    assert c.get("/api/stock/NVDA/segments").json()["segments"][0]["direction"] == "up"
    assert c.get("/api/stock/NVDA/large-trades").json()[0]["side_inferred"] == "buy"
    assert c.get("/api/stock/MU/overview").json()["valuation"]["pe_ttm"] == 25.4
    assert c.get("/api/stock/NVDA/reviews").json()[0]["score"] == 45
    briefing = c.get("/api/briefing?date=2026-09-04").json()
    assert briefing["rows"][0]["health"] == "趋势健康"
    assert briefing["has_reviews"] is True
    assert briefing["confirm_required"] is False
    holiday = c.get("/api/briefing?date=2026-09-07").json()
    assert holiday["rows"] == []
    assert holiday["has_reviews"] is False
    assert holiday["session"]["reason"] == "holiday"
    assert holiday["session"]["last_trading_date"] == "2026-09-04"
    session = c.get("/api/market/session?date=2026-09-07").json()
    assert session["is_trading_day"] is False
    assert session["default_review_date"] == "2026-09-04"
    assert c.get("/api/market/session?date=bad").status_code == 400
    chart = c.get("/api/stock/NVDA/chart?interval=1m").json()
    assert chart["daily_ma"]["ma50"] == 240


def test_patch_review(monkeypatch):
    fake = FakeDatabase()
    monkeypatch.setattr(api, "database", fake)
    c = TestClient(api.app)
    response = c.patch(
        "/api/reviews/NVDA/2026-09-04",
        json={"user_bias": "偏多", "user_outlook": "守住支撑", "user_note": "量能尚可"},
    )
    assert response.status_code == 200
    assert fake.patched["symbol"] == "NVDA"
    assert fake.patched["user_bias"] == "偏多"
    assert c.patch("/api/reviews/NVDA/bad-date", json={"user_bias": "偏多"}).status_code == 400


def test_retry_llm_endpoint(monkeypatch):
    fake = FakeDatabase()
    monkeypatch.setattr(api, "database", fake)

    def fake_retry(database, review_date=None, symbol=None, llm_fn=None):
        fake.retried = {"date": review_date, "symbol": symbol}
        return {
            "date": review_date or "2026-09-04",
            "retried": [{"symbol": "NVDA", "llm_status": "ok"}],
            "quota_exhausted": False,
            "ok": 1,
        }

    monkeypatch.setattr(api, "retry_reviews_for_llm", fake_retry)
    c = TestClient(api.app)
    response = c.post("/api/reviews/retry-llm?date=2026-09-04&symbol=NVDA")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] == 1
    assert body["quota_exhausted"] is False
    assert body["briefing"]["rows"][0]["symbol"] == "NVDA"
    assert fake.retried["symbol"] == "NVDA"
    assert c.post("/api/reviews/retry-llm?date=bad").status_code == 400


def test_static_assets(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/static/app.css").status_code == 200
    assert c.get("/static/stock.js").status_code == 200
    html = c.get("/stock/AAPL").text
    assert 'data-tab="chart"' in html
    assert "/static/stock.js" in html


def test_replay_endpoints(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/api/replay/day?date=2026-09-04").json()["date"] == "2026-09-04"
    assert c.get("/api/replay/day?date=bad").status_code == 400
    body = c.get("/api/replay/range?symbol=NVDA&from=2026-09-01&to=2026-09-05").json()
    assert body["symbol"] == "NVDA"
    assert body["interval"] == "1m"
    assert body["reviews"][0]["score"] == 45
    assert body["segments"][0]["direction"] == "up"
    assert c.get("/api/replay/range?symbol=NVDA&from=2026-08-01&to=2026-09-05").status_code == 400


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


def test_shell_and_environment_endpoints(monkeypatch):
    c = client(monkeypatch)
    shell = c.get("/api/shell?date=2026-09-04").json()
    assert "explicit_state" in shell
    assert shell["explicit_state"]["code"] in {"face_slap", "overdue", "missing", "clear"}
    assert shell["explicit_state"]["prediction_ready"] is False
    assert "environment" in shell
    assert shell["environment"]["publishState"] in {"published", "draft", "stale", "missing"}
    assert "missingFlags" in shell["environment"]
    env = c.get("/api/environment?date=2026-09-04").json()
    assert env["one_liner"]
    assert env["prediction_ready"] is False
    symbol_env = c.get("/api/environment?date=2026-09-04&symbol=NVDA").json()
    assert symbol_env["scope"] == "symbol"
    assert symbol_env["symbol"] == "NVDA"
    assert "struct" in symbol_env
    assert "missingFlags" in symbol_env
    history = c.get("/api/environment/history?symbol=NVDA")
    assert history.status_code == 200
    assert history.json() == []
    assert c.get("/api/jobs").status_code == 200
    symbol_shell = c.get("/api/shell?date=2026-09-04&symbol=NVDA").json()
    assert symbol_shell["tape"]["symbol"] == "NVDA"
    assert symbol_shell["tape"]["volume_price"]["form"]
    assert symbol_shell["review_note"]["summary"]
    assert symbol_shell["review_note"]["prediction_ready"] is False
    assert c.get("/api/shell?date=bad").status_code == 400


def test_static_shell_assets(monkeypatch):
    c = client(monkeypatch)
    js = c.get("/static/shell.js")
    assert js.status_code == 200
    assert "zone-b" in js.text
    assert "折叠材料" in js.text
    assert c.get("/static/shell.css").status_code == 200
    home = c.get("/").text
    assert 'id="stock-pm-shell"' in home
    assert "/static/shell.js" in home
    assert home.index('id="stock-pm-shell"') < home.index('id="rows"')
    assert home.index('id="rows"') < home.index('id="options-panel"')
    assert home.index('id="rows"') < home.index('id="news-mapped"')
    assert home.index('id="rows"') < home.index('id="impact-panel"')
    assert '折叠材料' in home
    options_at = home.index('id="options-panel"')
    fold_at = home.index('data-zone="C"')
    assert fold_at < options_at
    tag_end = home.index(">", home.index('<details class="fold zone-c materials"'))
    assert "open" not in home[home.index("<details class=\"fold zone-c materials\"") : tag_end]
    assert "<details" in js.text and 'data-zone="C"' in js.text
    assert "<details open" not in js.text
    assert "→ 支撑结论" in js.text
    assert 'data-zone="A"' in js.text
    assert '预测状态机尚未接入' in home
    assert "watch_low" not in home
    assert "face_slap" not in home
    assert "昨盘半句" in home
    assert "昨盘结论未就绪（M2）" in home
    assert "折叠材料" in home
    js = c.get("/static/shell.js").text
    assert 'data-zone="tape"' in js
    assert 'data-zone="review"' in js
    assert "预测状态机尚未接入，不编时间窗口或涨跌边界" in js
    assert "MA5/20/50/200" in js
    stock = c.get("/stock/NVDA").text
    assert 'id="stock-pm-shell"' in stock


def test_tape_and_review_note_endpoints(monkeypatch):
    c = client(monkeypatch)
    tape = c.get("/api/stock/NVDA/tape?date=2026-09-04").json()
    assert tape["symbol"] == "NVDA"
    assert tape["volume_price"]["form"] in {
        "放量涨", "缩量涨", "放量跌", "缩量跌", "平量涨", "平量跌", "量价平稳"
    }
    assert tape["prediction_ready"] is False
    assert "missingFlags" in tape
    assert c.get("/api/stock/NVDA/tape/history").json() == []
    notes = c.get("/api/stock/NVDA/review-notes?date=2026-09-04").json()
    assert notes and notes[0]["summary"]
    assert notes[0]["explanation"]
    assert "保存确认" not in c.get("/").text
    assert c.get("/api/stock/bad symbol/tape").status_code == 400
    assert c.get("/api/stock/NVDA/tape?date=bad").status_code == 400
