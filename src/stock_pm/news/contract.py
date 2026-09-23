"""RawArticle: one vendor item before story clustering.

Adapters fill what the vendor actually provides and leave the rest empty.
``missing_fields()`` names every gap so coverage reports stay honest; nothing
is back-filled by guessing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .timeutil import PublishedTime, session_fields

SOURCE_KINDS = ("official", "vendor_feed", "aggregator", "discovery")
SOURCE_KIND_RANK = {"official": 0, "vendor_feed": 1, "aggregator": 2, "discovery": 3}
EXTERNAL_ID_KINDS = ("sec_accession", "vendor_id", "guid", "url")

_TITLE_NOISE = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    return _TITLE_NOISE.sub(" ", (title or "").lower()).strip()


def title_fingerprint(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class RawArticle:
    source: str
    source_kind: str
    url: str
    canonical_url: str
    title: str
    published: PublishedTime
    fetched_at: datetime
    publisher: str | None = None
    external_id: str | None = None
    external_id_kind: str | None = None
    summary: str = ""
    body: str = ""
    authors: list[str] = field(default_factory=list)
    vendor_tickers: list[str] = field(default_factory=list)
    vendor_ticker_meta: list[dict[str, Any]] = field(default_factory=list)
    vendor_topics: list[str] = field(default_factory=list)
    company_scoped: bool = True
    sec_form: str | None = None
    sec_items: list[str] = field(default_factory=list)
    sec_accession: str | None = None
    sec_cik: str | None = None
    calendar_event: str | None = None
    language: str = "en"
    native: dict[str, Any] = field(default_factory=dict)
    also_seen_in: list[str] = field(default_factory=list)

    @property
    def published_at(self) -> datetime | None:
        return self.published.utc

    @property
    def dedupe_title(self) -> str:
        return title_fingerprint(self.title)

    @property
    def session(self) -> str:
        return str(session_fields(self.published)["session"])

    @property
    def reaction_date(self) -> date | None:
        value = session_fields(self.published)["reaction_date"]
        return value if isinstance(value, date) else None

    def missing_fields(self) -> list[str]:
        gaps: list[str] = []
        if not self.external_id:
            gaps.append("external_id")
        elif self.external_id_kind == "url":
            gaps.append("external_id:url_fallback")
        if self.published.utc is None:
            gaps.append("published_at")
        else:
            if not self.published.has_time_of_day:
                gaps.append("published_at:time_of_day")
            if not self.published.tz_explicit and self.published.tz_basis != "date_only":
                gaps.append("published_at:tz_assumed")
        if not self.publisher:
            gaps.append("publisher")
        if self.company_scoped and not self.vendor_tickers:
            gaps.append("vendor_tickers")
        if self.source_kind == "official" and self.sec_form:
            for name in ("sec_items", "sec_accession", "sec_cik"):
                if not getattr(self, name):
                    gaps.append(name)
        return gaps

    def as_dict(self) -> dict[str, Any]:
        fields = session_fields(self.published)
        reaction = fields["reaction_date"]
        return {
            "source": self.source,
            "source_kind": self.source_kind,
            "external_id": self.external_id,
            "external_id_kind": self.external_id_kind,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "summary": self.summary,
            "body": self.body,
            "publisher": self.publisher,
            "authors": list(self.authors),
            "published_at": self.published.iso,
            "published_raw": self.published.raw,
            "published_precision": self.published.precision,
            "published_tz_basis": self.published.tz_basis,
            "published_local_date": self.published.local_date.isoformat() if self.published.local_date else None,
            "session": fields["session"],
            "reaction_date": reaction.isoformat() if isinstance(reaction, date) else None,
            "fetched_at": self.fetched_at.isoformat(),
            "vendor_tickers": list(self.vendor_tickers),
            "vendor_ticker_meta": [dict(row) for row in self.vendor_ticker_meta],
            "vendor_topics": list(self.vendor_topics),
            "sec_form": self.sec_form,
            "sec_items": list(self.sec_items),
            "sec_accession": self.sec_accession,
            "sec_cik": self.sec_cik,
            "calendar_event": self.calendar_event,
            "language": self.language,
            "native": dict(self.native),
            "also_seen_in": list(self.also_seen_in),
            "missing_fields": self.missing_fields(),
        }
