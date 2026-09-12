"""Verified official event providers. URLs are documented endpoints, not guesses.

A) SEC EDGAR current 8-K Atom
   https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&...&output=atom
   Company Atom uses the same browse-edgar contract with action=getcompany.
   Fair-access UA: "Company Name AdminContact@domain.com"
   https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

B) Federal Reserve official feeds
   https://www.federalreserve.gov/feeds/press_all.xml
   https://www.federalreserve.gov/feeds/press_monetary.xml

C) EIA press releases listed on https://www.eia.gov/tools/rssfeeds/
   https://www.eia.gov/rss/press_rss.xml
   BLS RSS returned HTTP 403 from this environment; OFAC RSS was retired 2025-01-31.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from stock_pm.config import Settings

from .feeds import RateLimiter, fetch_feed, parse_feed_items, strip_markup
from .policy import events_data_mode, is_safe_public_http_url
from .types import EventDocument


# Documented current-filings Atom. type=8-K follows the SEC RSS example that uses type=10-k.
SEC_CURRENT_8K = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type=8-K&company=&dateb=&owner=include&start=0&count=40&output=atom"
)
SEC_COMPANY_ATOM = "https://www.sec.gov/cgi-bin/browse-edgar"
FED_PRESS_ALL = "https://www.federalreserve.gov/feeds/press_all.xml"
FED_PRESS_MONETARY = "https://www.federalreserve.gov/feeds/press_monetary.xml"
EIA_PRESS = "https://www.eia.gov/rss/press_rss.xml"
EIA_INDEX = "https://www.eia.gov/tools/rssfeeds/"

DEFAULT_SEC_UA = "stock-pm research AdminContact@example.com"
CIK_RE = re.compile(r"\((\d{6,10})\)")
ACCESSION_RE = re.compile(r"(?:accession-number=|AccNo:\s*)(\d{10}-\d{2}-\d{6})", re.I)
TITLE_NAME_RE = re.compile(r"^\s*(?:8-K|8-k)\s*-\s*(.+?)\s*\(\d{6,10}\)", re.I)
REVOKE_MARKERS = ("withdraws", "withdrawn", "rescinds", "repeals", "revokes")
UPDATE_MARKERS = ("update:", "amends", "amendment", "correction", "revised")
MONETARY_MARKERS = (
    "fomc",
    "federal funds",
    "monetary policy",
    "discount rate",
    "interest rate",
    "inflation",
    "balance sheet",
)
BANK_MARKERS = ("bank", "credit", "supervisory", "enforcement", "capital")
OIL_MARKERS = (
    "oil",
    "crude",
    "petroleum",
    "gasoline",
    "distillate",
    "wti",
    "brent",
    "hormuz",
    "opec",
    "inventory",
    "inventories",
    "natural gas",
    "lng",
)

# Zero-padded EDGAR CIKs for the seeded watchlist. Mapping is explicit; unknown CIKs stay unmapped.
WATCHLIST_CIKS: dict[str, str] = {
    "0000320193": "AAPL",
    "0001045810": "NVDA",
    "0000034088": "XOM",
    "0000019617": "JPM",
    "0000723125": "MU",
    "0000050863": "INTC",
    "0001652044": "GOOGL",
    "0001730168": "AVGO",
    "0000924619": "NOK",
}
DISPLAY_CIKS = ("0000320193", "0001045810", "0000034088", "0000019617")

_STATE: dict[str, dict[str, Any]] = {}
_SEC_LIMITER = RateLimiter(0.15)
_DEFAULT_LIMITER = RateLimiter(0.25)


def reset_live_state() -> None:
    _STATE.clear()


def live_ingest_enabled(settings: Settings | None = None) -> bool:
    flag = (os.getenv("STOCK_PM_EVENTS_LIVE") or "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return False
    return events_data_mode(settings) in {"empty", "live"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _status_from_title(title: str) -> str:
    lowered = title.lower()
    if any(marker in lowered for marker in REVOKE_MARKERS):
        return "revoked"
    if any(marker in lowered for marker in UPDATE_MARKERS):
        return "updated"
    return "active"


def _pad_cik(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits.zfill(10) if digits else ""


def _slug(url: str) -> str:
    path = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return path.split("?")[0] or "item"


def apply_cursor(provider: str, *, etag: str | None = None, last_modified: str | None = None) -> None:
    state = _STATE.setdefault(provider, {})
    if etag:
        state["etag"] = etag
    if last_modified:
        state["last_modified"] = last_modified


def _record(
    name: str,
    *,
    status: str,
    reason_code: str | None,
    docs: list[EventDocument],
    live: bool,
    request_url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    note: str = "",
) -> list[EventDocument]:
    state = _STATE.setdefault(name, {})
    state["status"] = status
    state["reason_code"] = reason_code
    state["event_count"] = len(docs)
    state["live"] = live
    state["request_url"] = request_url
    state["note"] = note
    if etag:
        state["etag"] = etag
    if last_modified:
        state["last_modified"] = last_modified
    if status == "ok":
        state["last_success_at"] = _now()
        state["docs"] = docs
    elif "docs" not in state:
        state["docs"] = []
    return docs


def _provider_status(name: str, *, role: str, default_url: str, disabled_note: str) -> dict[str, Any]:
    state = _STATE.get(name) or {}
    if not live_ingest_enabled():
        return {
            "provider": name,
            "status": "idle",
            "live": False,
            "reason_code": "live_fetch_disabled",
            "role": role,
            "request_url": default_url,
            "last_success_at": None,
            "event_count": 0,
            "etag": None,
            "last_modified": None,
            "note": disabled_note,
        }
    return {
        "provider": name,
        "status": state.get("status") or "configured_unverified",
        "live": bool(state.get("live")),
        "reason_code": state.get("reason_code"),
        "role": role,
        "request_url": state.get("request_url") or default_url,
        "last_success_at": state.get("last_success_at"),
        "event_count": int(state.get("event_count") or 0),
        "etag": state.get("etag"),
        "last_modified": state.get("last_modified"),
        "note": state.get("note") or "",
    }


def _fetch_items(
    url: str,
    *,
    name: str,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    allow_304: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = _STATE.get(name) or {}
    etag = state.get("etag") if allow_304 and state.get("docs") else None
    last_modified = state.get("last_modified") if allow_304 and state.get("docs") else None
    resp = fetch_feed(
        url,
        user_agent=user_agent,
        extra_headers=extra_headers,
        etag=etag,
        last_modified=last_modified,
        limiter=limiter,
    )
    meta = {
        "status_code": resp.status_code,
        "etag": resp.etag or etag,
        "last_modified": resp.last_modified or last_modified,
        "error": resp.error,
        "not_modified": resp.not_modified,
        "url": url,
    }
    if resp.not_modified and state.get("docs"):
        return [], meta
    if not resp.ok:
        meta["error"] = resp.error or f"http_{resp.status_code}"
        return [], meta
    return parse_feed_items(resp.body, base_url=url), meta


class SecEdgarProvider:
    name = "sec_edgar"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def user_agent(self) -> str:
        raw = (
            getattr(self.settings, "sec_edgar_user_agent", None)
            or os.getenv("SEC_EDGAR_USER_AGENT")
            or DEFAULT_SEC_UA
        ).strip()
        return raw

    def configured(self) -> bool:
        return "@" in self.user_agent()

    def status(self) -> dict[str, Any]:
        if not self.configured():
            return {
                "provider": self.name,
                "status": "not_configured",
                "live": False,
                "reason_code": "sec_user_agent_missing",
                "role": "official_fact",
                "request_url": SEC_CURRENT_8K,
                "last_success_at": None,
                "event_count": 0,
                "etag": None,
                "last_modified": None,
                "note": "SEC requires a descriptive User-Agent with a contact email.",
            }
        return _provider_status(
            self.name,
            role="official_fact",
            default_url=SEC_CURRENT_8K,
            disabled_note="Live SEC fetch disabled in this process.",
        )

    def _company_url(self, cik: str) -> str:
        query = urlencode(
            {
                "action": "getcompany",
                "CIK": cik,
                "type": "8-K",
                "dateb": "",
                "owner": "include",
                "count": "8",
                "output": "atom",
            }
        )
        return f"{SEC_COMPANY_ATOM}?{query}"

    def _to_doc(
        self,
        item: dict[str, Any],
        *,
        mapped_symbol: str | None = None,
        expected_cik: str | None = None,
    ) -> EventDocument | None:
        url = str(item.get("url") or "")
        if not is_safe_public_http_url(url) or "sec.gov" not in url.lower():
            return None
        title = strip_markup(str(item.get("title") or ""))
        blob = f"{title} {item.get('summary') or ''} {item.get('entry_id') or ''}"
        cik_match = CIK_RE.search(title) or CIK_RE.search(blob)
        cik = _pad_cik(cik_match.group(1)) if cik_match else ""
        if expected_cik and cik and cik != expected_cik:
            return None
        symbol = mapped_symbol if (mapped_symbol and (not cik or cik == expected_cik)) else WATCHLIST_CIKS.get(cik)
        accession_match = ACCESSION_RE.search(blob)
        accession = accession_match.group(1) if accession_match else _slug(url)
        name_match = TITLE_NAME_RE.search(title)
        company = strip_markup(name_match.group(1)) if name_match else ""
        entities = [item for item in (symbol, cik, accession, company) if item]
        if symbol is None and cik and cik not in WATCHLIST_CIKS:
            # Keep the filing on the market center; withhold from stock pages.
            entities.append("UNMAPPED_FILER")
        summary = strip_markup(str(item.get("summary") or ""))
        return EventDocument(
            title=title,
            url=url,
            publisher="SEC EDGAR",
            published_at=item.get("published_at"),
            event_type="company_filing",
            entities=entities,
            countries=["US"],
            claims=[title] + ([summary] if summary else []),
            body=summary,
            provider="official",
            status=_status_from_title(title),
        )

    def discover(self) -> list[EventDocument]:
        if not live_ingest_enabled(self.settings):
            return _record(
                self.name,
                status="idle",
                reason_code="live_fetch_disabled",
                docs=[],
                live=False,
                request_url=SEC_CURRENT_8K,
            )
        if not self.configured():
            return _record(
                self.name,
                status="not_configured",
                reason_code="sec_user_agent_missing",
                docs=[],
                live=False,
                request_url=SEC_CURRENT_8K,
            )
        try:
            items, meta = _fetch_items(
                SEC_CURRENT_8K,
                name=self.name,
                user_agent=self.user_agent(),
                extra_headers={"Host": "www.sec.gov"},
                limiter=_SEC_LIMITER,
            )
            if meta.get("not_modified"):
                cached = list((_STATE.get(self.name) or {}).get("docs") or [])
                return _record(
                    self.name,
                    status="ok",
                    reason_code=None,
                    docs=cached,
                    live=True,
                    request_url=SEC_CURRENT_8K,
                    etag=meta.get("etag"),
                    last_modified=meta.get("last_modified"),
                    note="304 Not Modified; reused previous SEC documents.",
                )
            if meta.get("error") and not items:
                return _record(
                    self.name,
                    status="upstream_error",
                    reason_code=str(meta["error"]),
                    docs=[],
                    live=False,
                    request_url=SEC_CURRENT_8K,
                    etag=meta.get("etag"),
                    last_modified=meta.get("last_modified"),
                )
            docs: list[EventDocument] = []
            seen: set[str] = set()
            for item in items:
                doc = self._to_doc(item)
                if doc is None or doc.url in seen:
                    continue
                seen.add(doc.url)
                docs.append(doc)
            # Documented per-company Atom for the four display names, so mapping is explicit.
            for cik in DISPLAY_CIKS:
                symbol = WATCHLIST_CIKS[cik]
                company_url = self._company_url(cik)
                company_items, company_meta = _fetch_items(
                    company_url,
                    name=f"{self.name}:{symbol}",
                    user_agent=self.user_agent(),
                    extra_headers={"Host": "www.sec.gov"},
                    limiter=_SEC_LIMITER,
                    allow_304=False,
                )
                if company_meta.get("error"):
                    continue
                for item in company_items:
                    doc = self._to_doc(item, mapped_symbol=symbol, expected_cik=cik)
                    if doc is None or doc.url in seen:
                        continue
                    seen.add(doc.url)
                    docs.append(doc)
            return _record(
                self.name,
                status="ok",
                reason_code=None,
                docs=docs,
                live=True,
                request_url=SEC_CURRENT_8K,
                etag=meta.get("etag"),
                last_modified=meta.get("last_modified"),
                note="Current 8-K Atom plus watchlist company Atom. Unknown CIKs stay on the market center.",
            )
        except Exception as exc:
            return _record(
                self.name,
                status="upstream_error",
                reason_code=type(exc).__name__,
                docs=[],
                live=False,
                request_url=SEC_CURRENT_8K,
            )


class FederalReserveProvider:
    name = "federal_reserve"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def status(self) -> dict[str, Any]:
        return _provider_status(
            self.name,
            role="official_fact",
            default_url=FED_PRESS_ALL,
            disabled_note="Live Federal Reserve fetch disabled in this process.",
        )

    def _classify(self, title: str, url: str) -> tuple[str, list[str]]:
        lowered = title.lower()
        slug = _slug(url)
        if any(marker in lowered for marker in MONETARY_MARKERS):
            return "central_bank_rates", ["FOMC", "US", slug]
        if any(marker in lowered for marker in BANK_MARKERS):
            return "sovereign_or_corporate_debt", ["banks", "credit", slug]
        return "other", ["FederalReserve", slug]

    def discover(self) -> list[EventDocument]:
        if not live_ingest_enabled(self.settings):
            return _record(
                self.name,
                status="idle",
                reason_code="live_fetch_disabled",
                docs=[],
                live=False,
                request_url=FED_PRESS_ALL,
            )
        try:
            docs: list[EventDocument] = []
            seen: set[str] = set()
            last_meta: dict[str, Any] = {}
            errors: list[str] = []
            for url in (FED_PRESS_MONETARY, FED_PRESS_ALL):
                items, meta = _fetch_items(
                    url,
                    name=f"{self.name}:{url.rsplit('/', 1)[-1]}",
                    user_agent="stock-pm official-feed/5b",
                    limiter=_DEFAULT_LIMITER,
                )
                last_meta = meta
                if meta.get("not_modified"):
                    cached = list((_STATE.get(self.name) or {}).get("docs") or [])
                    if cached:
                        return _record(
                            self.name,
                            status="ok",
                            reason_code=None,
                            docs=cached,
                            live=True,
                            request_url=FED_PRESS_ALL,
                            etag=meta.get("etag"),
                            last_modified=meta.get("last_modified"),
                            note="304 Not Modified; reused previous Fed documents.",
                        )
                if meta.get("error"):
                    errors.append(str(meta["error"]))
                    continue
                for item in items:
                    link = str(item.get("url") or "")
                    if not is_safe_public_http_url(link) or "federalreserve.gov" not in link.lower():
                        continue
                    if link in seen:
                        continue
                    seen.add(link)
                    title = strip_markup(str(item.get("title") or ""))
                    event_type, entities = self._classify(title, link)
                    docs.append(
                        EventDocument(
                            title=title,
                            url=link,
                            publisher="Federal Reserve Board",
                            published_at=item.get("published_at"),
                            event_type=event_type,
                            entities=entities,
                            countries=["US"],
                            claims=[title],
                            body=strip_markup(str(item.get("summary") or "")),
                            provider="official",
                            status=_status_from_title(title),
                        )
                    )
            if not docs and errors:
                return _record(
                    self.name,
                    status="upstream_error",
                    reason_code=errors[0],
                    docs=[],
                    live=False,
                    request_url=FED_PRESS_ALL,
                    etag=last_meta.get("etag"),
                    last_modified=last_meta.get("last_modified"),
                )
            return _record(
                self.name,
                status="ok",
                reason_code=None,
                docs=docs,
                live=True,
                request_url=FED_PRESS_ALL,
                etag=last_meta.get("etag"),
                last_modified=last_meta.get("last_modified"),
                note="Documented Fed press_all.xml and press_monetary.xml.",
            )
        except Exception as exc:
            return _record(
                self.name,
                status="upstream_error",
                reason_code=type(exc).__name__,
                docs=[],
                live=False,
                request_url=FED_PRESS_ALL,
            )


class EiaPressProvider:
    name = "eia_press"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def status(self) -> dict[str, Any]:
        return _provider_status(
            self.name,
            role="official_fact",
            default_url=EIA_PRESS,
            disabled_note="Live EIA fetch disabled in this process.",
        )

    def _classify(self, title: str, slug: str) -> tuple[str, list[str]]:
        lowered = title.lower()
        if any(marker in lowered for marker in OIL_MARKERS):
            return "energy_supply", ["EIA", "oil", "energy", slug]
        return "other", ["EIA", slug]

    def discover(self) -> list[EventDocument]:
        if not live_ingest_enabled(self.settings):
            return _record(
                self.name,
                status="idle",
                reason_code="live_fetch_disabled",
                docs=[],
                live=False,
                request_url=EIA_PRESS,
            )
        try:
            items, meta = _fetch_items(
                EIA_PRESS,
                name=self.name,
                user_agent="stock-pm official-feed/5b",
                limiter=_DEFAULT_LIMITER,
            )
            if meta.get("not_modified"):
                cached = list((_STATE.get(self.name) or {}).get("docs") or [])
                return _record(
                    self.name,
                    status="ok",
                    reason_code=None,
                    docs=cached,
                    live=True,
                    request_url=EIA_PRESS,
                    etag=meta.get("etag"),
                    last_modified=meta.get("last_modified"),
                    note="304 Not Modified; reused previous EIA documents.",
                )
            if meta.get("error"):
                return _record(
                    self.name,
                    status="upstream_error",
                    reason_code=str(meta["error"]),
                    docs=[],
                    live=False,
                    request_url=EIA_PRESS,
                    etag=meta.get("etag"),
                    last_modified=meta.get("last_modified"),
                )
            docs: list[EventDocument] = []
            for item in items:
                link = str(item.get("url") or "")
                if link.startswith("/"):
                    link = "https://www.eia.gov" + link
                if link.startswith("http://www.eia.gov"):
                    link = "https://" + link[len("http://") :]
                if not is_safe_public_http_url(link) or "eia.gov" not in link.lower():
                    continue
                title = strip_markup(str(item.get("title") or ""))
                slug = _slug(link)
                event_type, entities = self._classify(title, slug)
                docs.append(
                    EventDocument(
                        title=title,
                        url=link,
                        publisher="U.S. Energy Information Administration",
                        published_at=item.get("published_at"),
                        event_type=event_type,
                        entities=entities,
                        countries=["US"],
                        claims=[title],
                        body=strip_markup(str(item.get("summary") or "")),
                        provider="official",
                        status=_status_from_title(title),
                    )
                )
            return _record(
                self.name,
                status="ok",
                reason_code=None,
                docs=docs,
                live=True,
                request_url=EIA_PRESS,
                etag=meta.get("etag"),
                last_modified=meta.get("last_modified"),
                note=f"Documented on {EIA_INDEX}. BLS RSS is not used (HTTP 403 from this environment).",
            )
        except Exception as exc:
            return _record(
                self.name,
                status="upstream_error",
                reason_code=type(exc).__name__,
                docs=[],
                live=False,
                request_url=EIA_PRESS,
            )


LIVE_PROVIDERS = (SecEdgarProvider, FederalReserveProvider, EiaPressProvider)


def live_provider_instances(settings: Settings | None = None) -> list[Any]:
    return [cls(settings) for cls in LIVE_PROVIDERS]


def discover_live_documents(settings: Settings | None = None) -> list[EventDocument]:
    """Each provider is isolated. One failure does not stop the others."""
    rows: list[EventDocument] = []
    for provider in live_provider_instances(settings):
        try:
            rows.extend(provider.discover())
        except Exception as exc:
            _record(
                provider.name,
                status="upstream_error",
                reason_code=type(exc).__name__,
                docs=[],
                live=False,
                request_url=getattr(provider, "name", ""),
            )
    return rows


def live_provider_coverage(settings: Settings | None = None) -> dict[str, Any]:
    return {provider.name: provider.status() for provider in live_provider_instances(settings)}
