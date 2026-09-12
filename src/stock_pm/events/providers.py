"""Pluggable discovery providers. Google HTML is never scraped."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stock_pm.config import Settings

from .policy import sanitize_untrusted
from .types import EventDocument


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
            )
        )
    return rows


class OfficialFeedProvider:
    name = "official_feed"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.limiter = RateLimiter(0.2)

    def configured(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "status": "ok",
            "reason_code": None,
            "role": "official_fact",
        }

    def discover(self, *, query: str | None = None) -> list[EventDocument]:
        self.limiter.wait()
        docs = [row for row in load_fixture_documents() if row.provider in {"official", "media", "research"}]
        if query:
            needle = query.lower()
            docs = [row for row in docs if needle in row.title.lower() or needle in row.event_type]
        return [row for row in docs if row.provider != "google"]


class GoogleDiscoveryProvider:
    """Official Programmable Search JSON API only. Missing keys => not_configured."""

    name = "google_cse"
    API = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.limiter = RateLimiter(1.0)

    def _key(self) -> str:
        return (getattr(self.settings, "google_cse_api_key", None) or os.getenv("GOOGLE_CSE_API_KEY") or "").strip()

    def _cx(self) -> str:
        return (getattr(self.settings, "google_cse_id", None) or os.getenv("GOOGLE_CSE_ID") or "").strip()

    def configured(self) -> bool:
        return bool(self._key() and self._cx())

    def status(self) -> dict[str, Any]:
        if not self.configured():
            return {
                "provider": self.name,
                "status": "not_configured",
                "reason_code": "source_not_configured",
                "role": "discovery_only",
            }
        return {
            "provider": self.name,
            "status": "ok",
            "reason_code": None,
            "role": "discovery_only",
        }

    def discover(self, *, query: str | None = None) -> list[EventDocument]:
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
        req = Request(f"{self.API}?{params}", headers={"User-Agent": "stock-pm-events/5b"})
        payload: dict[str, Any] = {}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(req, timeout=12) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                last_error = None
                break
            except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
                time.sleep(0.4 * (2 ** attempt))
        if last_error is not None:
            return []
        rows = []
        for item in payload.get("items") or []:
            link = str(item.get("link") or "")
            host = link.lower()
            if "google.com" in host and "/search" in host:
                continue
            if host.startswith("https://www.google.com/search") or host.startswith("http://www.google.com/search"):
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
                )
            )
        return rows


def provider_coverage(settings: Settings | None = None) -> dict[str, Any]:
    official = OfficialFeedProvider(settings)
    google = GoogleDiscoveryProvider(settings)
    return {
        "official_feed": official.status(),
        "google_cse": google.status(),
        "note": "Google is discovery only. Missing keys stay not_configured. HTML search pages are never fetched.",
    }
