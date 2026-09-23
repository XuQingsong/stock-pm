"""Per-source freshness targets and silent-failure detection.

A source is "silent" when fetches succeed but the newest item stops
advancing while the source is expected to be publishing. Health state is
kept in the existing ``event_job_cursors`` table under ``news:<source>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from stock_pm.calendar import NY_TZ, is_trading_day

from .timeutil import minutes_between, normalize_published, utc_now

CURSOR_PREFIX = "news:"
HEALTH_STATUSES = ("ok", "idle", "degraded", "silent", "stale", "down", "not_configured")


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source: str
    max_fetch_age_min: float
    silence_after_min: float | None
    active_start: time
    active_end: time
    trading_days_only: bool = True


# EDGAR accepts filings 06:00–22:00 ET on federal business days; the NYSE calendar
# is used as an approximation (it differs on Good Friday, Columbus and Veterans Day).
DEFAULT_POLICIES: dict[str, SourcePolicy] = {
    "sec_edgar": SourcePolicy("sec_edgar", 30, 90, time(6, 0), time(22, 0)),
    "alpha_vantage_news": SourcePolicy("alpha_vantage_news", 180, 24 * 60, time(4, 0), time(20, 0)),
    "nasdaq_news": SourcePolicy("nasdaq_news", 26 * 60, 3 * 24 * 60, time(0, 0), time(23, 59)),
    "federal_reserve": SourcePolicy("federal_reserve", 26 * 60, None, time(0, 0), time(23, 59), trading_days_only=False),
    "eia": SourcePolicy("eia", 26 * 60, None, time(0, 0), time(23, 59), trading_days_only=False),
}


def in_active_window(policy: SourcePolicy, now: datetime) -> bool:
    local = now.astimezone(NY_TZ)
    if policy.trading_days_only and not is_trading_day(local.date()):
        return False
    return policy.active_start <= local.time() <= policy.active_end


def evaluate_health(
    policy: SourcePolicy,
    *,
    configured: bool,
    last_attempt: datetime | None,
    last_success: datetime | None,
    last_attempt_ok: bool,
    newest_published: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    active = in_active_window(policy, current)
    fetch_age = minutes_between(last_success, current)
    silence = minutes_between(newest_published, current)
    report: dict[str, Any] = {
        "source": policy.source,
        "active_window": active,
        "fetch_age_min": fetch_age,
        "newest_item_age_min": silence,
        "max_fetch_age_min": policy.max_fetch_age_min,
        "silence_after_min": policy.silence_after_min,
    }
    success_fresh = fetch_age is not None and fetch_age <= policy.max_fetch_age_min

    if not configured:
        status, reason = "not_configured", "source_not_configured"
    elif last_success is None and last_attempt is None:
        status, reason = "stale", "never_run"
    elif not last_attempt_ok and not success_fresh:
        status, reason = "down", "query_error"
    elif not success_fresh:
        status, reason = ("stale", "record_stale") if active else ("idle", "outside_window")
    elif not last_attempt_ok:
        status, reason = "degraded", "last_attempt_failed"
    elif active and policy.silence_after_min is not None and (silence is None or silence > policy.silence_after_min):
        status, reason = "silent", "upstream_silent"
    elif active:
        status, reason = "ok", None
    else:
        status, reason = "idle", "outside_window"
    report.update({"status": status, "reason_code": reason})
    return report


def cursor_row(
    source: str,
    *,
    ok: bool,
    reason_code: str | None,
    item_count: int,
    newest_published: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keyword arguments for ``events.store.persist_cursor``."""
    stamp = (now or utc_now()).isoformat()
    return {
        "provider": f"{CURSOR_PREFIX}{source}",
        "status": "ok" if ok else "error",
        "reason_code": reason_code,
        "item_count": item_count,
        "stamp": stamp,
        "cursor_json": {"newest_published_at": newest_published.isoformat() if newest_published else None},
    }


def _stamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    parsed = normalize_published(value, naive_tz="UTC") if value else None
    return parsed.utc if parsed else None


def health_from_cursor(
    row: dict[str, Any] | None,
    policy: SourcePolicy,
    *,
    configured: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    row = row or {}
    cursor = row.get("cursor_json") or {}
    return evaluate_health(
        policy,
        configured=configured,
        last_attempt=_stamp(row.get("last_attempt")),
        last_success=_stamp(row.get("last_success")),
        last_attempt_ok=str(row.get("status") or "") == "ok",
        newest_published=_stamp(cursor.get("newest_published_at")),
        now=now,
    )
