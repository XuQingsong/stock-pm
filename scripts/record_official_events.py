#!/usr/bin/env python3
"""Record minimal fields from verified official originals. No full-text archive."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import ssl
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

from stock_pm.events.feeds import parse_datetime, strip_markup
from stock_pm.events.replay import RECORDED_PACK_PATH, compute_pack_hash

UA = "stock-pm research AdminContact@example.com"
CTX = ssl.create_default_context()

# Verified 200 OK in this environment. Annotations are derived from the page
# titles/excerpts, not invented facts.
SPECS = [
    {
        "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm",
        "publisher": "Federal Reserve Board",
        "event_type": "central_bank_rates",
        "entities": ["FOMC", "US", "June 2026"],
        "countries": ["US"],
        "status": "active",
        "scenario": "e2_fomc",
        "document_role": "statement",
        "title_override": None,
        "claim": "Federal Reserve issues FOMC statement; maintains the federal funds target range.",
        "required_tokens": ["fomc statement"],
    },
    {
        "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617b.htm",
        "publisher": "Federal Reserve Board",
        "event_type": "central_bank_rates",
        "entities": ["FOMC", "US", "June 2026"],
        "countries": ["US"],
        "status": "active",
        "scenario": "e2_fomc",
        "document_role": "projections",
        "title_override": None,
        "claim": "Federal Reserve Board and FOMC release economic projections from the June 16-17 FOMC meeting.",
        "required_tokens": ["economic projections", "june 16-17"],
    },
    {
        "source_url": "https://www.federalreserve.gov/monetarypolicy/fomcminutes20260617.htm",
        "publisher": "Federal Reserve Board",
        "event_type": "central_bank_rates",
        "entities": ["FOMC", "US", "June 2026"],
        "countries": ["US"],
        "status": "updated",
        "scenario": "e2_fomc",
        "document_role": "minutes",
        "title_override": "Minutes of the Federal Open Market Committee, June 16-17, 2026",
        "claim": "FOMC minutes for the June 16-17, 2026 meeting update the same rate decision record.",
        "required_tokens": ["minutes", "june 16-17"],
    },
    {
        "source_url": "https://www.eia.gov/pressroom/releases/press588.php",
        "publisher": "U.S. Energy Information Administration",
        "event_type": "war_sanctions",
        "entities": ["Iran", "oil", "Hormuz"],
        "countries": ["US", "IR"],
        "status": "active",
        "scenario": "e9_hormuz",
        "document_role": "forecast_update",
        "phase": "disruption",
        "title_override": None,
        "claim": "EIA updates forecast amid continued Mideast disruption to Middle Eastern oil flows through Hormuz.",
        "required_tokens": ["continued mideast disruption"],
    },
    {
        "source_url": "https://www.eia.gov/pressroom/releases/press589.php",
        "publisher": "U.S. Energy Information Administration",
        "event_type": "war_sanctions",
        "entities": ["Iran", "oil", "Hormuz"],
        "countries": ["US", "IR"],
        "status": "updated",
        "scenario": "e9_hormuz",
        "document_role": "forecast_update",
        "phase": "demand_buffer",
        "supersedes_url": "https://www.eia.gov/pressroom/releases/press588.php",
        "title_override": None,
        "claim": "EIA expects a drop in global oil demand will limit price increases from Hormuz disruptions.",
        "required_tokens": ["drop in global oil demand", "hormuz"],
    },
    {
        "source_url": "https://www.eia.gov/pressroom/releases/press590.php",
        "publisher": "U.S. Energy Information Administration",
        "event_type": "war_sanctions",
        "entities": ["Iran", "oil", "Hormuz"],
        "countries": ["US", "IR"],
        "status": "updated",
        "scenario": "e9_hormuz",
        "document_role": "forecast_update",
        "phase": "reopen_supply",
        "supersedes_url": "https://www.eia.gov/pressroom/releases/press589.php",
        "title_override": None,
        "claim": "EIA increases global oil production forecast after the opening of the Strait of Hormuz.",
        "required_tokens": ["opening of the strait of hormuz", "production forecast"],
    },
]


def _fetch(url: str) -> tuple[int, bytes, str | None]:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urlopen(req, timeout=40, context=CTX) as resp:
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return getattr(resp, "status", 200), raw, resp.headers.get("Last-Modified")


def _title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    return strip_markup(unescape(re.sub(r"\s+", " ", match.group(1))))


def _published(title: str, html: str, last_modified: str | None) -> str | None:
    header = parse_datetime(last_modified)
    if header:
        return header
    titled = re.search(r"\((\d{2})/(\d{2})/(\d{4})\)", title or "")
    if titled:
        return f"{titled.group(3)}-{titled.group(1)}-{titled.group(2)}T12:00:00+00:00"
    stamped = re.search(r'<time[^>]+datetime=["\']([^"\']+)', html or "", flags=re.I)
    if stamped:
        return parse_datetime(stamped.group(1))
    return None


def record() -> dict:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    documents = []
    for spec in SPECS:
        status, raw, last_modified = _fetch(spec["source_url"])
        if status != 200:
            raise RuntimeError(f"{spec['source_url']} HTTP {status}")
        html = raw.decode("utf-8", "replace")
        title = spec.get("title_override") or _title(html)
        excerpt = strip_markup(html)[:400]
        published = _published(title, html, last_modified)
        documents.append(
            {
                "source_url": spec["source_url"],
                "publisher": spec["publisher"],
                "title": title,
                "published_at": published,
                "event_time": published,
                "fetched_at": fetched_at,
                "http_status": status,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "excerpt": excerpt,
                "event_type": spec["event_type"],
                "entities": spec["entities"],
                "countries": spec["countries"],
                "claims": [spec["claim"]],
                "status": spec["status"],
                "scenario": spec["scenario"],
                "document_role": spec.get("document_role"),
                "evidence_role": "event_fact",
                "phase": spec.get("phase"),
                "supersedes_url": spec.get("supersedes_url"),
                "required_tokens": spec.get("required_tokens") or [],
                "provider": "official",
            }
        )
    pack = {
        "pack_id": "events_recorded_5b",
        "data_class": "recorded_replay",
        "live": False,
        "note": (
            "Minimal excerpts from reachable official originals. "
            "Not production live prints. Full pages are not stored."
        ),
        "recorded_at": fetched_at,
        "documents": documents,
    }
    pack["integrity_sha256"] = compute_pack_hash(pack)
    return pack


def main() -> None:
    pack = record()
    RECORDED_PACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORDED_PACK_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(RECORDED_PACK_PATH), "documents": len(pack["documents"]), "hash": pack["integrity_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
