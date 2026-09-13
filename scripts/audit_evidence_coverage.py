#!/usr/bin/env python3
"""Freeze a live official-document sample and classify withheld reasons.

This is an audit tool. It does not change production evidence gates.
Fixture/demo documents are rejected. HTML probes are labeled counterfactual.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from stock_pm.config import Settings
from stock_pm.events.analyze import (
    analyze_event,
    closed_loop_summary,
    inspect_closed_loop,
)
from stock_pm.events.dedupe import build_events
from stock_pm.events.evidence import excerpt_supports_claim, select_claim_support_excerpt
from stock_pm.events.feeds import RateLimiter, fetch_feed, strip_markup
from stock_pm.events.live import discover_live_documents, live_provider_coverage
from stock_pm.events.policy import events_data_mode
from stock_pm.events.types import EventDocument, TrustedEvent

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = Path(os.environ.get("AUDIT_OUT", "/tmp/evidence-coverage-audit"))
HTML_LIMITER = RateLimiter(0.35)

PRIMARY_REASONS = (
    "fetch_failure",
    "body_missing",
    "parser_failure",
    "claim_not_supported",
    "no_official_url",
    "no_exposure",
    "chain_incomplete",
    "superseded_or_no_material_change",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _publisher_group(publisher: str, url: str) -> str:
    host = (url or "").lower()
    pub = (publisher or "").lower()
    if "sec.gov" in host or "edgar" in pub:
        return "sec_edgar"
    if "federalreserve.gov" in host or "federal reserve" in pub:
        return "federal_reserve"
    if "eia.gov" in host or "energy information" in pub:
        return "eia_press"
    return "other"


def _claim_tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9\u4e00-\u9fff]{4,}", (text or "").lower())]


def classify_current(event: TrustedEvent) -> dict[str, Any]:
    loop = inspect_closed_loop(event)
    analysis = event.analysis or {}
    withheld = analysis.get("withheld") or {}
    claims = list(event.claims or [])
    live_claims = [row for row in claims if row.status not in {"superseded", "revoked"}]
    excerpts = [str(row.excerpt or "").strip() for row in live_claims]
    claim_texts = [str(row.text or "").strip() for row in live_claims]
    rss_body = next((item for item in excerpts if item), "")
    official_url = ""
    for source in event.sources:
        if str(source.source_url or "").startswith("http"):
            official_url = source.source_url
            break
    primary = None
    secondary: list[str] = []
    if loop["valid"]:
        return {
            "valid": True,
            "primary_reason": None,
            "secondary_reasons": [],
            "loop": loop,
            "withheld_status": withheld.get("status"),
            "withheld_reason": withheld.get("reason"),
            "official_url": official_url,
            "rss_excerpt_len": len(rss_body),
            "claim_count": len(live_claims),
        }
    if not loop["official_ok"]:
        primary = "no_official_url"
    elif not any(claim_texts) and not any(excerpts):
        primary = "body_missing"
    elif not loop["excerpt_ok"]:
        if not any(excerpts):
            primary = "body_missing"
        else:
            primary = "claim_not_supported"
    elif not loop["exposure_ok"]:
        primary = "no_exposure"
    elif event.status == "revoked" or all(row.status in {"superseded", "revoked"} for row in claims):
        primary = "superseded_or_no_material_change"
    else:
        primary = "chain_incomplete"
    if primary != "claim_not_supported" and not loop["excerpt_ok"]:
        secondary.append("claim_not_supported" if any(excerpts) else "body_missing")
    if primary != "no_exposure" and not loop["exposure_ok"]:
        secondary.append("no_exposure")
    if primary != "chain_incomplete" and not loop["chain_ok"]:
        secondary.append("chain_incomplete")
    if event.status in {"revoked", "superseded"} and primary != "superseded_or_no_material_change":
        secondary.append("superseded_or_no_material_change")
    return {
        "valid": False,
        "primary_reason": primary,
        "secondary_reasons": [item for item in secondary if item != primary],
        "loop": loop,
        "withheld_status": withheld.get("status"),
        "withheld_reason": withheld.get("reason"),
        "official_url": official_url,
        "rss_excerpt_len": len(rss_body),
        "claim_count": len(live_claims),
    }


def probe_html(url: str, claim: str, user_agent: str) -> dict[str, Any]:
    fetched_at = _now()
    if not url.startswith("http"):
        return {
            "url": url,
            "fetched_at": fetched_at,
            "http_status": 0,
            "error": "no_official_url",
            "body_hash": None,
            "cleaned_len": 0,
            "would_support_claim": False,
            "probe_reason": "no_official_url",
        }
    extra = {"Host": "www.sec.gov"} if "sec.gov" in url.lower() else None
    resp = fetch_feed(
        url,
        user_agent=user_agent,
        extra_headers=extra,
        limiter=HTML_LIMITER,
        timeout=35,
        retries=2,
    )
    if resp.error or not resp.ok:
        return {
            "url": url,
            "fetched_at": fetched_at,
            "http_status": resp.status_code,
            "error": resp.error or f"http_{resp.status_code}",
            "body_hash": None,
            "cleaned_len": 0,
            "would_support_claim": False,
            "probe_reason": "fetch_failure",
        }
    raw = resp.body or b""
    html = raw.decode("utf-8", "replace")
    cleaned = strip_markup(html, max_len=None)
    body_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest() if cleaned else None
    if not cleaned.strip():
        return {
            "url": url,
            "fetched_at": fetched_at,
            "http_status": resp.status_code,
            "error": None,
            "body_hash": body_hash,
            "cleaned_len": 0,
            "would_support_claim": False,
            "probe_reason": "body_missing",
        }
    tokens = [word for word in _claim_tokens(claim) if word not in {"http", "https", "www"}][:8]
    would = excerpt_supports_claim(claim, cleaned)
    probe_reason = "ok" if would else "claim_not_supported"
    excerpt = ""
    excerpt_error = None
    if tokens:
        try:
            window = select_claim_support_excerpt(cleaned, tokens[:3] if len(tokens) >= 2 else tokens)
            excerpt = window.get("claim_support_excerpt") or ""
            if excerpt and excerpt_supports_claim(claim, excerpt):
                would = True
                probe_reason = "ok"
        except ValueError as exc:
            excerpt_error = str(exc)
            if probe_reason == "ok":
                probe_reason = "parser_failure"
    return {
        "url": url,
        "fetched_at": fetched_at,
        "http_status": resp.status_code,
        "error": None,
        "body_hash": body_hash,
        "cleaned_len": len(cleaned),
        "would_support_claim": would,
        "probe_reason": probe_reason,
        "excerpt": excerpt[:480],
        "excerpt_error": excerpt_error,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "etag": resp.etag,
        "last_modified": resp.last_modified,
    }


def freeze_document(doc: EventDocument) -> dict[str, Any]:
    return {
        "title": doc.title,
        "url": doc.url,
        "publisher": doc.publisher,
        "published_at": doc.published_at,
        "event_type": doc.event_type,
        "entities": list(doc.entities),
        "countries": list(doc.countries),
        "claims": list(doc.claims),
        "body": doc.body,
        "provider": doc.provider,
        "status": doc.status,
        "document_role": doc.document_role,
        "evidence_role": doc.evidence_role,
        "supersedes_url": doc.supersedes_url,
        "body_sha256": hashlib.sha256((doc.body or "").encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit live official evidence coverage")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--probe-html", action="store_true", default=True)
    parser.add_argument("--no-probe-html", action="store_false", dest="probe_html")
    parser.add_argument("--max-sec-probes", type=int, default=12)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=True)
    os.environ.pop("APP_ENV", None)
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ["STOCK_PM_EVENTS_MODE"] = "empty"
    os.environ["STOCK_PM_EVENTS_LIVE"] = "1"
    os.environ.setdefault("SEC_EDGAR_USER_AGENT", "stock-pm research AdminContact@example.com")
    settings = Settings()
    mode = events_data_mode(settings)
    if mode in {"demo", "fixture", "recorded_replay", "replay"}:
        raise SystemExit(f"refusing to audit non-live mode={mode}")
    fetched_at = _now()
    docs = discover_live_documents(settings)
    if any((doc.provider or "") == "fixture" for doc in docs):
        raise SystemExit("fixture documents appeared in live discover")
    events = build_events(docs)
    for event in events:
        analyze_event(event)
    summary = closed_loop_summary(events)
    coverage = live_provider_coverage(settings)
    rows = []
    probes_done: dict[str, dict[str, Any]] = {}
    sec_probes = 0
    ua = os.environ.get("SEC_EDGAR_USER_AGENT") or "stock-pm research AdminContact@example.com"
    for event in events:
        classified = classify_current(event)
        publisher = event.sources[0].publisher if event.sources else ""
        url = classified["official_url"]
        group = _publisher_group(publisher, url)
        probe = None
        should_probe = args.probe_html and url.startswith("http")
        if should_probe and group == "sec_edgar":
            if classified["valid"] or classified["primary_reason"] not in {"body_missing", "claim_not_supported"}:
                should_probe = False
            elif sec_probes >= args.max_sec_probes:
                should_probe = False
        if should_probe:
            claim = (event.claims[0].text if event.claims else event.canonical_title) or event.canonical_title
            if url not in probes_done:
                probes_done[url] = probe_html(url, claim, ua if group == "sec_edgar" else "stock-pm official-feed/5c")
                if group == "sec_edgar":
                    sec_probes += 1
            probe = probes_done[url]
        rows.append(
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "event_type": event.event_type,
                "publisher": publisher,
                "provider": group,
                "status": event.status,
                "url": url,
                "published_at": event.published_at,
                "fetched_at": fetched_at,
                **classified,
                "html_probe": probe,
            }
        )
    withheld_rows = [row for row in rows if not row["valid"]]
    unsupported_rows = [row for row in rows if row["loop"]["unsupported"]]
    reason_counts = Counter(row["primary_reason"] for row in withheld_rows)
    unsupported_reasons = Counter(row["primary_reason"] for row in unsupported_rows)
    by_provider = Counter((row["provider"], row["primary_reason"]) for row in withheld_rows)
    by_type = Counter((row["event_type"], row["primary_reason"]) for row in withheld_rows)
    fixable = []
    for row in withheld_rows:
        probe = row.get("html_probe") or {}
        if (
            row["primary_reason"] in {"body_missing", "claim_not_supported", "parser_failure"}
            and probe.get("would_support_claim")
            and row["loop"].get("exposure_ok")
        ):
            fixable.append(row)
        elif (
            row["primary_reason"] in {"body_missing", "claim_not_supported"}
            and probe.get("would_support_claim")
            and not row["loop"].get("exposure_ok")
        ):
            row.setdefault("secondary_reasons", []).append("no_exposure")
    pack = {
        "audit_id": "events_5c_a_baseline",
        "data_class": "frozen_official_audit",
        "live": True,
        "fixture": False,
        "fetched_at": fetched_at,
        "mode": mode,
        "summary": summary,
        "provider_coverage": coverage,
        "reason_counts": dict(reason_counts),
        "unsupported_reason_counts": dict(unsupported_reasons),
        "by_provider_reason": {f"{k[0]}|{k[1]}": v for k, v in by_provider.items()},
        "by_type_reason": {f"{k[0]}|{k[1]}": v for k, v in by_type.items()},
        "fixable_if_html_and_exposure": len(fixable),
        "fixable_event_ids": [row["event_id"] for row in fixable],
        "events": rows,
        "documents": [freeze_document(doc) for doc in docs],
        "html_probes": probes_done,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "baseline.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(path),
                "events": len(rows),
                "documents": len(docs),
                "summary": summary,
                "reason_counts": dict(reason_counts),
                "unsupported_reason_counts": dict(unsupported_reasons),
                "by_provider_reason": pack["by_provider_reason"],
                "fixable_if_html_and_exposure": len(fixable),
                "html_probes": len(probes_done),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
