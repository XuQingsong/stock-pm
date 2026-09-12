from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_pm.bars import decorate_bar
from stock_pm.config import DEFAULT_DATABASE_URL, redact_database_url
from stock_pm.database import Database
from stock_pm.decision.health import build_data_health
from stock_pm.migrate import discover_migrations, migrate
from stock_pm.persist_live import persist_daily_bars, persist_earnings, persist_macro_events, readback_daily_bar, readback_earnings, readback_nfp
from stock_pm.series import decorate_macro_row


def postgres_or_skip() -> Database:
    db = Database()
    if not db.ping():
        db.close()
        pytest.skip("PostgreSQL is not reachable")
    db.initialize()
    return db


def test_redact_database_url_hides_password():
    redacted = redact_database_url(DEFAULT_DATABASE_URL)
    assert "***" in redacted
    assert "stock_pm_dev" not in redacted
    assert "stock_pm" in redacted
    assert "localhost" in redacted


def test_discover_migrations_starts_with_schema_sql():
    items = discover_migrations()
    assert items[0].version == "0001_initial"
    assert items[0].filename == "schema.sql"
    assert "CREATE TABLE IF NOT EXISTS price_bars" in items[0].sql
    assert items[0].checksum


def test_postgres_connect_and_migrate_pass():
    db = postgres_or_skip()
    try:
        report = migrate(db.settings)
        assert report["status"] == "ok"
        assert "0001_initial" in report["verify"]["present"]
        assert report["verify"]["missing"] == []
        again = migrate(db.settings)
        assert again["status"] == "ok"
        assert "0001_initial" in again["apply"]["skipped"]
        assert "***" in report["database"]
        assert "stock_pm_dev" not in report["database"]
    finally:
        db.close()


def test_idempotent_bar_and_earnings_writes_and_rerun():
    db = postgres_or_skip()
    try:
        captured = "2026-09-12T12:00:00+00:00"
        bars = [
            decorate_bar(
                {
                    "symbol": "NVDA",
                    "bar_time": "2026-09-11T20:00:00+00:00",
                    "open_price": 217.0,
                    "high_price": 219.5,
                    "low_price": 216.0,
                    "close_price": 218.29,
                    "volume": 1000,
                },
                fetched_at=captured,
                source="alpaca_sip",
            )
        ]
        earnings = [
            {
                "symbol": "NVDA",
                "report_date": "2026-08-26",
                "fiscal_period": "Q2",
                "eps_actual": 2.22,
                "eps_estimate": 2.09,
                "source": "fmp",
            }
        ]
        first = persist_daily_bars(db, "NVDA", bars, captured_at=captured, source="alpaca_sip")
        second = persist_daily_bars(db, "NVDA", bars, captured_at=captured, source="alpaca_sip")
        assert first["bars"] == 1
        assert second["bars"] == 1
        persist_earnings(db, "NVDA", earnings, captured_at=captured, source="fmp")
        persist_earnings(db, "NVDA", earnings, captured_at=captured, source="fmp")
        bar = readback_daily_bar(db, "NVDA")
        earn = readback_earnings(db, "NVDA")
        assert bar is not None
        assert str(bar["source"]).startswith("alpaca_sip")
        assert bar["as_of"] == "2026-09-11"
        assert float(bar["close_price"]) == 218.29
        assert bar["status"] == "ok"
        assert earn is not None
        assert earn["source"] == "fmp"
        assert float(earn["eps_actual"]) == 2.22
        assert float(earn["eps_estimate"]) == 2.09
        count = db.fetch_all(
            "SELECT COUNT(*) AS n FROM price_bars WHERE symbol = %s AND bar_size = '1d' AND bar_time = %s",
            ("NVDA", "2026-09-11T20:00:00+00:00"),
        )[0]["n"]
        assert int(count) == 1
    finally:
        db.close()


def test_nfp_persist_readback_and_stale_freshness():
    db = postgres_or_skip()
    try:
        fresh = {
            "event_type": "nfp",
            "event_time": "2026-08-01T00:00:00+00:00",
            "name": "NFP",
            "actual": 220.0,
            "unit": "thousands",
            "source": "FRED",
            "notes": (
                '{"series_or_symbol":"PAYEMS","as_of":"2026-08-01",'
                '"fetched_at":"2026-09-05T12:30:00+00:00","unit":"thousands",'
                '"frequency":"monthly","status":"ok","source":"FRED"}'
            ),
        }
        persist_macro_events(db, [fresh])
        row = readback_nfp(db)
        assert row is not None
        assert row["event_type"] == "nfp"
        assert float(row["value"]) == 220.0
        assert row["as_of"] == "2026-08-01"
        assert row["status"] == "ok"
        assert row["source"] == "FRED"

        stale_time = (datetime.now(timezone.utc) - timedelta(days=80)).replace(microsecond=0)
        stale = {
            "event_type": "nfp_freshness_probe",
            "event_time": stale_time.isoformat(),
            "name": "stale probe",
            "actual": 1.0,
            "unit": "thousands",
            "source": "FRED",
            "notes": (
                '{"series_or_symbol":"PAYEMS","as_of":"%s",'
                '"fetched_at":"%s","observed_at":"%s","unit":"thousands",'
                '"frequency":"monthly","status":"ok","source":"FRED"}'
                % (stale_time.date().isoformat(), stale_time.isoformat(), stale_time.isoformat())
            ),
        }
        persist_macro_events(db, [stale])
        recent_bar = decorate_bar(
            {
                "symbol": "NVDA",
                "bar_time": "2026-09-11T20:00:00+00:00",
                "open_price": 217.0,
                "high_price": 219.5,
                "low_price": 216.0,
                "close_price": 218.29,
                "volume": 1000,
            },
            fetched_at="2026-09-12T12:00:00+00:00",
            source="alpaca_sip",
        )
        nfp_like = build_data_health(
            {
                "symbol": "NVDA",
                "bars": [recent_bar],
                "earnings": [],
                "macro_events": [decorate_macro_row({**stale, "event_type": "nfp"})],
                "synthetic": False,
            }
        )
        nfp = {row["dataset"]: row for row in nfp_like["datasets"]}["macro_nfp"]
        assert nfp["status"] == "stale"
        assert nfp["reason_code"] == "record_stale"
    finally:
        db.close()


def test_reconnect_after_disconnect():
    db = postgres_or_skip()
    try:
        assert db.ping() is True
        db.close()
        assert db.ping() is False
        assert db.reconnect() is True
        assert db.ping() is True
        rows = db.fetch_all("SELECT 1 AS ok")
        assert rows[0]["ok"] == 1
    finally:
        db.close()
