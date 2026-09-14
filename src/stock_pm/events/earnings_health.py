"""Per-symbol earnings health. Never fills missing numbers with inferred values."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from stock_pm.fetch import cache_dir, utc_now


REASON_CODES = (
    "not_configured",
    "unsupported",
    "rate_limited",
    "stale",
    "upstream_empty",
    "period_mismatch",
    "baseline_missing",
    "query_error",
    "source_not_configured",
    "skipped_dependency",
    "record_invalid",
)
FIELD_NAMES = ("actual", "prior", "consensus", "transcript")
AV_ENDPOINTS = ("EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT")
BUCKET_EARNINGS_UNMET = 0
BUCKET_COMPLEMENT_UNMET = 1
BUCKET_REFRESH = 2
# Raw Alpha Vantage payload cache (json_get) is last-success. Older than this is stale, not deleted.
FRESHNESS_DAYS = 120
# Scheduling last_attempt_at stays valid for rotation. It is not an inferred number fill.
SCHEDULE_TTL_DAYS = 30
HEALTH_CACHE_NAME = "earnings_coverage.json"
CACHE_TTL = {
    "av_payload_freshness_days": FRESHNESS_DAYS,
    "schedule_ttl_days": SCHEDULE_TTL_DAYS,
    "health_persist": "until_explicit_purge",
    "note": "AV raw cache and earnings_coverage.json are separate. reset_cache/job refresh must not delete either.",
}
RETRY_BY_REASON = {
    "rate_limited": timedelta(minutes=15),
    "upstream_empty": timedelta(hours=6),
    "query_error": timedelta(hours=6),
    "unsupported": timedelta(hours=24),
    "not_configured": timedelta(hours=1),
    "source_not_configured": timedelta(hours=1),
    "stale": timedelta(hours=6),
    "period_mismatch": timedelta(hours=24),
    "baseline_missing": timedelta(hours=6),
    "skipped_dependency": timedelta(hours=24),
    "record_invalid": timedelta(hours=6),
}

_STATE: dict[str, Any] = {}
_INJECT: dict[str, str] = {}


def clear_earnings_health_memory() -> None:
    """Drop in-process health only. Persistent schedule/health files stay on disk."""
    _STATE.clear()


def purge_earnings_health_persist() -> None:
    """Explicit fixture/test cleanup. Production reset_cache/job must not call this."""
    clear_earnings_health_memory()
    try:
        path = health_cache_path()
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def reset_earnings_health() -> None:
    """Request/job refresh alias: memory only. Does not delete persist."""
    clear_earnings_health_memory()


def reset_earnings_inject() -> None:
    _INJECT.clear()


def set_earnings_inject(mapping: dict[str, str] | None) -> None:
    reset_earnings_inject()
    if mapping:
        _INJECT.update({str(key).upper(): str(value) for key, value in mapping.items()})


def parse_inject_env() -> None:
    raw = (os.getenv("STOCK_PM_EARNINGS_INJECT") or "").strip()
    if not raw:
        return
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        mapping[key.strip()] = value.strip()
    if mapping:
        set_earnings_inject(mapping)


def injected_reason(symbol: str, function: str | None = None) -> str | None:
    symbol = str(symbol or "").upper()
    if not symbol:
        return None
    if function:
        hit = _INJECT.get(f"{symbol}:{function.upper()}")
        if hit:
            return hit
    return _INJECT.get(symbol)


def _parse_stamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_stale(fetched_at: str | None, *, days: int = FRESHNESS_DAYS) -> bool:
    stamp = _parse_stamp(fetched_at)
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp > timedelta(days=days)


def cache_age_days(fetched_at: str | None) -> float | None:
    stamp = _parse_stamp(fetched_at)
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - stamp).total_seconds() / 86400, 3)


def next_retry_at(reason_code: str | None, *, now: str | None = None) -> str:
    stamp = _parse_stamp(now) or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    delta = RETRY_BY_REASON.get(str(reason_code or ""), timedelta(hours=12))
    return (stamp + delta).replace(microsecond=0).isoformat()


def field_record(
    *,
    status: str,
    reason_code: str | None = None,
    as_of: str | None = None,
    fetched_at: str | None = None,
    last_success_at: str | None = None,
    source: str = "none",
    next_retry: str | None = None,
) -> dict[str, Any]:
    success_at = last_success_at or (fetched_at if status == "ok" else None)
    fresh = "unknown"
    if success_at and is_stale(success_at):
        fresh = "expired"
    elif fetched_at and status == "ok" and source == "live" and reason_code not in {"stale", "rate_limited", "query_error"} and not is_stale(fetched_at):
        fresh = "fresh"
    elif status in {"stale"} or source == "cache" or is_stale(fetched_at) or reason_code in {"stale", "rate_limited", "query_error"}:
        if success_at or fetched_at:
            fresh = "stale"
    return {
        "status": status,
        "reason_code": reason_code or "",
        "as_of": as_of,
        "fetched_at": fetched_at,
        "freshness": fresh,
        "last_success_at": success_at,
        "cache_age_days": cache_age_days(success_at),
        "source": source,
        "next_retry_at": next_retry or next_retry_at(reason_code or ("stale" if fresh in {"stale", "expired"} else status)),
    }


def empty_fields(*, reason_code: str, source: str = "none", fetched_at: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        name: field_record(status=reason_code if reason_code in {"not_configured", "unsupported", "rate_limited"} else "missing", reason_code=reason_code, source=source, fetched_at=fetched_at)
        for name in FIELD_NAMES
    }


def endpoint_record(
    *,
    status: str = "pending",
    last_attempt_at: str | None = None,
    last_success_at: str | None = None,
    reason_code: str | None = None,
    source: str = "none",
    quarter: str | None = None,
    period: str | None = None,
    this_round: bool = False,
    next_retry: str | None = None,
) -> dict[str, Any]:
    success_at = last_success_at if status in {"ok", "stale"} else None
    fresh = "unknown"
    if success_at and is_stale(success_at):
        fresh = "expired"
    elif success_at and status == "ok" and source == "live" and reason_code not in {"rate_limited", "query_error", "stale"}:
        fresh = "fresh"
    elif success_at and status in {"ok", "stale"}:
        fresh = "stale"
    return {
        "status": status,
        "last_attempt_at": last_attempt_at,
        "last_success_at": success_at,
        "cache_age_days": cache_age_days(success_at),
        "reason_code": reason_code or "",
        "source": source,
        "freshness": fresh,
        "quarter": quarter or "",
        "period": period or "",
        "this_round": bool(this_round),
        "next_retry_at": next_retry or (
            next_retry_at(reason_code or status, now=last_attempt_at) if last_attempt_at or reason_code else None
        ),
    }


def empty_endpoints() -> dict[str, dict[str, Any]]:
    return {name: endpoint_record(status="pending") for name in AV_ENDPOINTS}


def merge_endpoints(
    previous: dict[str, Any] | None,
    updates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    merged = empty_endpoints()
    for name, row in (previous or {}).items():
        if name in merged and isinstance(row, dict):
            merged[name] = {**merged[name], **row, "this_round": False}
    for name, row in (updates or {}).items():
        if name in merged and isinstance(row, dict):
            merged[name] = {**merged[name], **row}
    return merged


def _legacy_endpoint(row: dict[str, Any], endpoint: str) -> dict[str, Any]:
    stored = ((row or {}).get("endpoints") or {}).get(endpoint)
    if isinstance(stored, dict) and (stored.get("status") or stored.get("last_attempt_at") or stored.get("last_success_at")):
        return dict(stored)
    if endpoint == "EARNINGS" and (row or {}).get("last_attempt_at"):
        return endpoint_record(
            status="ok" if row.get("last_success_at") else "failed",
            last_attempt_at=row.get("last_attempt_at"),
            last_success_at=row.get("last_success_at"),
            reason_code=row.get("reason_code"),
            source=str(row.get("source") or "none"),
        )
    return endpoint_record(status="pending")


def _is_fresh_success(rec: dict[str, Any]) -> bool:
    """Live semantic success only. Displayable cache/stale must not block upstream retry."""
    if rec.get("status") == "unsupported":
        return True
    if rec.get("status") != "ok":
        return False
    if rec.get("source") != "live":
        return False
    if rec.get("reason_code") in {"rate_limited", "query_error", "stale"}:
        return False
    success = rec.get("last_success_at")
    return bool(success) and not is_stale(str(success))


def _retry_due(rec: dict[str, Any]) -> bool:
    if rec.get("status") == "unsupported":
        return False
    if rec.get("status") == "skipped_dependency":
        return False
    if _is_fresh_success(rec):
        return False
    nxt = rec.get("next_retry_at")
    stamp = _parse_stamp(str(nxt) if nxt else None)
    if stamp is not None:
        now = datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return now >= stamp
    return True


def earnings_usable(rec: dict[str, Any]) -> bool:
    """Displayable semantic cache or live print. Does not mean upstream retry is done."""
    if rec.get("status") not in {"ok", "stale"}:
        return False
    if not rec.get("last_success_at"):
        return False
    return bool(rec.get("quarter") or rec.get("period"))


def symbol_health(
    symbol: str,
    *,
    asset_class: str,
    supported: bool,
    fields: dict[str, dict[str, Any]] | None = None,
    reason_code: str | None = None,
    last_success_at: str | None = None,
    next_retry: str | None = None,
    implication: str | None = None,
    scenario: str | None = None,
    source: str = "none",
    gap: str | None = None,
    missing_fields: list[str] | None = None,
    last_attempt_at: str | None = None,
    this_round_calls: int = 0,
    this_round: str | None = None,
    endpoints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = fields or empty_fields(reason_code=reason_code or ("unsupported" if not supported else "upstream_empty"), source=source)
    successes = [str(row.get("last_success_at") or "") for row in rows.values() if row.get("last_success_at")]
    stamp = last_success_at or (max(successes) if successes else None)
    codes = [str(row.get("reason_code") or "") for row in rows.values() if row.get("reason_code")]
    primary = reason_code or next((code for code in codes if code), "")
    return {
        "symbol": symbol.upper(),
        "asset_class": asset_class,
        "supported": supported,
        "reason_code": primary,
        "fields": rows,
        "last_success_at": stamp,
        "cache_age_days": cache_age_days(stamp),
        "last_attempt_at": last_attempt_at,
        "this_round_calls": int(this_round_calls or 0),
        "this_round": this_round,
        "next_retry_at": next_retry or next_retry_at(primary or None, now=last_attempt_at),
        "implication": implication,
        "scenario": scenario,
        "source": source,
        "gap": gap,
        "missing_fields": list(missing_fields)
        if missing_fields is not None
        else [name for name, row in rows.items() if row.get("status") not in {"ok"}],
        "endpoints": endpoints or empty_endpoints(),
    }


def health_cache_path() -> Any:
    return cache_dir() / HEALTH_CACHE_NAME


def persist_health(report: dict[str, Any]) -> None:
    report = dict(report)
    report.setdefault("cache_ttl", CACHE_TTL)
    _STATE.clear()
    _STATE.update(deepcopy(report))
    path = health_cache_path()
    dumped = json.dumps(report, ensure_ascii=False)
    if any(token in dumped.lower() for token in ("apikey", "api_key", "alpha_vantage_api_key")):
        return
    try:
        path.write_text(dumped, encoding="utf-8")
    except OSError:
        return


def load_persisted_health() -> dict[str, Any]:
    if _STATE:
        return deepcopy(_STATE)
    path = health_cache_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        _STATE.update(payload)
        return deepcopy(payload)
    return {}


def current_earnings_health() -> dict[str, Any]:
    return deepcopy(_STATE) if _STATE else load_persisted_health()


def health_for_symbol(symbol: str) -> dict[str, Any]:
    report = current_earnings_health()
    rows = report.get("symbols") or {}
    return deepcopy(rows.get(str(symbol or "").upper()) or {})


def print_is_complete(row: dict[str, Any]) -> bool:
    if row.get("supported") is False:
        return False
    if row.get("gap"):
        return False
    if row.get("scenario") == "complete":
        return True
    fields = row.get("fields") or {}
    needed = ("actual", "prior", "consensus")
    return all((fields.get(name) or {}).get("status") in {"ok", "stale"} and (fields.get(name) or {}).get("source") != "none" for name in needed) and not row.get("missing_fields")


def _fresh_live_complete(row: dict[str, Any]) -> bool:
    if not print_is_complete(row):
        return False
    if row.get("this_round") == "deferred":
        return False
    earn = ((row.get("endpoints") or {}).get("EARNINGS") or {})
    if earn:
        if not earn.get("this_round") or earn.get("source") != "live":
            return False
    elif row.get("source") != "live" or int(row.get("this_round_calls") or 0) <= 0:
        return False
    fields = row.get("fields") or {}
    if any((fields.get(name) or {}).get("freshness") in {"stale", "expired"} for name in ("actual", "prior", "consensus")):
        return False
    return True


def _cache_stale_complete(row: dict[str, Any]) -> bool:
    if not print_is_complete(row):
        return False
    return not _fresh_live_complete(row)


def prioritize_symbols(stocks: list[str], previous: dict[str, Any] | None) -> list[str]:
    """Never-attempted first, then oldest last_attempt_at. Failed attempts still rotate."""
    rows = (previous or {}).get("symbols") or {}
    schedule = (previous or {}).get("schedule") or {}

    def attempted_at(symbol: str) -> str:
        row = rows.get(symbol) or {}
        return str(row.get("last_attempt_at") or "")

    never = [symbol for symbol in stocks if not attempted_at(symbol)]
    seen = [symbol for symbol in stocks if attempted_at(symbol)]
    seen.sort(key=lambda symbol: (attempted_at(symbol), stocks.index(symbol)))
    ordered = never + seen
    nxt = str(schedule.get("next_symbol") or "")
    if nxt in ordered and not never:
        idx = ordered.index(nxt)
        ordered = ordered[idx:] + ordered[:idx]
    return ordered


def pending_endpoint_tasks(symbol: str, row: dict[str, Any] | None) -> list[tuple[str, str, str, int]]:
    """Return (symbol, endpoint, last_attempt_at, bucket) still needing a call."""
    row = row or {}
    earn = _legacy_endpoint(row, "EARNINGS")
    est = _legacy_endpoint(row, "EARNINGS_ESTIMATES")
    transcript = _legacy_endpoint(row, "EARNINGS_CALL_TRANSCRIPT")
    tasks: list[tuple[str, str, str, int]] = []
    if not _is_fresh_success(earn) and _retry_due(earn):
        bucket = BUCKET_REFRESH if earn.get("last_success_at") else BUCKET_EARNINGS_UNMET
        tasks.append((symbol, "EARNINGS", str(earn.get("last_attempt_at") or ""), bucket))
    if earnings_usable(earn):
        if not _is_fresh_success(est) and _retry_due(est):
            bucket = BUCKET_REFRESH if est.get("last_success_at") else BUCKET_COMPLEMENT_UNMET
            tasks.append((symbol, "EARNINGS_ESTIMATES", str(est.get("last_attempt_at") or ""), bucket))
        if earn.get("quarter"):
            if not _is_fresh_success(transcript) and _retry_due(transcript):
                bucket = BUCKET_REFRESH if transcript.get("last_success_at") else BUCKET_COMPLEMENT_UNMET
                tasks.append(
                    (symbol, "EARNINGS_CALL_TRANSCRIPT", str(transcript.get("last_attempt_at") or ""), bucket)
                )
    return tasks


def prioritize_endpoint_tasks(stocks: list[str], previous: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Fair symbol×endpoint order. Fresh EARNINGS is not re-fetched so complements can run."""
    rows = (previous or {}).get("symbols") or {}
    schedule = (previous or {}).get("schedule") or {}
    collected: list[tuple[str, str, str, int]] = []
    for symbol in stocks:
        collected.extend(pending_endpoint_tasks(symbol, rows.get(symbol) or {}))
    collected.sort(
        key=lambda item: (
            item[3],
            0 if not item[2] else 1,
            item[2],
            stocks.index(item[0]) if item[0] in stocks else 0,
            AV_ENDPOINTS.index(item[1]) if item[1] in AV_ENDPOINTS else 0,
        )
    )
    nxt = schedule.get("next_task") or {}
    nxt_key = (str(nxt.get("symbol") or ""), str(nxt.get("endpoint") or ""))
    if nxt_key[0] and nxt_key[1] and any((item[0], item[1]) == nxt_key for item in collected):
        bucket = next(item[3] for item in collected if (item[0], item[1]) == nxt_key)
        head = [item for item in collected if item[3] < bucket]
        mid = [item for item in collected if item[3] == bucket]
        tail = [item for item in collected if item[3] > bucket]
        idx = next(i for i, item in enumerate(mid) if (item[0], item[1]) == nxt_key)
        collected = head + mid[idx:] + mid[:idx] + tail
    return [(item[0], item[1]) for item in collected]


def attempted_symbols(entries: list[Any]) -> list[str]:
    out: list[str] = []
    for item in entries or []:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if symbol and symbol not in out:
            out.append(str(symbol))
    return out


def endpoint_coverage(payload: dict[str, Any] | None) -> dict[str, Any]:
    report = payload or {}
    this_round = {name: {"attempted": 0, "success": 0, "symbols": []} for name in AV_ENDPOINTS}
    cumulative = {
        name: {
            "attempted_symbols": [],
            "success_symbols": [],
            "pending_symbols": [],
            "skipped_dependency_symbols": [],
        }
        for name in AV_ENDPOINTS
    }
    for item in (report.get("schedule") or {}).get("attempted_this_round") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("endpoint") or "")
        symbol = str(item.get("symbol") or "")
        if name not in this_round or not symbol:
            continue
        this_round[name]["attempted"] += 1
        if symbol not in this_round[name]["symbols"]:
            this_round[name]["symbols"].append(symbol)
    for symbol, row in (report.get("symbols") or {}).items():
        if not isinstance(row, dict) or row.get("supported") is False:
            continue
        for name in AV_ENDPOINTS:
            rec = _legacy_endpoint(row, name)
            semantic_ok = rec.get("status") in {"ok", "stale"} and rec.get("last_success_at")
            if rec.get("this_round") and semantic_ok and rec.get("source") == "live":
                this_round[name]["success"] += 1
            if rec.get("last_attempt_at") or rec.get("status") == "skipped_dependency":
                if symbol not in cumulative[name]["attempted_symbols"]:
                    cumulative[name]["attempted_symbols"].append(symbol)
            if semantic_ok and symbol not in cumulative[name]["success_symbols"]:
                cumulative[name]["success_symbols"].append(symbol)
            if rec.get("status") == "skipped_dependency":
                cumulative[name]["skipped_dependency_symbols"].append(symbol)
            elif not _is_fresh_success(rec) and rec.get("status") != "unsupported":
                if symbol not in cumulative[name]["pending_symbols"]:
                    cumulative[name]["pending_symbols"].append(symbol)
    return {"this_round": this_round, "cumulative": cumulative}


def summarize_health(report: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = report or current_earnings_health()
    symbols = payload.get("symbols") or {}
    complete = 0
    partial = 0
    unsupported = 0
    rate_limited = 0
    not_configured = 0
    deferred = 0
    fresh_live = 0
    cache_stale = 0
    for row in symbols.values():
        if not isinstance(row, dict):
            continue
        if row.get("supported") is False or row.get("reason_code") == "unsupported":
            unsupported += 1
            continue
        if row.get("reason_code") in {"not_configured", "source_not_configured"}:
            not_configured += 1
            continue
        if row.get("this_round") == "deferred" or row.get("scenario") == "deferred":
            deferred += 1
        fields = row.get("fields") or {}
        limited = any(item.get("reason_code") == "rate_limited" for item in fields.values())
        if limited:
            rate_limited += 1
        if print_is_complete(row):
            complete += 1
            if _fresh_live_complete(row):
                fresh_live += 1
            else:
                cache_stale += 1
        else:
            if row.get("scenario") != "deferred":
                partial += 1
    live = bool(payload.get("live"))
    return {
        "live": live,
        "data_class": payload.get("data_class") or ("live_current" if live else "unknown"),
        "as_of": payload.get("as_of"),
        "complete_count": complete,
        "partial_count": partial,
        "unsupported_count": unsupported,
        "rate_limited_count": rate_limited,
        "not_configured_count": not_configured,
        "deferred_count": deferred,
        "symbol_count": len(symbols),
        "fixture_complete_count": 0 if live else complete,
        "fresh_live_complete_count": fresh_live if live else 0,
        "cache_stale_complete_count": cache_stale if live else 0,
        "live_complete_count": fresh_live if live else 0,
        "budget": payload.get("budget") or {},
        "schedule": payload.get("schedule") or {},
        "endpoints": payload.get("endpoints") or endpoint_coverage(payload),
        "cache_ttl": payload.get("cache_ttl") or CACHE_TTL,
        "symbols": symbols,
        "note": payload.get("note")
        or (
            "Live-current coverage only. Cache/stale complete is not this-round live complete."
            if live
            else "Frozen/fixture coverage is not production live coverage."
        ),
    }


def fields_from_evidence(
    evidence: Any,
    *,
    outcomes: dict[str, dict[str, Any]] | None = None,
    source: str = "live",
) -> dict[str, dict[str, Any]]:
    outcomes = outcomes or {}
    fetched = getattr(evidence, "fetched_at", None)
    bindings = getattr(evidence, "field_bindings", None) or {}
    gap = getattr(evidence, "gap", None)

    def _from_binding(name: str, attr: str, endpoint: str) -> dict[str, Any]:
        binding = bindings.get(name) or bindings.get(attr) or {}
        value = getattr(evidence, attr, None)
        outcome = outcomes.get(endpoint) or {}
        reason = outcome.get("reason_code")
        field_source = outcome.get("source") or source
        if value is None and not binding:
            if gap == "period_mismatch":
                reason = reason or "period_mismatch"
            elif reason in {None, ""}:
                reason = "upstream_empty"
            status = "rate_limited" if reason == "rate_limited" else (
                "unsupported" if reason == "unsupported" else (
                    "not_configured" if reason in {"not_configured", "source_not_configured"} else (
                        "stale" if field_source == "cache" else "missing"
                    )
                )
            )
            if reason == "skipped_dependency":
                status = "missing"
            return field_record(
                status=status,
                reason_code=reason,
                fetched_at=outcome.get("fetched_at") or fetched,
                last_success_at=outcome.get("last_success_at"),
                source=field_source,
                next_retry=outcome.get("next_retry_at"),
            )
        status = "stale" if field_source == "cache" or reason in {"stale", "rate_limited", "query_error"} else "ok"
        if reason in {"rate_limited", "query_error"} and field_source == "cache":
            status = "stale"
        return field_record(
            status=status,
            reason_code=reason if status != "ok" else "",
            as_of=binding.get("as_of") or getattr(evidence, "as_of", None),
            fetched_at=outcome.get("fetched_at") or binding.get("fetched_at") or fetched,
            last_success_at=outcome.get("last_success_at") or binding.get("fetched_at") or (
                fetched if field_source == "live" and status == "ok" else None
            ),
            source=field_source,
            next_retry=outcome.get("next_retry_at"),
        )

    transcript_outcome = outcomes.get("EARNINGS_CALL_TRANSCRIPT") or {}
    excerpts = getattr(evidence, "transcript_excerpts", None) or []
    if excerpts:
        tr_status = "stale" if transcript_outcome.get("source") == "cache" or transcript_outcome.get("reason_code") in {"stale", "rate_limited", "query_error"} else "ok"
        transcript = field_record(
            status=tr_status,
            reason_code=transcript_outcome.get("reason_code") if tr_status != "ok" else "",
            as_of=excerpts[0].get("quarter") if isinstance(excerpts[0], dict) else None,
            fetched_at=transcript_outcome.get("fetched_at")
            or (excerpts[0].get("fetched_at") if isinstance(excerpts[0], dict) else fetched),
            last_success_at=transcript_outcome.get("last_success_at")
            or (fetched if (transcript_outcome.get("source") or source) == "live" else None),
            source=transcript_outcome.get("source") or source,
            next_retry=transcript_outcome.get("next_retry_at"),
        )
    else:
        reason = transcript_outcome.get("reason_code") or "upstream_empty"
        transcript = field_record(
            status="rate_limited" if reason == "rate_limited" else (
                "unsupported" if reason == "unsupported" else (
                    "not_configured" if reason in {"not_configured", "source_not_configured"} else "missing"
                )
            ),
            reason_code=reason,
            fetched_at=transcript_outcome.get("fetched_at") or fetched,
            last_success_at=transcript_outcome.get("last_success_at"),
            source=transcript_outcome.get("source") or source,
            next_retry=transcript_outcome.get("next_retry_at"),
        )
    return {
        "actual": _from_binding("actual", "actual", "EARNINGS"),
        "prior": _from_binding("prior_year_actual", "prior_year_actual", "EARNINGS"),
        "consensus": _from_binding("consensus", "consensus", "EARNINGS"),
        "transcript": transcript,
    }
