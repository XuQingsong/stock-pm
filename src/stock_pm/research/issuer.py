"""Issuer identity is data: CIK, fiscal year-end, aliases. Not workflow branches."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


DIRECTORY_PATH = Path(__file__).resolve().parent / "data" / "issuer_directory.json"


@lru_cache(maxsize=1)
def load_directory() -> dict[str, dict[str, Any]]:
    if not DIRECTORY_PATH.is_file():
        return {}
    payload = json.loads(DIRECTORY_PATH.read_text(encoding="utf-8"))
    return {str(key).upper(): dict(value or {}) for key, value in payload.items()}


def directory_entry(ticker: str) -> dict[str, Any]:
    return dict(load_directory().get(str(ticker or "").upper()) or {})


def cik_for(ticker: str) -> str:
    return str(directory_entry(ticker).get("cik") or "").strip()


def fiscal_year_end_month_for(ticker: str, row: dict[str, Any] | None = None) -> int | None:
    if row and row.get("fiscal_year_end_month") not in (None, ""):
        try:
            month = int(row["fiscal_year_end_month"])
        except (TypeError, ValueError):
            month = None
        else:
            if 1 <= month <= 12:
                return month
    raw = directory_entry(ticker).get("fiscal_year_end_month")
    if raw in (None, ""):
        return None
    try:
        month = int(raw)
    except (TypeError, ValueError):
        return None
    return month if 1 <= month <= 12 else None


def ticker_for_cik(cik: str) -> str:
    needle = str(cik or "").strip().zfill(10)
    if needle == "0000000000":
        return ""
    for ticker, entry in load_directory().items():
        stored = str(entry.get("cik") or "").strip().zfill(10)
        if stored == needle:
            return ticker
    return ""


def missing_identity_fields(row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(row.get("cik") or "").strip():
        missing.append("cik")
    if row.get("fiscal_year_end_month") in (None, ""):
        missing.append("fiscal_year_end_month")
    if not str(row.get("legal_name") or "").strip():
        missing.append("legal_name")
    return missing


def merge_identity(
    ticker: str,
    *,
    legal_name: str = "",
    cik: str | None = None,
    fiscal_year_end_month: int | None = None,
    sector: str | None = None,
    gics: str | None = None,
    primary_exchange: str = "",
    asset_class: str = "stocks",
    aliases: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    listed = directory_entry(ticker)
    name = (legal_name or listed.get("legal_name") or ticker).strip()
    resolved_cik = (cik or listed.get("cik") or "") or None
    if resolved_cik:
        resolved_cik = str(resolved_cik).strip()
    month = fiscal_year_end_month
    if month is None:
        month = fiscal_year_end_month_for(ticker)
    alias_set = list(aliases or [])
    for item in listed.get("aliases") or []:
        if item not in alias_set:
            alias_set.append(item)
    row = {
        "ticker": str(ticker).upper(),
        "legal_name": name,
        "cik": resolved_cik,
        "fiscal_year_end_month": month,
        "sector": sector if sector is not None else listed.get("sector"),
        "gics": gics,
        "primary_exchange": primary_exchange or listed.get("primary_exchange") or "",
        "asset_class": asset_class or listed.get("asset_class") or "stocks",
        "aliases": alias_set,
        "source": source,
    }
    row["missing_fields"] = missing_identity_fields(row)
    return row
