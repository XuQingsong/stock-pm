"""Idempotent incremental event ingest. Failures stay on the events chain."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from stock_pm.config import Settings
from stock_pm.database import Database

from .live import apply_cursor
from .policy import events_data_mode
from .service import build_event_book, coverage, reset_cache
from .store import load_cursors, persist_cursor, persist_events


LIVE_CURSOR_NAMES = (
    "sec_edgar",
    "federal_reserve",
    "eia_press",
    "official_feed",
    "google_cse",
    "alpha_vantage_earnings",
)


def _hydrate_cursors(conn) -> None:
    try:
        for name, row in load_cursors(conn).items():
            apply_cursor(name, etag=row.get("etag"), last_modified=row.get("last_modified"))
    except Exception:
        return


def run_event_job(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or Settings()
    reset_cache()
    persist_error = None
    persisted = 0
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    mode = events_data_mode(config)
    if mode == "recorded_replay":
        events = build_event_book(config, refresh=True)
        cover = coverage(config, events)
        return {
            "status": "ok",
            "persisted": 0,
            "coverage": cover,
            "job": "events_ingest",
            "idempotent": True,
            "persist_error": None,
            "persist_skipped": "recorded_replay",
            "affects_chain": "events",
        }
    db = None
    try:
        db = Database(config)
        with db.pool.connection() as conn:
            _hydrate_cursors(conn)
            try:
                from stock_pm.events.watchlist import apply_watchlist_rows

                apply_watchlist_rows(db.watchlist_rows())
            except Exception:
                pass
            events = build_event_book(config, refresh=True)
            cover = coverage(config, events)
            persisted = persist_events(conn, events, cover)
            providers = cover.get("providers") or {}
            for name in LIVE_CURSOR_NAMES:
                row = providers.get(name) or {}
                persist_cursor(
                    conn,
                    name,
                    status=str(row.get("status") or "idle"),
                    reason_code=row.get("reason_code"),
                    item_count=int(row.get("event_count") or 0),
                    stamp=stamp,
                    etag=row.get("etag"),
                    last_modified=row.get("last_modified"),
                    cursor_json={
                        "request_url": row.get("request_url"),
                        "live": row.get("live"),
                    },
                )
    except Exception as exc:
        persist_error = type(exc).__name__
        events = build_event_book(config, refresh=True)
        cover = coverage(config, events)
    finally:
        if db is not None:
            db.close()
    return {
        "status": "ok" if persist_error is None else "degraded",
        "persisted": persisted,
        "coverage": cover,
        "job": "events_ingest",
        "idempotent": True,
        "persist_error": persist_error,
        "affects_chain": "events",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest trusted events incrementally")
    parser.parse_args()
    report = run_event_job()
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
