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

# Official / first-hand series. ICE DXY is not wired; DTWEXBGS is a separate proxy.
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
        "fixture": "tests/fixtures/fred_cpiaucsl.json",
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
        "fixture": "tests/fixtures/fred_dgs2.json",
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
        "fixture": "tests/fixtures/fred_vixcls.json",
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
        "fixture": "tests/fixtures/fred_goldpmgbd228nlbm.json",
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
        "fixture": "tests/fixtures/fred_dcoilwtico.json",
    },
    "broad_usd_proxy": {
        "series_id": "DTWEXBGS",
        "unit": "index",
        "frequency": "daily",
        "name": "广义美元代理",
        "freshness_days": 7,
        "required": False,
        "affects_chain": "macro_rates",
        "affects_stage": "confirmation",
        "fixture": "tests/fixtures/fred_dtwexbgs.json",
    },
}

PROXY_METRICS = frozenset({"broad_usd_proxy", "usd_broad"})
LEGACY_PROXY_EVENT_TYPES = frozenset({"broad_usd_proxy", "usd_broad", "dxy"})

# ICE DXY is not licensed or stably wired. Never fetch or label DTWEXBGS as DXY.
DXY_UNAVAILABLE = {
    "metric": "dxy",
    "series_id": None,
    "series_or_symbol": None,
    "status": "not_configured",
    "availability": "unavailable",
    "reason_code": "source_not_configured",
    "source": "ice",
    "name": "ICE DXY",
    "note": "ICE DXY is not wired; FRED DTWEXBGS is broad_usd_proxy (广义美元代理) only",
}

NORMALIZED_FIELDS = (
    "source",
    "series_or_symbol",
    "observed_at",
    "as_of",
    "fetched_at",
    "unit",
    "frequency",
    "status",
)


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
        period = _require_period(row.get("date"))
        parsed.append(
            {
                "period": period,
                "value": number,
                "realtime_start": row.get("realtime_start"),
            }
        )
    return parsed


def _require_period(value: Any) -> str:
    period = str(value or "")
    if len(period) < 10:
        raise FetchError("record_invalid", "FRED date is missing")
    stamp = period[:10]
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise FetchError("record_invalid", "FRED date is invalid") from exc
    return stamp


def expected_unit(metric: str) -> str | None:
    spec = FRED_MARKET_SERIES.get(metric)
    return None if spec is None else spec["unit"]


def validate_unit(metric: str, unit: str | None) -> None:
    expected = expected_unit(metric)
    if expected is None:
        return
    if not unit or unit != expected:
        raise FetchError("record_invalid", f"unit {unit!r} does not match {expected}")


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
            "series_or_symbol": series_id,
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


def _notes_meta(row: dict[str, Any]) -> dict[str, Any]:
    notes = row.get("notes")
    if isinstance(notes, dict):
        return notes
    if isinstance(notes, str) and notes.startswith("{"):
        try:
            parsed = json.loads(notes)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def decorate_macro_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    meta = dict(_notes_meta(row))
    series_id = (
        meta.get("series_or_symbol")
        or meta.get("series")
        or meta.get("symbol")
        or payload.get("series_or_symbol")
        or payload.get("series")
    )
    event_type = str(payload.get("event_type") or payload.get("metric") or "")
    # Historical dxy+DTWEXBGS / usd_broad rows surface as the proxy, never as ICE DXY.
    if series_id == "DTWEXBGS" or event_type in PROXY_METRICS or (
        event_type in LEGACY_PROXY_EVENT_TYPES and series_id in {None, "", "DTWEXBGS"}
    ):
        payload["event_type"] = "broad_usd_proxy"
        payload["name"] = "广义美元代理"
        series_id = series_id or "DTWEXBGS"
        meta["series"] = series_id
        meta["symbol"] = series_id
        meta["series_or_symbol"] = series_id
        meta["metric"] = "broad_usd_proxy"
    fetched = meta.get("fetched_at") or meta.get("observed_at") or payload.get("fetched_at") or payload.get("observed_at")
    period = meta.get("as_of") or payload.get("as_of") or payload.get("event_time")
    if hasattr(period, "isoformat"):
        period = period.isoformat()
    as_of = str(period)[:10] if period else None
    payload.update(
        {
            "series": series_id,
            "symbol": series_id,
            "series_or_symbol": series_id,
            "observed_at": fetched,
            "ingested_at": fetched,
            "synced_at": fetched,
            "source_as_of": fetched,
            "as_of": as_of,
            "fetched_at": fetched,
            "frequency": payload.get("frequency") or meta.get("frequency"),
            "unit": payload.get("unit") or meta.get("unit"),
            "status": meta.get("status") or payload.get("status") or "ok",
        }
    )
    return payload


def normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    """Machine-verifiable contract: source, series_or_symbol, clocks, unit, frequency, status."""
    if row.get("metric") == "dxy" and row.get("status") in {"not_configured", "unavailable"}:
        return dxy_unavailable_record(fetched_at=row.get("fetched_at"))
    decorated = decorate_macro_row(row)
    series = decorated.get("series_or_symbol") or decorated.get("series") or decorated.get("symbol")
    return {
        "source": decorated.get("source"),
        "series_or_symbol": series,
        "series": series,
        "symbol": series,
        "observed_at": decorated.get("observed_at"),
        "as_of": decorated.get("as_of"),
        "fetched_at": decorated.get("fetched_at"),
        "unit": decorated.get("unit"),
        "frequency": decorated.get("frequency"),
        "status": decorated.get("status") or "ok",
    }


def dxy_unavailable_record(*, fetched_at: str | None = None) -> dict[str, Any]:
    return {
        "source": DXY_UNAVAILABLE["source"],
        "series_or_symbol": None,
        "series": None,
        "symbol": None,
        "observed_at": None,
        "as_of": None,
        "fetched_at": fetched_at,
        "unit": None,
        "frequency": None,
        "status": "not_configured",
        "availability": "unavailable",
        "reason_code": DXY_UNAVAILABLE["reason_code"],
        "note": DXY_UNAVAILABLE["note"],
    }


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
    validate_unit(metric, spec["unit"])
    if observation.get("unit"):
        validate_unit(metric, str(observation["unit"]))
    return {
        "event_type": metric,
        "event_time": event_time.isoformat(),
        "name": spec["name"],
        "actual": observation["value"],
        "consensus": None,
        "prior": None,
        "unit": spec["unit"],
        "series": spec["series_id"],
        "series_or_symbol": spec["series_id"],
        "frequency": spec["frequency"],
        "observed_at": fetched_at,
        "as_of": period,
        "fetched_at": fetched_at,
        "status": "stale" if from_cache else "ok",
        "surprise": "unknown",
        "confirmed": True,
        "source": "FRED",
        "notes": json.dumps(notes, ensure_ascii=False),
    }


def _empty_series_report(*, fetched_at: str, reason_code: str, status: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "series_or_symbol": None,
        "observed_at": None,
        "as_of": None,
        "fetched_at": fetched_at,
        "unit": None,
        "frequency": None,
        "source": "FRED",
    }


def sync_fred_market_series(settings: Settings | None = None, store=None) -> dict[str, Any]:
    settings = settings or Settings()
    fetched_at = utc_now()
    report: dict[str, Any] = {"fetched_at": fetched_at, "series": {}}
    dxy = dxy_unavailable_record(fetched_at=fetched_at)
    report["series"]["dxy"] = {
        **dxy,
        "series_id": None,
        "note": DXY_UNAVAILABLE["note"],
    }
    if not settings.fred_api_key:
        for metric, spec in FRED_MARKET_SERIES.items():
            report["series"][metric] = {
                **_empty_series_report(
                    fetched_at=fetched_at,
                    reason_code="source_not_configured",
                    status="not_configured",
                ),
                "series_or_symbol": spec["series_id"],
                "unit": spec["unit"],
                "frequency": spec["frequency"],
            }
        return report
    for metric, spec in FRED_MARKET_SERIES.items():
        try:
            result = fetch_fred_series(spec["series_id"], settings.fred_api_key)
            rows = parse_fred_observations(result.payload)
            if not rows:
                report["series"][metric] = {
                    **_empty_series_report(
                        fetched_at=result.fetched_at,
                        reason_code="upstream_empty",
                        status="missing",
                    ),
                    "series_or_symbol": spec["series_id"],
                    "unit": spec["unit"],
                    "frequency": spec["frequency"],
                }
                continue
            latest = rows[0]
            if latest.get("unit"):
                validate_unit(metric, str(latest["unit"]))
            event = build_macro_event(
                metric,
                latest,
                spec,
                fetched_at=result.fetched_at,
                from_cache=result.from_cache,
            )
            if store is not None:
                store(event)
            rec = normalized_record(event)
            report["series"][metric] = {
                **rec,
                "reason_code": result.reason_code,
                "period": latest["period"],
                "from_cache": result.from_cache,
                "series_id": spec["series_id"],
            }
        except FetchError as exc:
            status = "stale" if exc.reason_code == "record_stale" else "error"
            if exc.reason_code == "record_invalid":
                status = "invalid"
            report["series"][metric] = {
                **_empty_series_report(
                    fetched_at=fetched_at,
                    reason_code=exc.reason_code,
                    status=status,
                ),
                "series_or_symbol": spec["series_id"],
                "unit": spec["unit"],
                "frequency": spec["frequency"],
            }
    return report
