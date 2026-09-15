"""Frozen decision-system pack: mapping, strength, overview, review split."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_pm.events.dedupe import build_events
from stock_pm.events.types import EventDocument
from stock_pm.pack.cards import event_card, focus_rows
from stock_pm.pack.copy import HOLDINGS_BANNED, strip_holdings
from stock_pm.pack.mapping import map_event, map_news_to_watchlist
from stock_pm.pack.overview import build_overview_payload
from stock_pm.pack.review_page import build_review_payload, is_formal
from stock_pm.pack.stock_page import build_stock_payload
from stock_pm.pack.strength import grade_impact
from stock_pm.prediction import synthesize_prediction


WATCH = [
    {"symbol": "NVDA", "name": "NVIDIA", "themes": ["semis", "high_valuation_growth"], "rate_sensitivity": "high", "active": True},
    {"symbol": "AVGO", "name": "Broadcom", "themes": ["semis"], "rate_sensitivity": "high", "active": True},
    {"symbol": "XOM", "name": "Exxon", "themes": ["energy", "oil_producer"], "rate_sensitivity": "low", "active": True},
    {"symbol": "AAPL", "name": "Apple", "themes": ["consumer_electronics"], "rate_sensitivity": "medium", "active": True},
]


def _energy_event():
    docs = [
        EventDocument(
            title="EIA reports crude inventory build",
            url="https://www.eia.gov/pressroom/releases/press000",
            publisher="EIA",
            published_at="2026-09-14T14:00:00+00:00",
            event_type="energy_supply",
            entities=["EIA", "oil", "crude"],
            countries=["US"],
            claims=["crude inventory"],
            body="EIA reported a crude oil inventory build.",
            status="active",
        )
    ]
    return build_events(docs)[0]


def test_mapping_is_channel_not_headline_paste():
    event = _energy_event()
    mapped = {row["symbol"]: row for row in map_event(event, WATCH)}
    assert "XOM" in mapped
    assert mapped["XOM"]["channel"] == "commodity_revenue"
    assert mapped["XOM"]["mechanism"]
    assert mapped["XOM"]["why_relevant"]
    assert "AAPL" not in mapped
    assert "NVDA" not in mapped or mapped["NVDA"]["channel"] != "commodity_revenue"


def test_news_does_not_paste_other_tickers_from_headline():
    item = {
        "symbol": "NVDA",
        "headline": "AVGO and MSFT mentioned in passing while NVDA reports orders",
        "themes": ["semis"],
    }
    rows = map_news_to_watchlist(item, WATCH)
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["NVDA"]["mechanism"] == "watchlist_ingested_article"
    assert "AVGO" in by_symbol
    assert by_symbol["AVGO"]["mechanism"] == "watchlist_theme_intersection"
    assert "标题" in by_symbol["AVGO"]["why_relevant"] or "主题" in by_symbol["AVGO"]["why_relevant"]
    assert "MSFT" not in by_symbol


def test_strength_does_not_paint_deep_without_evidence():
    weak = grade_impact(side="bull", hit=None, closed_loop=False, withheld=True)
    assert weak["kind"] == "gray"
    strong = grade_impact(
        side="bull",
        hit={"channel": "company", "mechanism": "company_filing"},
        closed_loop=True,
        confidence="high",
    )
    assert strong["kind"] == "deep-green"
    yellow = grade_impact(side="watch", hit={"channel": "duration", "mechanism": "inflation_to_rates_to_discount"}, conflict=True)
    assert yellow["kind"] == "yellow"


def test_overview_features_mapped_event_and_groups_focus():
    event = _energy_event()
    payload = build_overview_payload(
        watch=WATCH,
        events=[event],
        briefing={"rows": [{"symbol": "XOM", "env_half": "能源短线波动", "attention": {"key": "rest"}}]},
    )
    assert payload["featured"] is not None
    assert payload["featured"]["mapped"] is True
    symbols = {row["symbol"] for row in payload["featured"]["tickers"]}
    assert "XOM" in symbols
    skip_symbols = {row["symbol"] for row in payload["focus"]["skip"]}
    assert "AAPL" in skip_symbols
    assert payload["focus"]["skip_count"] >= 1


def test_empty_events_are_honest():
    payload = build_overview_payload(watch=WATCH, events=[], briefing={"rows": []})
    assert payload["featured"] is None
    assert payload["featured_missing"]
    assert "墙" not in payload["featured_missing"]


def test_stock_page_has_five_sections_and_thesis_change():
    payload = build_stock_payload(
        symbol="NVDA",
        watch=WATCH,
        briefing_row={"symbol": "NVDA", "env_half": "研究倾向偏多"},
        events=[],
        environment={"one_liner": "消息：行业利多；因此：近端偏多", "as_of_date": "2026-09-15"},
        env_history=[
            {"as_of_date": "2026-09-15", "one_liner": "消息：行业利多；因此：近端偏多"},
            {"as_of_date": "2026-09-14", "one_liner": "中性偏多 / 等指引确认"},
        ],
        tape={},
        prediction={"state": "active", "thesis": "因此：两周内补涨"},
        decision={"thesis": {"direction": "bullish", "invalidation": "指引下修"}},
    )
    assert payload["judge"]["actions"]
    assert "减仓" not in payload["judge"]["stance"]
    assert payload["thesis_change"]["changed"] is True
    assert payload["thesis_change"]["midterm"]["unchanged"] is True
    assert payload["observe"]
    assert payload["invalidate"]


def test_review_splits_formal_and_observation():
    formal = synthesize_prediction(
        as_of_date="2026-09-08",
        symbol="NVDA",
        environment={"publishState": "published", "one_liner": "环境偏多", "struct": {"sentiment": {"atmosphere": "补涨"}}},
        tape={
            "publishState": "published",
            "volume_price": {"form": "放量涨"},
            "chips": {"close": 100, "support": 95, "resistance": 110},
            "env_link": {"judgment": "吸筹"},
        },
        review_note={"unexplained": False},
        entry_price=100,
    )
    assert is_formal(formal) is True
    observe = {
        "symbol": "MU",
        "state": "missing",
        "prediction_ready": False,
        "thesis": "弱偏多",
    }
    payload = build_review_payload(
        watch=[{"symbol": "NVDA"}, {"symbol": "MU"}],
        predictions={"NVDA": [formal], "MU": [observe]},
        checks={},
        today=date(2026, 9, 15),
    )
    assert payload["formal"]
    assert payload["formal"][0]["symbol"] == "NVDA"
    assert payload["learning"]
    assert payload["observations"]
    assert payload["observations"][0]["symbol"] == "MU"


def test_news_never_becomes_featured_main_event():
    payload = build_overview_payload(
        watch=WATCH,
        events=[],
        briefing={"rows": []},
        news=[
            {
                "symbol": "NVDA",
                "headline": "AVGO and MSFT mentioned while NVDA reports orders",
                "themes": ["semis"],
                "url": "https://example.com/nvda-orders",
                "summary": "订单超预期",
            }
        ],
    )
    assert payload["featured"] is None
    assert payload["featured_missing"]
    titles = [card["title"] for card in payload["carousel"]]
    assert any("订单" in title or "相关新闻" in title for title in titles) or payload["carousel"]
    blob = " ".join(titles)
    assert "AVGO and MSFT" not in blob
    assert "reports orders" not in blob
    mapped_symbols = {row["symbol"] for card in payload["carousel"] for row in card.get("tickers") or []}
    assert "NVDA" in mapped_symbols
    assert "MSFT" not in mapped_symbols
    watch_symbols = {row["symbol"] for row in payload["focus"]["watch"]}
    assert "NVDA" in watch_symbols


def test_copy_and_ui_forbid_holdings_and_jargon():
    assert "研究倾向" in strip_holdings("建议减仓观察")
    files = [
        Path("src/stock_pm/static/overview.html"),
        Path("src/stock_pm/static/review.html"),
        Path("src/stock_pm/static/desk.js"),
    ]
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for phrase in HOLDINGS_BANNED:
        assert phrase not in blob
    for phrase in ("PredictionCheck", "重评队列", "A层", "L0"):
        assert phrase not in Path("src/stock_pm/static/overview.html").read_text(encoding="utf-8")
        assert phrase not in Path("src/stock_pm/static/review.html").read_text(encoding="utf-8")
        assert phrase not in Path("src/stock_pm/static/desk.js").read_text(encoding="utf-8")


def test_overview_assemble_does_not_block_on_cold_event_book(monkeypatch):
    import time

    from stock_pm.events import service
    from stock_pm.pack.assemble import build_overview

    called = {"build": 0}

    def hang():
        called["build"] += 1
        time.sleep(30)
        return []

    monkeypatch.setattr(service, "build_event_book", hang)
    monkeypatch.setattr(service, "peek_event_book", lambda: None)
    monkeypatch.setattr(service, "kick_event_book_warm", lambda: None)

    class DB:
        def watchlist_rows(self):
            return WATCH

        def briefing(self, date=None, *, live_synthesize=True):
            assert live_synthesize is False
            return {"rows": [{"symbol": "XOM", "env_half": "观察"}]}

        def news(self, limit=40):
            return []

        def latest_snapshots(self):
            return [{"symbol": "XOM"}]

    start = time.monotonic()
    payload = build_overview(DB())
    elapsed = time.monotonic() - start
    assert elapsed < 2
    assert called["build"] == 0
    assert payload["featured"] is None
    assert payload["gaps"]["events"] is True
    assert payload["diagnostics"]["warming"] is True


def test_review_assemble_skips_missing_prediction_placeholders(monkeypatch):
    from stock_pm.events import service
    from stock_pm.pack.assemble import build_review

    monkeypatch.setattr(service, "peek_event_book", lambda: [])
    monkeypatch.setattr(service, "kick_event_book_warm", lambda: None)

    class DB:
        def watchlist_rows(self):
            return WATCH

        def briefing(self, date=None, *, live_synthesize=True):
            return {"rows": []}

        def prediction_history(self, symbol, limit=8):
            return []

        def prediction_payload(self, date=None, symbol=None, *, live_fallback=True):
            return {"state": "missing", "prediction_ready": False, "symbol": symbol}

        def prediction_checks(self, prediction_id, limit=8):
            return []

    payload = build_review(DB())
    assert payload["observations"] == []
    assert payload["formal"] == []
