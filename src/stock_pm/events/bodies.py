"""Official HTML body helpers. Titles, H1, nav, and SEC Item lines are not excerpts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from .evidence import STOP, drop_chrome_lines, excerpt_supports_claim, normalize_evidence_text, select_claim_support_excerpt
from .feeds import FeedResponse, fetch_feed, strip_markup
from .policy import host_of, is_https_registrable_host, sanitize_untrusted

ITEM_LINE_RE = re.compile(r"^Item\s+(\d+\.\d+)\s*[:\-]?\s*(.+)$", re.I)
ITEM_HEADING_RE = re.compile(
    r"Item\s+\d+\.\d+\s*[:\-]?\s*[A-Za-z][A-Za-z0-9 ,/;()'\"&-]{3,200}",
    re.I,
)
ITEM_SPLIT_RE = re.compile(r"(?=Item\s+\d+\.\d+)", re.I)
FILING_CHROME_RE = re.compile(
    r"(?i)(?:Filed|AccNo|Accession(?:-number)?|Size)\s*:[^\n]*|"
    r"\b(?:8-K|Form|Current report|KB|Filer)\b"
)
NAV_NOISE = (
    "skip to",
    "an official website",
    "edgar filing documents",
    "complete submission text file",
    "form 8-k - current report",
    "page form 8-k",
    "sec accession no",
    "u.s. energy information administration washington",
    "for immediate release",
)
SEC_BOILERPLATE = (
    "hereby furnished",
    "incorporated by reference",
    "furnished pursuant",
    "shall not be deemed",
    "issued a press release",
    "attached as exhibit",
    "exhibit 99",
    "securities exchange act",
    "securities and exchange commission",
    "current report pursuant",
    "pursuant to section 13",
    "check the appropriate box",
    "commission file number",
    "irs employer",
    "registrant's telephone",
    "written communications",
    "soliciting material",
)
EXHIBIT_MARKERS = ("ex99", "ex-99", "ex_99", "a8-kex", "exhibit")
STALE_ERRORS = frozenset({"timeout", "http_429", "http_500", "http_502", "http_503", "http_504"})
STALE_CODES = frozenset({429, 500, 502, 503, 504})
_CACHE: dict[str, dict[str, Any]] = {}


def reset_body_cache() -> None:
    _CACHE.clear()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _claim_tokens(claim: str) -> list[str]:
    words = re.findall(r"[a-z0-9\u4e00-\u9fff]{4,}", (claim or "").lower())
    return [word for word in words if word not in STOP]


def is_chrome_text(text: str) -> bool:
    hay = normalize_evidence_text(text).lower()
    if not hay:
        return True
    return any(marker in hay for marker in NAV_NOISE) and "item " not in hay


def is_sec_item_metadata(text: str) -> bool:
    """True when text is only EDGAR Item category labels / filing chrome."""
    hay = normalize_evidence_text(text or "")
    if not re.search(r"Item\s+\d+\.\d+", hay, re.I):
        return False
    leftovers: list[str] = []
    for part in ITEM_SPLIT_RE.split(hay):
        part = normalize_evidence_text(part)
        if not part:
            continue
        if ITEM_LINE_RE.match(part):
            continue
        stripped = ITEM_HEADING_RE.sub(" ", part, count=1)
        stripped = FILING_CHROME_RE.sub(" ", stripped)
        stripped = normalize_evidence_text(stripped)
        if stripped:
            leftovers.append(stripped)
    return len(normalize_evidence_text(" ".join(leftovers))) < 24


def excerpt_is_claim_echo(excerpt: str, claim: str) -> bool:
    left = normalize_evidence_text(excerpt).lower()
    right = normalize_evidence_text(claim).lower()
    if not left or not right:
        return True
    if left == right:
        return True
    if left in right or right in left:
        extra = set(_claim_tokens(excerpt)) - set(_claim_tokens(claim))
        return len(extra) < 2 and not re.search(r"\d", excerpt or "")
    return False


def excerpt_has_body_substance(excerpt: str, claim: str) -> bool:
    """Body must add facts beyond repeating the title/claim."""
    if is_sec_item_metadata(excerpt) or is_chrome_text(excerpt):
        return False
    if excerpt_is_claim_echo(excerpt, claim):
        return False
    extra = set(_claim_tokens(excerpt)) - set(_claim_tokens(claim))
    has_number = bool(re.search(r"\d", excerpt or ""))
    return bool(extra) or (has_number and len(normalize_evidence_text(excerpt)) > len(normalize_evidence_text(claim)))


def is_allowed_eia_host(url: str) -> bool:
    """https only; hostname is eia.gov or a subdomain of eia.gov."""
    return is_https_registrable_host(url, "eia.gov")


def is_allowed_sec_host(url: str) -> bool:
    """https only; hostname is sec.gov or a subdomain of sec.gov."""
    return is_https_registrable_host(url, "sec.gov")


def extract_sec_index_items(html: str) -> list[str]:
    """Per-node/per-line Item labels. Concatenated raw+text blobs are rejected."""
    raw = str(html or "")
    lines: list[str] = []
    for match in re.finditer(r"(?is)<(?:t[dh]|li|div|p)[^>]*>(.*?)</(?:t[dh]|li|div|p)>", raw):
        lines.extend(strip_markup(match.group(1), max_len=None).splitlines())
    text = strip_markup(raw, max_len=None)
    lines.extend(text.splitlines())
    for part in ITEM_SPLIT_RE.split(text):
        lines.append(part)
    seen: dict[str, str] = {}
    out: list[str] = []
    for line in lines:
        line = normalize_evidence_text(line)
        match = ITEM_LINE_RE.match(line)
        if not match:
            continue
        desc = normalize_evidence_text(match.group(2))
        if re.search(r"Item\s+\d+\.\d+", desc, re.I):
            continue
        desc = re.split(r"\s+Item\s+\d+\.\d+", desc, maxsplit=1, flags=re.I)[0].strip()
        if len(desc) < 8 or is_chrome_text(desc):
            continue
        item = sanitize_untrusted(f"Item {match.group(1)}: {desc}", max_len=240)
        key = item.lower()
        if key in seen:
            continue
        seen[key] = item
        out.append(item)
    return out[:8]


def extract_sec_primary_document_url(index_html: str, index_url: str) -> str:
    """Follow the inline XBRL / primary 8-K. Exhibits and complete .txt are skipped."""
    ix = re.search(
        r"""href=["']([^"']*?/ix\?doc=/Archives/edgar/data/\d+/\d+/[^"']+\.htm)["']""",
        index_html or "",
        flags=re.I,
    )
    def _abs(href: str) -> str:
        target = urljoin(index_url or "https://www.sec.gov", href)
        return target if is_allowed_sec_host(target) else ""

    if ix:
        return _abs(ix.group(1))
    candidates: list[str] = []
    for href in re.findall(r"""href=["']([^"']+)["']""", index_html or "", flags=re.I):
        low = href.lower()
        if not low.endswith((".htm", ".html")):
            continue
        if "index" in low or "/ix?" in low:
            continue
        if any(marker in low for marker in EXHIBIT_MARKERS):
            continue
        if "/archives/edgar/data/" not in low:
            continue
        if not _abs(href):
            continue
        candidates.append(href)
    if not candidates:
        return ""
    for href in candidates:
        if re.search(r"8-?k", href, re.I):
            return _abs(href)
    return _abs(candidates[0])


def _is_sec_boilerplate(text: str) -> bool:
    hay = (text or "").lower()
    return any(marker in hay for marker in SEC_BOILERPLATE)


def extract_sec_primary_facts(html: str) -> list[str]:
    """Concrete 8-K body facts. Item headings and exhibit/boilerplate sentences are dropped."""
    body = extract_official_body_text(html)
    if not body:
        return []
    facts: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", body):
        part = normalize_evidence_text(part)
        if len(part) < 40:
            continue
        if is_sec_item_metadata(part) or _is_sec_boilerplate(part) or is_chrome_text(part):
            continue
        if not re.search(r"\d", part):
            continue
        if len(_claim_tokens(part)) < 4:
            continue
        facts.append(sanitize_untrusted(part, max_len=480))
        if len(facts) >= 3:
            break
    return facts


def _strip_chrome_html(html: str) -> str:
    text = str(html or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<title[^>]*>.*?</title>", " ", text)
    text = re.sub(r"(?is)<nav[^>]*>.*?</nav>", " ", text)
    text = re.sub(r"(?is)<header[^>]*>.*?</header>", " ", text)
    text = re.sub(r"(?is)<footer[^>]*>.*?</footer>", " ", text)
    text = re.sub(r"(?is)<aside[^>]*>.*?</aside>", " ", text)
    text = re.sub(r"(?is)<h1[^>]*>.*?</h1>", " ", text)
    text = re.sub(
        r"(?is)<[^>]+(?:class|id)=['\"][^'\"]*(?:breadcrumb|breadcrumbs|utility-nav|site-nav|masthead)[^'\"]*['\"][^>]*>.*?</[a-z0-9]+>",
        " ",
        text,
    )
    return text


def extract_official_body_text(html: str) -> str:
    """Keep main/article/press body or remaining paragraphs after chrome removal."""
    chrome_free = _strip_chrome_html(html)
    preferred: list[str] = []
    for match in re.finditer(r"(?is)<(main|article)(?:\s[^>]*)?>(.*?)</\1>", chrome_free):
        preferred.append(match.group(2))
    for match in re.finditer(
        r"(?is)<[^>]+(?:class|id)=['\"][^'\"]*(?:press-release|article-body|entry-content|main-content)[^'\"]*['\"][^>]*>(.*?)</[a-z0-9]+>",
        chrome_free,
    ):
        preferred.append(match.group(1))
    joined = " ".join(preferred)
    source = joined if preferred and len(strip_markup(joined, max_len=None)) >= 40 else chrome_free
    paras = [normalize_evidence_text(strip_markup(part, max_len=None)) for part in re.findall(r"(?is)<p[^>]*>(.*?)</p>", source)]
    paras = [part for part in paras if part]
    text = "\n".join(paras) if paras else strip_markup(source, max_len=None)
    return drop_chrome_lines(text)


def _supporting_body_excerpt(cleaned: str, claim: str) -> str | None:
    if not excerpt_supports_claim(claim, cleaned) or is_chrome_text(cleaned):
        return None
    paras = [normalize_evidence_text(part) for part in re.split(r"\n+", cleaned) if part.strip()]
    best: str | None = None
    for para in paras:
        if (
            excerpt_supports_claim(claim, para)
            and excerpt_has_body_substance(para, claim)
            and not is_chrome_text(para)
            and not is_sec_item_metadata(para)
        ):
            if best is None or len(para) < len(best):
                best = para
    if best:
        return sanitize_untrusted(best, max_len=480)
    acc = ""
    for para in paras:
        if is_chrome_text(para) or is_sec_item_metadata(para):
            continue
        acc = f"{acc} {para}".strip()
        if excerpt_supports_claim(claim, acc) and excerpt_has_body_substance(acc, claim):
            return sanitize_untrusted(acc, max_len=480)
    if excerpt_supports_claim(claim, cleaned) and excerpt_has_body_substance(cleaned, claim):
        return sanitize_untrusted(cleaned, max_len=480)
    return None


def official_html_excerpt(html: str, claim: str) -> str | None:
    """Smallest official-body window that supports the claim. Title/H1/nav cannot substitute."""
    cleaned = normalize_evidence_text(extract_official_body_text(html))
    if not cleaned or is_chrome_text(cleaned) or is_sec_item_metadata(cleaned):
        return None
    if excerpt_is_claim_echo(cleaned, claim):
        return None
    excerpt = _supporting_body_excerpt(cleaned, claim)
    if excerpt:
        return excerpt
    tokens = _claim_tokens(claim)
    present = [token for token in tokens if token in cleaned.lower()]
    if len(present) >= 2:
        try:
            window = select_claim_support_excerpt(cleaned, present[:3])
            candidate = sanitize_untrusted(str(window.get("claim_support_excerpt") or ""), max_len=480)
            if (
                candidate
                and excerpt_supports_claim(claim, candidate)
                and excerpt_has_body_substance(candidate, claim)
                and not is_chrome_text(candidate)
                and not is_sec_item_metadata(candidate)
            ):
                return candidate
        except ValueError:
            pass
    return None


def _stale_from_cache(url: str, error: str, attempted_at: str) -> dict[str, Any] | None:
    cached = _CACHE.get(url)
    if not cached or not cached.get("html") or cached.get("error"):
        return None
    row = dict(cached)
    row.update(
        {
            "stale": True,
            "status": "stale_cache",
            "error": None,
            "fetch_error": error,
            "attempted_at": attempted_at,
            "fetched_at": cached.get("fetched_at"),
        }
    )
    return row


def fetch_official_page(
    url: str,
    *,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    limiter=None,
    allow_cache: bool = True,
    fetch=None,
) -> dict[str, Any]:
    fetched_at = _now()
    cached = _CACHE.get(url) if allow_cache else None
    etag = (cached or {}).get("etag")
    last_modified = (cached or {}).get("last_modified")
    do_fetch = fetch or fetch_feed
    try:
        resp: FeedResponse = do_fetch(
            url,
            user_agent=user_agent,
            extra_headers=extra_headers,
            etag=etag,
            last_modified=last_modified,
            timeout=35,
            limiter=limiter,
            retries=2,
        )
    except TimeoutError:
        stale = _stale_from_cache(url, "timeout", fetched_at) if allow_cache else None
        if stale:
            return stale
        return {
            "url": url,
            "html": "",
            "error": "timeout",
            "stale": False,
            "status": "error",
            "http_status": 0,
            "fetched_at": fetched_at,
            "etag": None,
            "last_modified": None,
            "not_modified": False,
        }
    if resp.not_modified and cached and cached.get("html"):
        cached = dict(cached)
        cached["fetched_at"] = fetched_at
        cached["not_modified"] = True
        cached["stale"] = False
        cached["status"] = "ok"
        _CACHE[url] = cached
        return cached
    error = resp.error or (None if resp.ok else f"http_{resp.status_code}")
    if error or not resp.ok:
        stale_eligible = error in STALE_ERRORS or resp.status_code in STALE_CODES
        if allow_cache and stale_eligible:
            stale = _stale_from_cache(url, error or f"http_{resp.status_code}", fetched_at)
            if stale:
                return stale
        return {
            "url": url,
            "html": "",
            "error": error or f"http_{resp.status_code}",
            "stale": False,
            "status": "error",
            "http_status": resp.status_code,
            "fetched_at": fetched_at,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
            "not_modified": False,
        }
    html = (resp.body or b"").decode("utf-8", "replace")
    row = {
        "url": url,
        "html": html,
        "error": None,
        "stale": False,
        "status": "ok",
        "http_status": resp.status_code,
        "fetched_at": fetched_at,
        "etag": resp.etag,
        "last_modified": resp.last_modified,
        "not_modified": False,
        "final_url": resp.url or url,
    }
    # Exact request URL only — never alias a cache entry onto another host.
    _CACHE[url] = dict(row)
    if resp.url and resp.url != url and host_of(resp.url) == host_of(url):
        _CACHE[resp.url] = dict(row)
    return row


def resolve_redirect_url(base: str, html: str) -> str | None:
    match = re.search(
        r"""<meta[^>]+http-equiv=["']refresh["'][^>]+content=["'][^"']*url=([^"']+)""",
        html or "",
        flags=re.I,
    )
    if not match:
        return None
    target = match.group(1).strip()
    if not target:
        return None
    return urljoin(base, target)
