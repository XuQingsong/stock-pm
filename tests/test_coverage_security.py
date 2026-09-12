from __future__ import annotations

import json
from pathlib import Path

from stock_pm.series import FRED_MARKET_SERIES


SECRET_MARKERS = ("api_key", "apikey", "secret", "password", "authorization", "sk-", "Bearer ")


def test_recorded_fixtures_have_no_secrets_or_live_claim():
    for spec in FRED_MARKET_SERIES.values():
        text = Path(spec["fixture"]).read_text()
        lowered = text.lower()
        for marker in SECRET_MARKERS:
            assert marker not in lowered, (spec["fixture"], marker)
        payload = json.loads(text)
        assert "recorded fixture" in payload["label"]
        assert "not a live" in payload["label"]


def test_schema_has_quarantine_and_no_hardcoded_keys():
    schema = Path("src/stock_pm/sql/schema.sql").read_text()
    lowered = schema.lower()
    for marker in ("api_key", "secret_key", "password="):
        assert marker not in lowered
    assert "CREATE TABLE IF NOT EXISTS price_bar_quarantine" in schema
    assert "DELETE FROM price_bars" not in schema


def test_env_examples_do_not_embed_real_keys():
    for path in (Path(".env.example"), Path(".env.server.example")):
        text = path.read_text()
        assert "your_" in text
        assert "sk-" not in text
