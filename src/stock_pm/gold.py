"""Current gold prints via Alpha Vantage. FRED LBMA gold is historical only.

GOLDPMGBD228NLBM was removed from FRED with ICE/IBA data (2022). Official
fredgraph.csv /data endpoints 404. IQ12260 is a BLS export-price index, not
spot gold, and is never substituted. ICE LBMA is licensed, not wired here.

Live gold uses the official Alpha Vantage GOLD_SILVER_HISTORY daily endpoint
when ALPHA_VANTAGE_API_KEY is set. No keys are written to cache, logs, or UI.
A discontinued FRED print is never shown as the current gold price.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from .config import Settings
from .fetch import FetchError, FetchResult, json_get, utc_now


ALPHA_VANTAGE_API = "https://www.alphavantage.co/query"
GOLD_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
GOLD_SYMBOL = "XAU"
GOLD_UNIT = "USD/oz"
GOLD_FUNCTION = "GOLD_SILVER_HISTORY"

FRED_GOLD_HISTORICAL = {
    "metric": "gold",
    "series_id": "GOLDPMGBD228NLBM",
    "series_or_symbol": "GOLDPMGBD228NLBM",
    "source": "FRED",
    "status": "upstream_unavailable",
    "reason_code": "deprecated",
    "availability": "unavailable",
    "name": "LBMA Gold PM (FRED historical)",
    "unit": GOLD_UNIT,
    "frequency": "daily",
    "note": (
        "ICE/IBA LBMA gold was removed from FRED in 2022; official CSV/graph "
        "returns 404. Historical FRED prints are not current gold prices."
    ),
}

GOLD_LIVE = {
    "metric": "gold",
    "provider": "alpha_vantage",
    "symbol": GOLD_SYMBOL,
    "series_id": GOLD_SYMBOL,
    "series_or_symbol": GOLD_SYMBOL,
    "function": GOLD_FUNCTION,
    "interval": "daily",
    "unit": GOLD_UNIT,
    "frequency": "daily",
    "name": "Gold",
    "env_var": GOLD_ENV_VAR,
    "required": False,
    "freshness_days": 7,
    "fixture": "tests/fixtures/av_gold_xau.json",
}


def fred_gold_historical_record(*, fetched_at: str | None = None) -> dict[str, Any]:
    return {
        "source": FRED_GOLD_HISTORICAL["source"],
        "series_or_symbol": FRED_GOLD_HISTORICAL["series_or_symbol"],
        "series": FRED_GOLD_HISTORICAL["series_id"],
        "symbol": FRED_GOLD_HISTORICAL["series_id"],
        "observed_at": None,
        "as_of": None,
        "fetched_at": fetched_at,
        "unit": FRED_GOLD_HISTORICAL["unit"],
        "frequency": FRED_GOLD_HISTORICAL["frequency"],
        "status": FRED_GOLD_HISTORICAL["status"],
        "reason_code": FRED_GOLD_HISTORICAL["reason_code"],
        "availability": FRED_GOLD_HISTORICAL["availability"],
        "value": None,
        "note": FRED_GOLD_HISTORICAL["note"],
    }


def historical_gold_fields() -> dict[str, Any]:
    return {
        "historical_source": FRED_GOLD_HISTORICAL["source"],
        "historical_series_or_symbol": FRED_GOLD_HISTORICAL["series_or_symbol"],
        "historical_status": FRED_GOLD_HISTORICAL["status"],
        "historical_reason_code": FRED_GOLD_HISTORICAL["reason_code"],
        "historical_note": FRED_GOLD_HISTORICAL["note"],
        "required_env": GOLD_ENV_VAR,
    }


def is_deprecated_fred_gold(row: dict[str, Any] | None) -> bool:
    payload = row or {}
    series = str(payload.get("series_or_symbol") or payload.get("series") or payload.get("symbol") or "")
    source = str(payload.get("source") or "")
    event_type = str(payload.get("event_type") or payload.get("metric") or "")
    if series == FRED_GOLD_HISTORICAL["series_id"]:
        return True
    return event_type == "gold" and source.upper() == "FRED"


def normalize_gold_unit(unit: str | None) -> str | None:
    if not unit:
        return unit
    text = unit.strip().lower()
    if text in {GOLD_UNIT.lower(), "usd per troy ounce", "usd/troy oz", "usd per ounce"}:
        return GOLD_UNIT
    return unit


def parse_alpha_vantage_gold(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise FetchError("record_invalid", "Alpha Vantage gold payload is not an object")
    if payload.get("Note") or payload.get("Information"):
        raise FetchError("rate_limited", "Alpha Vantage gold rate limited")
    if payload.get("Error Message"):
        raise FetchError("query_error", "Alpha Vantage gold query failed")
    rows = payload.get("data")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise FetchError("record_invalid", "Alpha Vantage gold data changed shape")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise FetchError("record_invalid", "Alpha Vantage gold row is not an object")
        value = row.get("value")
        if value in (None, "", "."):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FetchError("record_invalid", "Alpha Vantage gold value is not numeric") from exc
        period = _require_period(row.get("date"))
        parsed.append({"period": period, "value": number, "unit": normalize_gold_unit(payload.get("unit"))})
    parsed.sort(key=lambda item: item["period"], reverse=True)
    return parsed


def _require_period(value: Any) -> str:
    period = str(value or "")
    if len(period) < 10:
        raise FetchError("record_invalid", "Alpha Vantage gold date is missing")
    stamp = period[:10]
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise FetchError("record_invalid", "Alpha Vantage gold date is invalid") from exc
    return stamp


def gold_http_source() -> str:
    return (
        f"{ALPHA_VANTAGE_API}?function={GOLD_FUNCTION}"
        f"&symbol={GOLD_SYMBOL}&interval=daily"
    )


def fetch_alpha_vantage_gold(api_key: str, *, limit: int = 16) -> FetchResult:
    if not api_key:
        raise FetchError("source_not_configured", f"{GOLD_ENV_VAR} is required")
    params = urlencode(
        {
            "function": GOLD_FUNCTION,
            "symbol": GOLD_SYMBOL,
            "interval": "daily",
            "apikey": api_key,
        }
    )
    result = json_get(
        f"{ALPHA_VANTAGE_API}?{params}",
        timeout=20,
        retries=3,
        cache_key=f"av-gold-{GOLD_SYMBOL}",
    )
    rows = parse_alpha_vantage_gold(result.payload)[:limit]
    return FetchResult(
        payload={"data": [{"date": row["period"], "value": str(row["value"])} for row in rows], "unit": GOLD_UNIT},
        status=result.status,
        reason_code=result.reason_code,
        fetched_at=result.fetched_at,
        from_cache=result.from_cache,
        cache_key=result.cache_key,
        http_source=gold_http_source(),
        transport="alpha_vantage",
    )


def build_gold_event(
    observation: dict[str, Any],
    *,
    fetched_at: str,
    from_cache: bool,
    http_source: str | None = None,
    transport: str | None = None,
) -> dict[str, Any]:
    period = observation["period"]
    unit = normalize_gold_unit(observation.get("unit")) or GOLD_UNIT
    if unit != GOLD_UNIT:
        raise FetchError("record_invalid", f"unit {unit!r} does not match {GOLD_UNIT}")
    notes = {
        "series": GOLD_SYMBOL,
        "symbol": GOLD_SYMBOL,
        "series_or_symbol": GOLD_SYMBOL,
        "observed_at": fetched_at,
        "as_of": period,
        "fetched_at": fetched_at,
        "unit": GOLD_UNIT,
        "frequency": "daily",
        "status": "stale" if from_cache else "ok",
        "source": "alpha_vantage",
        "metric": "gold",
        "http_source": http_source,
        "transport": transport,
        **historical_gold_fields(),
    }
    return {
        "event_type": "gold",
        "event_time": datetime.fromisoformat(f"{period}T00:00:00+00:00").isoformat(),
        "name": GOLD_LIVE["name"],
        "actual": observation["value"],
        "value": observation["value"],
        "consensus": None,
        "prior": None,
        "unit": GOLD_UNIT,
        "series": GOLD_SYMBOL,
        "series_or_symbol": GOLD_SYMBOL,
        "frequency": "daily",
        "observed_at": fetched_at,
        "as_of": period,
        "fetched_at": fetched_at,
        "http_source": http_source,
        "transport": transport,
        "status": "stale" if from_cache else "ok",
        "surprise": "unknown",
        "confirmed": True,
        "source": "alpha_vantage",
        "notes": json.dumps(notes, ensure_ascii=False),
        **historical_gold_fields(),
    }


def _unconfigured_gold(fetched_at: str) -> dict[str, Any]:
    return {
        "source": "alpha_vantage",
        "series_or_symbol": GOLD_SYMBOL,
        "series": GOLD_SYMBOL,
        "symbol": GOLD_SYMBOL,
        "observed_at": None,
        "as_of": None,
        "fetched_at": fetched_at,
        "unit": GOLD_UNIT,
        "frequency": "daily",
        "status": "not_configured",
        "reason_code": "source_not_configured",
        "value": None,
        "http_source": gold_http_source(),
        "transport": "alpha_vantage",
        "note": f"配置 {GOLD_ENV_VAR} 后同步官方 GOLD_SILVER_HISTORY；不展示密钥。",
        **historical_gold_fields(),
    }


def sync_live_gold(settings: Settings | None = None, store=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = settings or Settings()
    fetched_at = utc_now()
    if not settings.alpha_vantage_api_key:
        return [], _unconfigured_gold(fetched_at)
    try:
        result = fetch_alpha_vantage_gold(settings.alpha_vantage_api_key)
        rows = parse_alpha_vantage_gold(result.payload)
        if not rows:
            rec = {
                **_unconfigured_gold(result.fetched_at),
                "status": "missing",
                "reason_code": "upstream_empty",
                "note": "Alpha Vantage gold returned no observations",
            }
            return [], rec
        event = build_gold_event(
            rows[0],
            fetched_at=result.fetched_at,
            from_cache=result.from_cache,
            http_source=result.http_source,
            transport=result.transport,
        )
        if store is not None:
            store(event)
        return [event], {
            "source": "alpha_vantage",
            "series_or_symbol": GOLD_SYMBOL,
            "as_of": rows[0]["period"],
            "value": rows[0]["value"],
            "unit": GOLD_UNIT,
            "frequency": "daily",
            "status": event["status"],
            "reason_code": result.reason_code,
            "fetched_at": result.fetched_at,
            "observed_at": result.fetched_at,
            "http_source": result.http_source,
            "transport": result.transport,
            "from_cache": result.from_cache,
            **historical_gold_fields(),
        }
    except FetchError as exc:
        status = "stale" if exc.reason_code == "record_stale" else "error"
        if exc.reason_code == "record_invalid":
            status = "invalid"
        if exc.reason_code == "source_not_configured":
            return [], _unconfigured_gold(fetched_at)
        return [], {
            **_unconfigured_gold(fetched_at),
            "status": status,
            "reason_code": exc.reason_code,
            "note": "Alpha Vantage gold query failed; FRED historical gold is not used as current",
        }
