"""Shared live overlay for decision + data-health. Overlay does not hide a down DB."""

from __future__ import annotations

from typing import Any, Iterable

from stock_pm import alpaca, providers, series
from stock_pm.config import Settings
from stock_pm.errors import DatabaseError
from stock_pm.series import empty_real_bundle, merge_live_macros


def overlay_live_bundle(
    database,
    symbol: str,
    settings: Settings | None = None,
    *,
    persist: bool = True,
    inject: Iterable[str] | None = None,
) -> dict[str, Any]:
    from stock_pm.decision.inject import apply_inject, inject_allowed

    settings = settings or Settings()
    symbol = symbol.upper()
    if hasattr(database, "monitor_status"):
        db_status = dict(database.monitor_status() or {})
    else:
        reachable = bool(database.ping())
        db_status = {
            "reachable": reachable,
            "status": "ok" if reachable else "error",
            "database": "connected" if reachable else "unavailable",
            "reason_code": None if reachable else "query_error",
            "note": None if reachable else "PostgreSQL unreachable; live overlay does not hide this",
        }
    db_status.setdefault("reachable", db_status.get("status") != "error")
    db_status.setdefault("status", "ok" if db_status.get("reachable") else "error")
    db_error = not bool(db_status.get("reachable"))
    if db_error:
        bundle = empty_real_bundle(symbol)
    else:
        try:
            bundle = database.decision_bundle(symbol)
        except DatabaseError:
            db_error = True
            db_status = {
                **db_status,
                "status": "error",
                "reachable": False,
                "database": "unavailable",
                "reason_code": "query_error",
                "note": "PostgreSQL unreachable; live overlay does not hide this",
            }
            bundle = empty_real_bundle(symbol)
    live, live_errors, live_report = series.collect_live_macro_overlay(settings)
    bundle = merge_live_macros(bundle, live)
    live_bars, bar_errors, bar_report = alpaca.collect_live_daily_bars(symbol, settings)
    if live_bars:
        bundle["bars"] = live_bars
    live_earnings, earn_errors, earn_report = providers.collect_live_earnings(symbol, settings)
    if live_earnings:
        bundle["earnings"] = live_earnings
    persistence = {"status": "skipped", "reason": "database_unavailable"}
    if persist and not db_error:
        try:
            from stock_pm.persist_live import persist_daily_bars, persist_earnings, persist_macro_events

            captured_at = live_report.get("fetched_at")
            if live_bars:
                persist_daily_bars(
                    database,
                    symbol,
                    live_bars,
                    captured_at=captured_at,
                    source=str((bar_report.get("daily_price_bars") or {}).get("source") or "alpaca_sip"),
                )
            if live_earnings:
                persist_earnings(database, symbol, live_earnings, captured_at=captured_at, source="fmp")
            if live:
                persist_macro_events(database, live)
            persistence = {"status": "ok"}
        except DatabaseError:
            persistence = {"status": "error", "reason_code": "query_error"}
            db_status = {
                **db_status,
                "status": "error",
                "reason_code": "query_error",
                "note": "PostgreSQL write failed; live overlay does not hide this",
            }
    if inject and inject_allowed(settings):
        bundle = apply_inject(bundle, inject)
    query_errors = set(live_errors) | set(bar_errors) | set(earn_errors)
    return {
        "bundle": bundle,
        "db_status": db_status,
        "db_error": db_error,
        "persistence": persistence,
        "query_errors": query_errors,
        "live_report": live_report,
        "bar_report": bar_report,
        "earn_report": earn_report,
        "settings": settings,
    }
