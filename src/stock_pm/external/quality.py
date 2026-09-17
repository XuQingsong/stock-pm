"""Publisher quality is taken from the original URL, not the discovery provider."""

from __future__ import annotations

from urllib.parse import urlsplit

from stock_pm.events.policy import TIER1_HOSTS, normalize_url


TIER2_HOSTS = (
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "apnews.com",
    "associatedpress.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
)
TIER3_HOSTS = (
    "nasdaq.com",
    "marketwatch.com",
    "spglobal.com",
    "nikkei.com",
    "theinformation.com",
    "protocol.com",
    "lightreading.com",
    "semiengineering.com",
    "digitimes.com",
    "tomshardware.com",
    "anandtech.com",
    "theregister.com",
    "arstechnica.com",
    "barrons.com",
)
TIER4_HOSTS = (
    "fool.com",
    "zacks.com",
    "seekingalpha.com",
    "yahoo.com",
    "finance.yahoo.com",
    "msn.com",
    "benzinga.com",
    "investopedia.com",
    "tipranks.com",
    "motleyfool.com",
    "stocktitan.net",
    "marketscreener.com",
    "simplywall.st",
)
TIER5_HOSTS = (
    "reddit.com",
    "twitter.com",
    "x.com",
    "stocktwits.com",
    "youtube.com",
    "medium.com",
    "substack.com",
    "linkedin.com",
    "facebook.com",
    "blogspot.com",
    "wordpress.com",
    "github.io",
    "ghost.io",
    "notion.site",
    "typepad.com",
    "tumblr.com",
)
OFFICIAL_PATH_MARKERS = (
    "/investor",
    "/investors",
    "/newsroom",
    "/press-release",
    "/press-releases",
    "/shareholder",
    "/ir/",
)
DISCOVERY_HOSTS = (
    "tavily.com",
    "exa.ai",
    "duckduckgo.com",
    "googleapis.com",
)


def host_of(url: str | None) -> str:
    host = (urlsplit(str(url or "")).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _endswith_any(host: str, names: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith("." + item) for item in names)


def _official_host(host: str) -> bool:
    return (
        _endswith_any(host, TIER1_HOSTS)
        or host.endswith(".gov")
        or host.endswith(".mil")
        or host.startswith("ir.")
        or host.startswith("investors.")
        or "investor." in host
        or host.endswith(".sec.gov")
        or "sec.gov" in host
    )


def source_tier(url: str | None, *, source: str | None = None) -> int:
    host = host_of(url)
    path = (urlsplit(str(url or "")).path or "").lower()
    blob = f"{host} {source or ''} {path}".lower()
    if _official_host(host) or "sec.gov" in blob:
        return 1
    if _endswith_any(host, TIER2_HOSTS):
        return 2
    if _endswith_any(host, TIER3_HOSTS):
        return 3
    if _endswith_any(host, TIER5_HOSTS) or not host:
        return 5
    if any(marker in path for marker in OFFICIAL_PATH_MARKERS) and not _endswith_any(host, TIER4_HOSTS):
        return 1
    if _endswith_any(host, TIER4_HOSTS):
        return 4
    return 4


def source_type_for(url: str | None, *, query_type: str | None = None) -> str:
    host = host_of(url)
    tier = source_tier(url)
    if query_type == "macro" or _endswith_any(host, ("stlouisfed.org", "bls.gov", "bea.gov", "federalreserve.gov")):
        return "macro"
    if tier == 1:
        return "official"
    if query_type in {"industry_news", "related_entity", "customer", "supplier"} and tier >= 3:
        return "industry"
    if tier == 2:
        return "independent_news"
    if query_type == "industry_news":
        return "industry"
    return "aggregator"


def source_family(url: str | None, source: str | None = None) -> str:
    host = host_of(url)
    if not host:
        return "unknown"
    if _endswith_any(host, DISCOVERY_HOSTS):
        return "web_search"
    if "sec.gov" in host:
        return "sec"
    if host.startswith("ir.") or "investor" in host:
        return "issuer_ir"
    if _endswith_any(host, TIER2_HOSTS):
        return "high_quality_news"
    if _endswith_any(host, TIER1_HOSTS):
        return "official"
    return host


def is_high_quality(url: str | None, source: str | None = None) -> bool:
    return source_tier(url, source=source) <= 2


def canonical_url(url: str | None) -> str:
    return normalize_url(str(url or "").strip())
