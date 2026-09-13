"""Keep unit tests isolated from a workspace .env live key."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_live_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "")
    monkeypatch.setenv("FMP_API_KEY", "")
    monkeypatch.setenv("STOCK_PM_EVENTS_LIVE", "0")
