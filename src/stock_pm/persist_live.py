"""Write live Alpaca bars, FMP earnings, and FRED NFP into PostgreSQL, then read back.

Overlay values are not a substitute for persistence. If the database is down,
callers must surface that error instead of treating overlay as stored truth.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from .alpaca import collect_live_daily_bars
from .config import Settings, redact_database_url
from .database import Database
from .errors import DatabaseError
from .nfp import sync_nfp_from_fred
from .providers import collect_live_earnings
from .series import collect_live_macro_overlay, decorate_macro_row, map_earnings_health


def _captured_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def persist_daily_bars(
    database: Database,
    symbol: str,
    bars: list[dict[str, Any]],
    *,
    captured_at: str | None = None,
    source: str = "alpaca_sip",
) -> dict[str, int]:
    if not bars:
        return {"bars": 0}
    payload = {
        "source": source,
        "captured_at": captured_at or _captured_at(),
        "history": [
            {
                "symbol": symbol.upper(),
                "bar_size": "1d",
                "source": source,
                "bars": [
                    {
                        "bar_time": row.get("bar_time"),
                        "open_price": row.get("open_price"),
                        "high_price": row.get("high_price"),
                        "low_price": row.get("low_price"),
                        "close_price": row.get("close_price"),
                        "volume": row.get("volume"),
                    }
                    for row in bars
                    if row.get("bar_time") is not None
                ],
            }
        ],
    }
    return database.ingest(payload)


def persist_earnings(
    database: Database,
    symbol: str,
    earnings: list[dict[str, Any]],
    *,
    captured_at: str | None = None,
    source: str = "fmp",
) -> dict[str, int]:
    rows = []
    for row in earnings:
        if not row.get("report_date") or not row.get("fiscal_period"):
            continue
        rows.append(
            {
                "symbol": symbol.upper(),
                "report_date": row["report_date"],
                "report_timing": row.get("report_timing") or "unknown",
                "fiscal_period": row["fiscal_period"],
                "fiscal_year": row.get("fiscal_year"),
                "period_end": row.get("period_end"),
                "currency": row.get("currency") or "USD",
                "eps_actual": row.get("eps_actual"),
                "eps_estimate": row.get("eps_estimate"),
                "eps_surprise_pct": row.get("eps_surprise_pct"),
                "revenue_actual": row.get("revenue_actual"),
                "revenue_estimate": row.get("revenue_estimate"),
                "revenue_surprise_pct": row.get("revenue_surprise_pct"),
                "net_income_actual": row.get("net_income_actual"),
                "net_income_estimate": row.get("net_income_estimate"),
                "net_income_surprise_pct": row.get("net_income_surprise_pct"),
                "provider_fields": row.get("provider_fields") or {},
                "source": row.get("source") or source,
            }
        )
    if not rows:
        return {"earnings": 0}
    payload = {
        "source": source,
        "captured_at": captured_at or _captured_at(),
        "earnings": rows,
    }
    return database.ingest(payload)


def persist_macro_events(database: Database, events: list[dict[str, Any]]) -> int:
    written = 0
    for event in events:
        if not event.get("event_type") or not event.get("event_time"):
            continue
        database.store_macro_event(event)
        written += 1
    return written


def readback_daily_bar(database: Database, symbol: str) -> dict[str, Any] | None:
    return database.latest_daily_bar(symbol)


def readback_earnings(database: Database, symbol: str) -> dict[str, Any] | None:
    return database.latest_earnings_row(symbol)


def readback_nfp(database: Database) -> dict[str, Any] | None:
    row = database.latest_macro_event("nfp")
    return decorate_macro_row(row) if row else None


def persist_live_symbol(
    database: Database,
    symbol: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    symbol = symbol.upper()
    captured_at = _captured_at()
    report: dict[str, Any] = {
        "symbol": symbol,
        "captured_at": captured_at,
        "database": redact_database_url(settings.database_url),
        "bars": {"status": "missing"},
        "earnings": {"status": "missing"},
        "nfp": {"status": "missing"},
        "macros": {"status": "missing"},
    }
    bars, _bar_errors, bar_rec = collect_live_daily_bars(symbol, settings)
    if bars:
        persist_daily_bars(
            database,
            symbol,
            bars,
            captured_at=captured_at,
            source=str(bar_rec.get("daily_price_bars", {}).get("source") or "alpaca_sip"),
        )
        stored = readback_daily_bar(database, symbol)
        latest = bars[0]
        rec = bar_rec.get("daily_price_bars") or {}
        report["bars"] = {
            "status": "ok" if stored else "error",
            "source": (stored or {}).get("source") or rec.get("source"),
            "feed": "sip" if "sip" in str((stored or {}).get("source") or rec.get("source") or "") else None,
            "as_of": (stored or {}).get("as_of") or rec.get("as_of") or latest.get("as_of"),
            "value": (stored or {}).get("close_price") if stored else rec.get("value"),
            "unit": rec.get("unit") or "USD",
            "written": len(bars),
            "readback": stored,
        }
    else:
        report["bars"] = bar_rec.get("daily_price_bars") or {"status": "missing"}

    earnings, _earn_errors, earn_rec = collect_live_earnings(symbol, settings)
    if earnings:
        persist_earnings(database, symbol, earnings, captured_at=captured_at, source="fmp")
        stored = readback_earnings(database, symbol)
        rec = earn_rec.get("earnings_reports") or {}
        mapped = map_earnings_health(stored) if stored else {}
        report["earnings"] = {
            "status": "ok" if stored else "error",
            "source": (stored or {}).get("source") or rec.get("source"),
            "as_of": mapped.get("as_of") or rec.get("as_of"),
            "actual": (stored or {}).get("eps_actual"),
            "estimate": (stored or {}).get("eps_estimate"),
            "value": (stored or {}).get("eps_actual"),
            "unit": rec.get("unit") or "USD/share",
            "written": len(earnings),
            "readback": stored,
        }
    else:
        report["earnings"] = earn_rec.get("earnings_reports") or {"status": "missing"}

    live_macros, _macro_errors, macro_rec = collect_live_macro_overlay(settings)
    persist_macro_events(database, live_macros)
    nfp_rec = sync_nfp_from_fred(settings, store=database.store_macro_event)
    stored_nfp = readback_nfp(database)
    report["nfp"] = {
        "status": (stored_nfp or {}).get("status") or nfp_rec.get("status"),
        "source": (stored_nfp or {}).get("source") or nfp_rec.get("source"),
        "as_of": (stored_nfp or {}).get("as_of") or nfp_rec.get("as_of"),
        "value": (stored_nfp or {}).get("value") if stored_nfp else nfp_rec.get("value"),
        "unit": (stored_nfp or {}).get("unit") or nfp_rec.get("unit"),
        "reason_code": nfp_rec.get("reason_code"),
        "readback": stored_nfp,
    }
    report["macros"] = {
        "status": "ok" if live_macros else "missing",
        "written": len(live_macros),
        "series": {
            metric: {
                "status": rec.get("status"),
                "as_of": rec.get("as_of"),
                "value": rec.get("value"),
            }
            for metric, rec in (macro_rec.get("series") or {}).items()
            if metric not in {"dxy", "gold_fred_historical"}
        },
    }
    return report


def persist_live(symbol: str = "NVDA", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    database = Database(settings)
    try:
        if not database.ping():
            raise DatabaseError("PostgreSQL unreachable; refuse to treat live overlay as stored")
        database.initialize()
        return persist_live_symbol(database, symbol, settings)
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist live NVDA bars, FMP earnings, and NFP")
    parser.add_argument("--symbol", default="NVDA")
    args = parser.parse_args()
    report = persist_live(args.symbol)
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
