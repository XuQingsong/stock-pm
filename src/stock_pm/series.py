"""Official FRED series for rates, VIX, metals, oil, and the dollar.

Reuses the existing FRED provider. Does not add Alpha Vantage or EDGAR.
Does not invent values when the upstream is empty, timed out, or unconfigured.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from .config import Settings
from .fetch import FetchError, FetchResult, json_get, utc_now


FRED_API = "https://api.stlouisfed.org/fred/series/observations"

# Official / first-hand series. DXY uses the Fed broad dollar index (not ICE).
FRED_MARKET_SERIES = {
    "cpi": {
        "series_id": "CPIAUCSL",
        "unit": "index",
        "frequency": "monthly",
        "name": "CPI-U",
        "freshness_days": 50,
        "required": True,
        "affects_chain": "macro_rates",
        "affects_stage": "what_changed",
    },
    "us2y": {
        "series_id": "DGS2",
        "unit": "percent",
        "frequency": "daily",
        "name": "US 2Y Treasury",
        "freshness_days": 14,
        "required": True,
        "affects_chain": "macro_rates",
        "affects_stage": "confirmation",
    },
    "vix": {
        "series_id": "VIXCLS",
        "unit": "index",
        "frequency": "daily",
        "name": "VIX",
        "freshness_days": 7,
        "required": True,
        "affects_chain": "risk_sentiment",
        "affects_stage": "confirmation",
    },
    "gold": {
        "series_id": "GOLDPMGBD228NLBM",
        "unit": "USD/oz",
        "frequency": "daily",
        "name": "LBMA Gold PM",
        "freshness_days": 7,
        "required": False,
        "affects_chain": "macro_rates",
        "affects_stage": "confirmation",
    },
    "wti": {
        "series_id": "DCOILWTICO",
        "unit": "USD/bbl",
        "frequency": "daily",
        "name": "WTI Crude",
        "freshness_days": 7,
        "required": False,
        "affects_chain": "macro_rates",
        "affects_stage": "confirmation",
    },
    "dxy": {
        "series_id": "DTWEXBGS",
        "unit": "index",
        "frequency": "daily",
        "name": "Trade-weighted USD (broad)",
        "freshness_days": 7,
        "required": False,
        "affects_chain": "macro_rates",
        "affects_stage": "confirmation",
    },
}


def parse_fred_observations(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise FetchError("record_invalid", "FRED payload is not an object")
    rows = payload.get("observations")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise FetchError("record_invalid", "FRED observations changed shape")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise FetchError("record_invalid", "FRED observation row is not an object")
        value = row.get("value")
        if value in (None, "", "."):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FetchError("record_invalid", "FRED value is not numeric") from exc
        period = str(row.get("date") or "")
        if len(period) < 10:
            raise FetchError("record_invalid", "FRED date is missing")
        parsed.append(
            {
                "period": period[:10],
                "value": number,
                "realtime_start": row.get("realtime_start"),
            }
        )
    return parsed


def fetch_fred_series(series_id: str, api_key: str, *, limit: int = 16) -> FetchResult:
    if not api_key:
        raise FetchError("source_not_configured", "FRED is not configured")
    params = urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
    )
    return json_get(
        f"{FRED_API}?{params}",
        timeout=20,
        retries=3,
        cache_key=f"fred-{series_id}",
    )


def observation_notes(
    *,
    metric: str,
    series_id: str,
    fetched_at: str,
    from_cache: bool,
    frequency: str,
    unit: str,
    status: str,
) -> str:
    return json.dumps(
        {
            "series": series_id,
            "symbol": series_id,
            "observed_at": fetched_at,
            "as_of": None,
            "fetched_at": fetched_at,
            "unit": unit,
            "frequency": frequency,
            "status": "stale" if from_cache else status,
            "source": "FRED",
            "metric": metric,
        },
        ensure_ascii=False,
    )


def decorate_macro_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    notes = row.get("notes")
    meta: dict[str, Any] = {}
    if isinstance(notes, dict):
        meta = notes
    elif isinstance(notes, str) and notes.startswith("{"):
        try:
            parsed = json.loads(notes)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            meta = parsed
    fetched = meta.get("fetched_at") or meta.get("observed_at")
    period = payload.get("event_time")
    if hasattr(period, "isoformat"):
        period = period.isoformat()
    payload.update(
        {
            "series": meta.get("series") or meta.get("symbol"),
            "observed_at": fetched,
            "ingested_at": fetched,
            "synced_at": fetched,
            "source_as_of": fetched,
            "as_of": str(period)[:10] if period else meta.get("as_of"),
            "fetched_at": fetched,
            "frequency": meta.get("frequency"),
            "unit": payload.get("unit") or meta.get("unit"),
            "status": meta.get("status") or "ok",
        }
    )
    return payload


def map_earnings_health(row: dict[str, Any]) -> dict[str, Any]:
    """Map existing FMP/Nasdaq estimate fields. Do not invent prior snapshots."""
    payload = dict(row)
    synced = payload.get("synced_at")
    if hasattr(synced, "isoformat"):
        synced = synced.isoformat()
    payload["latest_consensus"] = payload.get("eps_estimate")
    payload["latest_consensus_as_of"] = synced
    payload["observed_at"] = synced
    payload["fetched_at"] = synced
    # Alpha Vantage is not wired; a distinct prior consensus as_of does not exist.
    payload.setdefault("prior_consensus", None)
    payload.setdefault("prior_consensus_as_of", None)
    payload["estimates_provider"] = payload.get("source") or "fmp"
    payload["edgar_status"] = "not_integrated"
    return payload


def build_macro_event(
    metric: str,
    observation: dict[str, Any],
    spec: dict[str, Any],
    *,
    fetched_at: str,
    from_cache: bool,
) -> dict[str, Any]:
    period = observation["period"]
    event_time = datetime.fromisoformat(f"{period}T00:00:00+00:00")
    notes = json.loads(observation_notes(
        metric=metric,
        series_id=spec["series_id"],
        fetched_at=fetched_at,
        from_cache=from_cache,
        frequency=spec["frequency"],
        unit=spec["unit"],
        status="ok",
    ))
    notes["as_of"] = period
    return {
        "event_type": metric,
        "event_time": event_time.isoformat(),
        "name": spec["name"],
        "actual": observation["value"],
        "consensus": None,
        "prior": None,
        "unit": spec["unit"],
        "surprise": "unknown",
        "confirmed": True,
        "source": "FRED",
        "notes": json.dumps(notes, ensure_ascii=False),
    }


def sync_fred_market_series(settings: Settings | None = None, store=None) -> dict[str, Any]:
    settings = settings or Settings()
    report: dict[str, Any] = {"fetched_at": utc_now(), "series": {}}
    if not settings.fred_api_key:
        for metric in FRED_MARKET_SERIES:
            report["series"][metric] = {"status": "not_configured", "reason_code": "source_not_configured"}
        return report
    for metric, spec in FRED_MARKET_SERIES.items():
        try:
            result = fetch_fred_series(spec["series_id"], settings.fred_api_key)
            rows = parse_fred_observations(result.payload)
            if not rows:
                report["series"][metric] = {"status": "missing", "reason_code": "upstream_empty"}
                continue
            latest = rows[0]
            event = build_macro_event(
                metric,
                latest,
                spec,
                fetched_at=result.fetched_at,
                from_cache=result.from_cache,
            )
            if store is not None:
                store(event)
            report["series"][metric] = {
                "status": "stale" if result.from_cache else "ok",
                "reason_code": result.reason_code,
                "period": latest["period"],
                "from_cache": result.from_cache,
                "series_id": spec["series_id"],
            }
        except FetchError as exc:
            report["series"][metric] = {"status": "error", "reason_code": exc.reason_code}
    return report
