"""URL / title / content / event dedupe. Keep the best publisher copy."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .quality import canonical_url, host_of, source_tier


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def _norm_title(value: Any) -> str:
    text = _PUNCT.sub(" ", str(value or "").lower())
    return _WS.sub(" ", text).strip()


def _content_key(value: Any) -> str:
    text = _WS.sub(" ", str(value or "").lower()).strip()
    return text[:480]


def _similar(left: str, right: str, *, threshold: float) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold


def _score(row: dict[str, Any]) -> tuple[int, int, int]:
    text = str(row.get("clean_text") or row.get("raw_text") or "")
    return (
        0 if row.get("is_primary_source") else 1,
        int(row.get("source_tier") or 5),
        -len(text),
    )


def dedupe_documents(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Return unique documents and the count removed."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        url = canonical_url(row.get("url") or row.get("canonical_url"))
        title = _norm_title(row.get("title"))
        content = _content_key(row.get("clean_text") or row.get("raw_text"))
        published = str(row.get("published_at") or "")[:10]
        host = host_of(url)
        duplicate_of = None
        for idx, existing in enumerate(kept):
            other_url = canonical_url(existing.get("url") or existing.get("canonical_url"))
            if url and other_url and url == other_url:
                duplicate_of = idx
                break
            other_title = _norm_title(existing.get("title"))
            other_content = _content_key(existing.get("clean_text") or existing.get("raw_text"))
            other_day = str(existing.get("published_at") or "")[:10]
            title_hit = _similar(title, other_title, threshold=0.86)
            content_hit = bool(content and other_content and _similar(content, other_content, threshold=0.82))
            same_event = title_hit and (not published or not other_day or published == other_day)
            syndicate = title_hit and host_of(other_url) != host
            if content_hit or same_event or syndicate:
                duplicate_of = idx
                break
        row = dict(row)
        row["canonical_url"] = url
        if duplicate_of is None:
            kept.append(row)
            continue
        winner, loser = kept[duplicate_of], row
        if _score(row) < _score(winner):
            winner, loser = row, winner
        meta = dict(winner.get("metadata") or {})
        dupes = list(meta.get("duplicate_urls") or [])
        other = str(loser.get("url") or "")
        if other and other not in dupes and other != winner.get("url"):
            dupes.append(other)
        meta["duplicate_urls"] = dupes[:8]
        meta["duplicates"] = int(meta.get("duplicates") or 0) + 1
        winner["metadata"] = meta
        kept[duplicate_of] = winner
    return kept, max(0, len(rows) - len(kept))
