"""Shared HTTP fetch: timeout, limited retry, 429 backoff, last-success cache.

Never invents numeric values. Cache hits are marked stale/from_cache.
API keys must not be written into cache files or error strings.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SECRET_QUERY_KEYS = ("api_key", "apikey", "token", "secret", "password", "authorization")


class FetchError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class FetchResult:
    payload: Any
    status: str
    reason_code: str
    fetched_at: str
    from_cache: bool
    cache_key: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cache_dir(settings_dir: str | None = None) -> Path:
    raw = settings_dir or os.getenv("STOCK_PM_CACHE_DIR") or "/tmp/stock-pm-cache"
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scrub(text: str) -> str:
    lowered = text.lower()
    if any(key in lowered for key in SECRET_QUERY_KEYS):
        return "upstream request failed"
    return text


def _cache_path(directory: Path, cache_key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in cache_key)
    return directory / f"{safe}.json"


def read_cache(cache_key: str, directory: Path | None = None) -> dict[str, Any] | None:
    path = _cache_path(directory or cache_dir(), cache_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "payload" not in payload:
        return None
    return payload


def write_cache(cache_key: str, payload: Any, directory: Path | None = None) -> None:
    path = _cache_path(directory or cache_dir(), cache_key)
    record = {
        "cache_key": cache_key,
        "fetched_at": utc_now(),
        "payload": payload,
    }
    dumped = json.dumps(record, ensure_ascii=False)
    if any(key in dumped.lower() for key in SECRET_QUERY_KEYS):
        return
    path.write_text(dumped, encoding="utf-8")


def json_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
    retries: int = 3,
    cache_key: str | None = None,
    directory: Path | None = None,
) -> FetchResult:
    last_error: Exception | None = None
    store = directory or cache_dir()
    for attempt in range(max(1, retries)):
        try:
            request = Request(url, headers=headers or {"Accept": "application/json", "User-Agent": "stock-pm/0.9"})
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if cache_key:
                write_cache(cache_key, payload, store)
            return FetchResult(
                payload=payload,
                status="ok",
                reason_code="within_threshold",
                fetched_at=utc_now(),
                from_cache=False,
                cache_key=cache_key,
            )
        except HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            reason = "rate_limited" if exc.code == 429 else "query_error"
            break
        except (TimeoutError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            reason = "timeout" if isinstance(exc, (TimeoutError, URLError)) else "query_error"
            break
    cached = read_cache(cache_key, store) if cache_key else None
    if cached:
        return FetchResult(
            payload=cached["payload"],
            status="stale",
            reason_code="record_stale",
            fetched_at=str(cached.get("fetched_at") or utc_now()),
            from_cache=True,
            cache_key=cache_key,
        )
    message = _scrub(str(last_error or "query failed"))
    raise FetchError(reason if "reason" in locals() else "query_error", message)
