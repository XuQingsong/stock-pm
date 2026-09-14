"""Watchlist universe for earnings coverage. Database is source of truth; seed is fallback."""

from __future__ import annotations

import os
from typing import Any

from stock_pm.config import DEFAULT_WATCHLIST, Settings


_APPLIED: dict[str, list[str]] | None = None


def seed_stock_symbols() -> list[str]:
    return [key for key, row in DEFAULT_WATCHLIST.items() if row.asset_class == "stocks"]


def seed_etf_symbols() -> list[str]:
    return [key for key, row in DEFAULT_WATCHLIST.items() if row.asset_class == "etf"]


def apply_watchlist_rows(rows: list[dict[str, Any]] | None) -> None:
    """Use already-loaded watchlist rows (job path) so discover does not open a second pool."""
    global _APPLIED
    if not rows:
        _APPLIED = None
        return
    stocks = [str(row["symbol"]).upper() for row in rows if str(row.get("asset_class") or "") == "stocks"]
    etfs = [str(row["symbol"]).upper() for row in rows if str(row.get("asset_class") or "") == "etf"]
    _APPLIED = {"stocks": stocks, "etfs": etfs}


def reset_watchlist_override() -> None:
    global _APPLIED
    _APPLIED = None


def _from_database(settings: Settings | None) -> dict[str, list[str]] | None:
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("STOCK_PM_EARNINGS_WATCHLIST_DB") != "1":
        return None
    try:
        from stock_pm.database import Database

        db = Database(settings)
        try:
            rows = db.watchlist_rows()
        finally:
            db.close()
        stocks = [str(row["symbol"]).upper() for row in rows if str(row.get("asset_class") or "") == "stocks"]
        etfs = [str(row["symbol"]).upper() for row in rows if str(row.get("asset_class") or "") == "etf"]
        if stocks or etfs:
            return {"stocks": stocks, "etfs": etfs}
    except Exception:
        return None
    return None


def resolve_watchlist(settings: Settings | None = None) -> dict[str, list[str]]:
    if _APPLIED is not None:
        return {"stocks": list(_APPLIED["stocks"]), "etfs": list(_APPLIED["etfs"])}
    loaded = _from_database(settings)
    if loaded:
        return loaded
    return {"stocks": seed_stock_symbols(), "etfs": seed_etf_symbols()}


def resolve_stock_symbols(settings: Settings | None = None) -> list[str]:
    return resolve_watchlist(settings)["stocks"]


def resolve_etf_symbols(settings: Settings | None = None) -> list[str]:
    return resolve_watchlist(settings)["etfs"]
