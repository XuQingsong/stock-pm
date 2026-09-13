"""HTTP helpers for official RSS/Atom feeds. Fetched bodies are untrusted data."""

from __future__ import annotations

import gzip
import io
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

from .policy import http_redirect_allowed, sanitize_untrusted


class _OfficialHostRedirectHandler(HTTPRedirectHandler):
    """Follow HTTP redirects only when the next hop stays on the same official host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        current = getattr(req, "full_url", None) or req.get_full_url()
        if not http_redirect_allowed(current, newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_OfficialHostRedirectHandler)


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class FeedResponse:
    url: str
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None
    content_type: str
    not_modified: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.not_modified or 200 <= self.status_code < 300)


class RateLimiter:
    def __init__(self, min_interval: float = 0.2) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self._last + self.min_interval - now
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


def strip_markup(text: str, *, max_len: int | None = 4000) -> str:
    """Drop HTML/script so feed bodies cannot execute or inject instructions."""
    raw = unescape(str(text or ""))
    raw = SCRIPT_RE.sub(" ", raw)
    raw = STYLE_RE.sub(" ", raw)
    raw = TAG_RE.sub(" ", raw)
    lines = []
    for line in raw.splitlines():
        collapsed = SPACE_RE.sub(" ", line).strip()
        if collapsed:
            lines.append(collapsed)
    return sanitize_untrusted("\n".join(lines), max_len=max_len)


def parse_datetime(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        stamp = parsedate_to_datetime(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except ValueError:
        return None


def _decode_body(raw: bytes, encoding_header: str | None) -> bytes:
    if raw[:2] == b"\x1f\x8b" or (encoding_header or "").lower() == "gzip":
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except OSError:
            return raw
    return raw


def fetch_feed(
    url: str,
    *,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = 30,
    limiter: RateLimiter | None = None,
    retries: int = 2,
) -> FeedResponse:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    }
    if extra_headers:
        headers.update(extra_headers)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    last_error: str | None = None
    for attempt in range(retries + 1):
        if limiter is not None:
            limiter.wait()
        req = Request(url, headers=headers, method="GET")
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                raw = _decode_body(resp.read(), resp.headers.get("Content-Encoding"))
                return FeedResponse(
                    url=url,
                    status_code=getattr(resp, "status", 200),
                    body=raw,
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                    content_type=resp.headers.get("Content-Type") or "",
                )
        except HTTPError as exc:
            if exc.code == 304:
                return FeedResponse(
                    url=url,
                    status_code=304,
                    body=b"",
                    etag=exc.headers.get("ETag") if exc.headers else etag,
                    last_modified=exc.headers.get("Last-Modified") if exc.headers else last_modified,
                    content_type=exc.headers.get("Content-Type") if exc.headers else "",
                    not_modified=True,
                )
            last_error = f"http_{exc.code}"
            if exc.code in {400, 401, 403, 404, 410}:
                break
            time.sleep(0.4 * (2 ** attempt))
        except TimeoutError:
            last_error = "timeout"
            time.sleep(0.4 * (2 ** attempt))
        except (URLError, OSError):
            last_error = "request_failed"
            time.sleep(0.4 * (2 ** attempt))
    return FeedResponse(
        url=url,
        status_code=0,
        body=b"",
        etag=etag,
        last_modified=last_modified,
        content_type="",
        error=last_error or "request_failed",
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if _local(child.tag) in names:
            return (child.text or "").strip()
    return ""


def _child_href(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if _local(child.tag) in names:
            href = (child.attrib.get("href") or child.attrib.get("url") or "").strip()
            if href:
                return href
            text = (child.text or "").strip()
            if text:
                return text
    return ""


def parse_feed_items(xml_bytes: bytes, *, base_url: str = "") -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom 1.0. Unknown markup is ignored, never executed."""
    if not xml_bytes:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    rows: list[dict[str, Any]] = []
    nodes = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    for node in nodes:
        title = strip_markup(_child_text(node, {"title"}))
        link = _child_href(node, {"link"}).strip()
        if link and not link.startswith("http"):
            link = urljoin(base_url, link)
        published = parse_datetime(
            _child_text(node, {"pubdate", "published", "updated", "date"})
        )
        summary = strip_markup(
            _child_text(node, {"description", "summary", "content"})
        )
        entry_id = strip_markup(_child_text(node, {"id", "guid"}))
        if not title or not link:
            continue
        rows.append(
            {
                "title": title,
                "url": link,
                "published_at": published,
                "summary": summary,
                "entry_id": entry_id,
            }
        )
    return rows
