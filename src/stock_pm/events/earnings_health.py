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
)
FIELD_NAMES = ("actual", "prior", "consensus", "transcript")
FRESHNESS_DAYS = 120
HEALTH_CACHE_NAME = "earnings_coverage.json"
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
}

_STATE: dict[str, Any] = {}
_INJECT: dict[str, str] = {}


def reset_earnings_health() -> None:
    _STATE.clear()
    try:
        path = health_cache_path()
        if path.is_file():
            path.unlink()
    except OSError:
        pass


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
    fresh = "unknown"
    if fetched_at and status == "ok" and not is_stale(fetched_at):
        fresh = "fresh"
    elif status in {"stale"} or source == "cache" or is_stale(fetched_at) or reason_code in {"stale", "rate_limited"}:
        if last_success_at or fetched_at:
            fresh = "stale"
    return {
        "status": status,
        "reason_code": reason_code or "",
        "as_of": as_of,
        "fetched_at": fetched_at,
        "freshness": fresh,
        "last_success_at": last_success_at or (fetched_at if status == "ok" else None),
        "source": source,
        "next_retry_at": next_retry or next_retry_at(reason_code or ("stale" if fresh == "stale" else status)),
    }


def empty_fields(*, reason_code: str, source: str = "none", fetched_at: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        name: field_record(status=reason_code if reason_code in {"not_configured", "unsupported", "rate_limited"} else "missing", reason_code=reason_code, source=source, fetched_at=fetched_at)
        for name in FIELD_NAMES
    }


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
        "next_retry_at": next_retry or next_retry_at(primary or None, now=stamp),
        "implication": implication,
        "scenario": scenario,
        "source": source,
        "gap": gap,
        "missing_fields": missing_fields or [
            name for name, row in rows.items() if row.get("status") not in {"ok"}
        ],
    }


def health_cache_path() -> Any:
    return cache_dir() / HEALTH_CACHE_NAME


def persist_health(report: dict[str, Any]) -> None:
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


def summarize_health(report: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = report or current_earnings_health()
    symbols = payload.get("symbols") or {}
    complete = 0
    partial = 0
    unsupported = 0
    rate_limited = 0
    not_configured = 0
    for row in symbols.values():
        if not isinstance(row, dict):
            continue
        if row.get("supported") is False or row.get("reason_code") == "unsupported":
            unsupported += 1
            continue
        if row.get("reason_code") in {"not_configured", "source_not_configured"}:
            not_configured += 1
            continue
        fields = row.get("fields") or {}
        limited = any(item.get("reason_code") == "rate_limited" for item in fields.values())
        if limited:
            rate_limited += 1
        missing = row.get("missing_fields") or [
            name for name, item in fields.items() if item.get("status") not in {"ok"}
        ]
        if row.get("gap") or missing:
            if row.get("scenario") == "complete" and not row.get("gap"):
                complete += 1
            else:
                partial += 1
        else:
            complete += 1
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
        "symbol_count": len(symbols),
        "fixture_complete_count": 0 if live else complete,
        "live_complete_count": complete if live else 0,
        "budget": payload.get("budget") or {},
        "symbols": symbols,
        "note": payload.get("note")
        or (
            "Live-current coverage only. Fixture success is not production coverage."
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
            return field_record(
                status=status,
                reason_code=reason,
                fetched_at=outcome.get("fetched_at") or fetched,
                last_success_at=outcome.get("last_success_at"),
                source=field_source,
            )
        status = "stale" if field_source == "cache" or reason in {"stale", "rate_limited"} else "ok"
        if reason == "rate_limited" and field_source == "cache":
            status = "stale"
        return field_record(
            status=status,
            reason_code=reason if status != "ok" else "",
            as_of=binding.get("as_of") or getattr(evidence, "as_of", None),
            fetched_at=binding.get("fetched_at") or outcome.get("fetched_at") or fetched,
            last_success_at=outcome.get("last_success_at") or binding.get("fetched_at") or fetched,
            source=field_source,
        )

    transcript_outcome = outcomes.get("EARNINGS_CALL_TRANSCRIPT") or {}
    excerpts = getattr(evidence, "transcript_excerpts", None) or []
    if excerpts:
        tr_status = "stale" if transcript_outcome.get("source") == "cache" or transcript_outcome.get("reason_code") in {"stale", "rate_limited"} else "ok"
        transcript = field_record(
            status=tr_status,
            reason_code=transcript_outcome.get("reason_code") if tr_status != "ok" else "",
            as_of=excerpts[0].get("quarter") if isinstance(excerpts[0], dict) else None,
            fetched_at=excerpts[0].get("fetched_at") if isinstance(excerpts[0], dict) else fetched,
            last_success_at=transcript_outcome.get("last_success_at") or fetched,
            source=transcript_outcome.get("source") or source,
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
        )
    return {
        "actual": _from_binding("actual", "actual", "EARNINGS"),
        "prior": _from_binding("prior_year_actual", "prior_year_actual", "EARNINGS"),
        "consensus": _from_binding("consensus", "consensus", "EARNINGS"),
        "transcript": transcript,
    }
