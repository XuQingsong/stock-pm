"""NFP from official FRED PAYEMS. Monthly change, not the employment level.

Restores the FRED persistence path without requiring FRED_API_KEY: keyless
fredgraph.csv is first-party stlouisfed.org. Does not invent prints.
"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .fetch import FetchError, utc_now
from .series import (
    FRED_GRAPH_CSV,
    build_macro_event,
    fetch_fred_series,
    normalized_record,
    parse_fred_observations,
)


NFP_ENV_OPTIONAL = "FRED_API_KEY"
NFP_SERIES = {
    "metric": "nfp",
    "series_id": "PAYEMS",
    "unit": "thousands",
    "frequency": "monthly",
    "name": "NFP",
    "transform": "diff",
    "freshness_days": 45,
    "required": True,
    "affects_chain": "macro_rates",
    "affects_stage": "facts",
    "fixture": "tests/fixtures/fred_payems.json",
}


def nfp_from_payems(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Latest monthly employment change in thousands. Needs two PAYEMS prints."""
    rows = [row for row in observations if row.get("value") is not None and row.get("period")]
    rows.sort(key=lambda row: str(row["period"]), reverse=True)
    if len(rows) < 2:
        return None
    latest, prior = rows[0], rows[1]
    try:
        value = round(float(latest["value"]) - float(prior["value"]), 1)
    except (TypeError, ValueError):
        return None
    return {
        "period": latest["period"],
        "value": value,
        "payems_level": float(latest["value"]),
        "prior_level": float(prior["value"]),
        "prior_period": prior["period"],
    }


def _empty_nfp_record(*, fetched_at: str, status: str, reason_code: str) -> dict[str, Any]:
    return {
        "source": "FRED",
        "series_or_symbol": NFP_SERIES["series_id"],
        "as_of": None,
        "value": None,
        "unit": NFP_SERIES["unit"],
        "frequency": NFP_SERIES["frequency"],
        "status": status,
        "reason_code": reason_code,
        "http_source": f"{FRED_GRAPH_CSV}?id={NFP_SERIES['series_id']}",
        "transport": "fredgraph_csv",
        "required_env": NFP_ENV_OPTIONAL,
    }


def sync_nfp_from_fred(settings: Settings | None = None, store=None) -> dict[str, Any]:
    settings = settings or Settings()
    fetched_at = utc_now()
    spec = {
        "series_id": NFP_SERIES["series_id"],
        "unit": NFP_SERIES["unit"],
        "frequency": NFP_SERIES["frequency"],
        "name": NFP_SERIES["name"],
    }
    try:
        result = fetch_fred_series(NFP_SERIES["series_id"], settings.fred_api_key, limit=16)
        rows = parse_fred_observations(result.payload)
        derived = nfp_from_payems(rows)
        if derived is None:
            return {
                **_empty_nfp_record(
                    fetched_at=result.fetched_at,
                    status="missing",
                    reason_code="upstream_empty",
                ),
                "fetched_at": result.fetched_at,
                "event": None,
            }
        event = build_macro_event(
            "nfp",
            {"period": derived["period"], "value": derived["value"], "unit": NFP_SERIES["unit"]},
            spec,
            fetched_at=result.fetched_at,
            from_cache=result.from_cache,
            http_source=result.http_source,
            transport=result.transport,
        )
        event["prior"] = derived["prior_level"]
        if store is not None:
            store(event)
        rec = normalized_record(event)
        return {
            **rec,
            "reason_code": result.reason_code,
            "value": derived["value"],
            "payems_level": derived["payems_level"],
            "prior_level": derived["prior_level"],
            "http_source": result.http_source,
            "transport": result.transport,
            "event": event,
        }
    except FetchError as exc:
        status = "stale" if exc.reason_code == "record_stale" else "error"
        if exc.reason_code == "record_invalid":
            status = "invalid"
        return {
            **_empty_nfp_record(fetched_at=fetched_at, status=status, reason_code=exc.reason_code),
            "fetched_at": fetched_at,
            "event": None,
        }
