"""Keep unit tests isolated from a workspace .env live key."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_alpha_vantage_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
