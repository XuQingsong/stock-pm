"""High-confidence published_at recovery. Never guess relative dates."""

from __future__ import annotations

import json
import re
from typing import Any

from .clients import parse_published


_RELATIVE = re.compile(r"\b(ago|yesterday|today|tomorrow|last\s+week)\b", re.I)
_JSONLD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_JSONLD_DATE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I)
_OG_PUBLISHED = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|pubdate|publishdate|dc.date.issued|parsely-pub-date|publication_date|sailthru.date)["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_OG_PUBLISHED_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:article:published_time|pubdate|publishdate|parsely-pub-date|publication_date)["\']',
    re.I,
)
_TIME_DATETIME = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I)
_ITEMPROP = re.compile(
    r'(?:itemprop=["\']datePublished["\'][^>]+(?:content|datetime)=["\']([^"\']+)["\']|(?:content|datetime)=["\']([^"\']+)["\'][^>]*itemprop=["\']datePublished["\'])',
    re.I,
)


def _confident(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _RELATIVE.search(text):
        return None
    return parse_published(text)


def _from_jsonld(blob: str) -> str | None:
    for match in _JSONLD_BLOCK.finditer(blob):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            found = _JSONLD_DATE.search(raw)
            parsed = _confident(found.group(1) if found else None)
            if parsed:
                return parsed
            continue
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            graph = row.get("@graph")
            candidates = graph if isinstance(graph, list) else [row]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                found = _confident(item.get("datePublished"))
                if found:
                    return found
    found = _JSONLD_DATE.search(blob)
    return _confident(found.group(1) if found else None)


def recover_published_at(html_or_text: Any) -> str | None:
    """Return YYYY-MM-DD only from explicit publisher metadata. None if uncertain."""
    blob = str(html_or_text or "")
    if not blob.strip():
        return None
    found = _from_jsonld(blob)
    if found:
        return found
    for pattern in (_OG_PUBLISHED, _OG_PUBLISHED_REV, _TIME_DATETIME, _ITEMPROP):
        match = pattern.search(blob)
        if match:
            parsed = _confident(next((group for group in match.groups() if group), None))
            if parsed:
                return parsed
    return None
