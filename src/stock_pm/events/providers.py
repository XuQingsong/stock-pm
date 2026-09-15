"""Pluggable discovery providers. Google HTML is never scraped."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stock_pm.config import Settings

from .budget import budget_exhausted, capped_timeout, remaining_seconds
from .live import live_provider_coverage
from .policy import events_data_mode, is_safe_public_http_url, redact_url, sanitize_untrusted
from .replay import RecordedReplayProvider
from .types import EventDocument


GOOGLE_API = "https://www.googleapis.com/customsearch/v1"
FIXTURE_LABEL = "packaged seed/demo fixture · not live official ingest"


class RateLimiter:
    def __init__(self, min_interval: float = 1.0) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self._last + self.min_interval - now
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


def _fixture_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "events_5b.json"


def load_fixture_documents() -> list[EventDocument]:
    path = _fixture_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("documents") or []:
        rows.append(
            EventDocument(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                publisher=str(item.get("publisher") or ""),
                published_at=item.get("published_at"),
                event_type=str(item.get("event_type") or "other"),
                entities=list(item.get("entities") or []),
                countries=list(item.get("countries") or []),
                claims=list(item.get("claims") or []),
                body=sanitize_untrusted(str(item.get("body") or "")),
                provider=str(item.get("provider") or "official"),
                status=str(item.get("status") or "active"),
                document_role=item.get("document_role"),
                evidence_role=str(item.get("evidence_role") or "event_fact"),
                supersedes_url=item.get("supersedes_url"),
                body_source=str(item.get("body_source") or ""),
                author=item.get("author"),
                discovery_role=item.get("discovery_role"),
            )
        )
    return rows


class OfficialFeedProvider:
    """Fixture loader only. Production live ingest lives in live.py."""

    name = "official_feed"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.limiter = RateLimiter(0.2)
        self.mode = events_data_mode(self.settings)
        self.last_error: str | None = None

    def configured(self) -> bool:
        return self.mode in {"demo", "fixture"}

    def status(self) -> dict[str, Any]:
        if self.mode in {"demo", "fixture"}:
            return {
                "provider": self.name,
                "status": "demo_fixture",
                "live": False,
                "reason_code": "fixture_not_live",
                "role": "seed_or_test_fixture",
                "request_url": None,
                "last_success_at": None,
                "event_count": len(load_fixture_documents()),
                "note": FIXTURE_LABEL,
            }
        return {
            "provider": self.name,
            "status": "idle",
            "live": False,
            "reason_code": "fixture_loader_only",
            "role": "seed_or_test_fixture",
            "request_url": None,
            "last_success_at": None,
            "event_count": 0,
            "note": "Fixtures are not loaded in production. Live ingest is sec_edgar / federal_reserve / eia_press.",
        }

    def discover(self, *, query: str | None = None) -> list[EventDocument]:
        if self.mode not in {"demo", "fixture"}:
            return []
        self.limiter.wait()
        docs = [row for row in load_fixture_documents() if row.provider in {"official", "media", "research"}]
        if query:
            needle = query.lower()
            docs = [row for row in docs if needle in row.title.lower() or needle in row.event_type]
        return docs


class GoogleDiscoveryProvider:
    """Official Programmable Search JSON API only. Missing keys => not_configured."""

    name = "google_cse"
    API = GOOGLE_API

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.limiter = RateLimiter(1.0)
        self.last_error: str | None = None
        self.last_request_url: str | None = None
        self.last_success_at: str | None = None
        self.last_count = 0

    def _clean(self, raw: str) -> str:
        value = (raw or "").strip()
        if not value or value.startswith("your_"):
            return ""
        return value

    def _key(self) -> str:
        return self._clean(getattr(self.settings, "google_cse_api_key", None) or os.getenv("GOOGLE_CSE_API_KEY") or "")

    def _cx(self) -> str:
        return self._clean(getattr(self.settings, "google_cse_id", None) or os.getenv("GOOGLE_CSE_ID") or "")

    def configured(self) -> bool:
        return bool(self._key() and self._cx())

    def status(self) -> dict[str, Any]:
        if not self.configured():
            return {
                "provider": self.name,
                "status": "not_configured",
                "live": False,
                "reason_code": "source_not_configured",
                "role": "discovery_only",
                "request_url": self.API,
                "last_success_at": None,
                "event_count": 0,
            }
        if self.last_error:
            return {
                "provider": self.name,
                "status": "upstream_error",
                "live": False,
                "reason_code": self.last_error,
                "role": "discovery_only",
                "request_url": self.API,
                "last_success_at": self.last_success_at,
                "event_count": self.last_count,
            }
        return {
            "provider": self.name,
            "status": "configured_unverified" if self.last_success_at is None else "ok",
            "live": bool(self.last_success_at),
            "reason_code": None,
            "role": "discovery_only",
            "request_url": self.API,
            "last_success_at": self.last_success_at,
            "event_count": self.last_count,
        }

    def discover(self, *, query: str | None = None) -> list[EventDocument]:
        self.last_error = None
        if not self.configured():
            return []
        self.limiter.wait()
        params = urlencode(
            {
                "key": self._key(),
                "cx": self._cx(),
                "q": query or "site:treasury.gov OR site:sec.gov",
            }
        )
        raw_url = f"{self.API}?{params}"
        self.last_request_url = redact_url(raw_url)
        req = Request(raw_url, headers={"User-Agent": "stock-pm-events/5b"})
        payload: dict[str, Any] = {}
        last_error: Exception | None = None
        attempts = 1 if remaining_seconds() is not None else 3
        for attempt in range(attempts):
            if budget_exhausted():
                self.last_error = "timeout"
                return []
            try:
                with urlopen(req, timeout=capped_timeout(12)) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                last_error = None
                break
            except HTTPError as exc:
                last_error = exc
                self.last_error = f"http_{exc.code}"
                if exc.code in {400, 401, 403, 429}:
                    break
                time.sleep(0.4 * (2 ** attempt))
            except TimeoutError as exc:
                last_error = exc
                self.last_error = "timeout"
                time.sleep(0.4 * (2 ** attempt))
            except (URLError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
                self.last_error = "request_failed"
                time.sleep(0.4 * (2 ** attempt))
        if last_error is not None:
            return []
        rows = []
        for item in payload.get("items") or []:
            link = str(item.get("link") or "")
            if not is_safe_public_http_url(link):
                continue
            host = link.lower()
            if "google.com" in host and "/search" in host:
                continue
            rows.append(
                EventDocument(
                    title=str(item.get("title") or ""),
                    url=link,
                    publisher="Google CSE discovery",
                    published_at=None,
                    event_type="other",
                    body=sanitize_untrusted(str(item.get("snippet") or "")),
                    provider="google",
                    body_source="cse_snippet",
                    discovery_role="discovery_candidate",
                    evidence_role="discovery_candidate",
                )
            )
        from datetime import datetime, timezone

        self.last_success_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.last_count = len(rows)
        return rows


def provider_coverage(settings: Settings | None = None) -> dict[str, Any]:
    official = OfficialFeedProvider(settings)
    google = GoogleDiscoveryProvider(settings)
    live = live_provider_coverage(settings)
    mode = events_data_mode(settings)
    if mode == "recorded_replay":
        replay = RecordedReplayProvider().status()
    else:
        replay = {
            "provider": "recorded_replay",
            "status": "idle",
            "live": False,
            "reason_code": "replay_not_enabled",
            "role": "recorded_replay",
            "request_url": None,
            "last_success_at": None,
            "event_count": 0,
            "note": "Recorded replay is off. Production latest events stay live-only.",
        }
    return {
        "official_feed": official.status(),
        "google_cse": google.status(),
        "recorded_replay": replay,
        **live,
        "note": (
            "Production uses verified SEC / Federal Reserve / EIA feeds only. "
            "Google CSE is discovery-only and may stay not_configured. "
            "Fixtures are never live coverage."
        ),
    }
