"""Idempotent incremental event ingest. Failures stay on the events chain."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from stock_pm.config import Settings
from stock_pm.database import Database

from .service import build_event_book, coverage, reset_cache
from .store import persist_cursor, persist_events


def run_event_job(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or Settings()
    reset_cache()
    events = build_event_book(config, refresh=True)
    cover = coverage(config, events)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    persisted = 0
    persist_error = None
    db = Database(config)
    try:
        with db.pool.connection() as conn:
            persisted = persist_events(conn, events, cover)
            persist_cursor(
                conn,
                "official_feed",
                status="ok",
                reason_code=None,
                item_count=persisted,
                stamp=stamp,
            )
            google = cover["providers"]["google_cse"]
            persist_cursor(
                conn,
                "google_cse",
                status=google["status"],
                reason_code=google.get("reason_code"),
                item_count=0 if google["status"] != "ok" else persisted,
                stamp=stamp,
            )
    except Exception as exc:
        persist_error = type(exc).__name__
    finally:
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
