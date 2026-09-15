"""Desk APIs must not hang the worker when live discovery blocks."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.events.budget import BudgetTimeout, call_with_timeout, discovery_budget
from stock_pm.events.feeds import fetch_feed
from stock_pm.events.service import reset_cache
from test_api import FakeDatabase, client as api_client


def _hang(*_args, **_kwargs):
    time.sleep(5)
    return []


def _short_budget(monkeypatch) -> None:
    monkeypatch.setattr("stock_pm.events.budget.PROVIDER_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("stock_pm.events.budget.OVERALL_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr("stock_pm.events.budget.DESK_ASSEMBLE_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr("stock_pm.events.budget.DEGRADED_COOLDOWN_SECONDS", 30.0)


def _empty_mode(_settings=None) -> str:
    return "empty"


def _hanging_discover(monkeypatch) -> TestClient:
    reset_cache()
    _short_budget(monkeypatch)
    # Production default is empty; pytest otherwise forces fixture documents.
    for target in (
        "stock_pm.events.policy.events_data_mode",
        "stock_pm.events.service.events_data_mode",
        "stock_pm.events.providers.events_data_mode",
        "stock_pm.events.live.events_data_mode",
    ):
        monkeypatch.setattr(target, _empty_mode)
    monkeypatch.setattr("stock_pm.events.service.discover_live_documents", _hang)
    monkeypatch.setattr("stock_pm.events.providers.OfficialFeedProvider.discover", lambda self, *a, **k: [])
    monkeypatch.setattr(api, "database", FakeDatabase())
    monkeypatch.setattr("stock_pm.series.collect_live_macro_overlay", lambda *a, **k: {})
    return TestClient(api.app)


def test_call_with_timeout_raises_on_hang():
    start = time.monotonic()
    try:
        call_with_timeout(_hang, 0.15)
        raise AssertionError("expected BudgetTimeout")
    except BudgetTimeout:
        pass
    assert time.monotonic() - start < 1.0


def test_fetch_feed_returns_timeout_when_budget_exhausted(monkeypatch):
    def _must_not_open(*_args, **_kwargs):
        raise AssertionError("fetch_feed must not open a socket after the budget expires")

    monkeypatch.setattr("stock_pm.events.feeds._OPENER.open", _must_not_open)
    with discovery_budget(overall=0.05, provider=0.05):
        time.sleep(0.08)
        resp = fetch_feed("https://www.federalreserve.gov/feeds/press_all.xml", user_agent="stock-pm-test")
    assert resp.error == "timeout"
    assert not resp.ok


def test_desk_overview_returns_quickly_when_discover_hangs(monkeypatch):
    c = _hanging_discover(monkeypatch)
    start = time.monotonic()
    response = c.get("/api/desk/overview")
    elapsed = time.monotonic() - start
    assert response.status_code == 200
    assert elapsed < 2.0
    payload = response.json()
    assert payload["page"]["title"] == "今天什么改变了"
    assert payload["featured"] is None
    assert payload["gaps"]["events"] is True
    assert payload["diagnostics"]["data_mode"] in {"degraded", "empty"}
    assert payload["diagnostics"]["live"] is False
    assert payload["diagnostics"]["event_count"] == 0
    reset_cache()


def test_desk_stock_returns_quickly_when_discover_hangs(monkeypatch):
    c = _hanging_discover(monkeypatch)
    start = time.monotonic()
    response = c.get("/api/desk/stock/NVDA")
    elapsed = time.monotonic() - start
    assert response.status_code == 200
    assert elapsed < 2.0
    payload = response.json()
    assert payload["symbol"] == "NVDA"
    assert "judge" in payload
    assert payload.get("events") == [] or payload.get("events") is not None
    reset_cache()


def test_desk_review_returns_quickly_when_discover_hangs(monkeypatch):
    c = _hanging_discover(monkeypatch)
    start = time.monotonic()
    response = c.get("/api/desk/review")
    elapsed = time.monotonic() - start
    assert response.status_code == 200
    assert elapsed < 2.0
    payload = response.json()
    assert "formal" in payload
    assert "observations" in payload
    assert "learning" in payload
    reset_cache()


def test_desk_shape_unchanged_when_discovery_is_fast(monkeypatch):
    c = api_client(monkeypatch)
    overview = c.get("/api/desk/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "featured" in body
    assert "focus" in body
    assert set(body["focus"]) >= {"priority", "watch", "skip", "skip_count"}
