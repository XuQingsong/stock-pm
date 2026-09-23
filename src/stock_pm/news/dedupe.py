"""Article-level dedupe: the same item seen twice, or syndicated verbatim.

This is not story clustering. Different articles about one event stay
separate here and are grouped later by event keys / similarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .contract import SOURCE_KIND_RANK, RawArticle, normalize_title

PRECISION_RANK = {"second": 0, "minute": 1, "day": 2, None: 3}
# Short or boilerplate titles ("Form 8-K", "Press release") collide across unrelated items.
MIN_TITLE_CHARS = 24
TITLE_WINDOW = timedelta(hours=36)


@dataclass(slots=True)
class DedupeResult:
    unique: list[RawArticle] = field(default_factory=list)
    dropped: list[dict[str, str]] = field(default_factory=list)


def _keys(article: RawArticle) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if article.sec_accession:
        keys.append(("sec_accession", article.sec_accession))
    if article.external_id and article.external_id_kind != "url":
        keys.append(("external_id", f"{article.source}:{article.external_id}"))
    if article.canonical_url:
        keys.append(("canonical_url", article.canonical_url))
    return keys


def _preferred(left: RawArticle, right: RawArticle) -> RawArticle:
    def score(item: RawArticle) -> tuple:
        published = item.published_at
        return (
            SOURCE_KIND_RANK.get(item.source_kind, 9),
            0 if item.published.tz_explicit else 1,
            PRECISION_RANK.get(item.published.precision, 3),
            published.timestamp() if published else float("inf"),
            -len(item.body or item.summary or ""),
        )

    return left if score(left) <= score(right) else right


def _merge(kept: RawArticle, other: RawArticle) -> None:
    for ticker in other.vendor_tickers:
        if ticker not in kept.vendor_tickers:
            kept.vendor_tickers.append(ticker)
    for source in [other.source, *other.also_seen_in]:
        if source != kept.source and source not in kept.also_seen_in:
            kept.also_seen_in.append(source)
    if not kept.sec_items and other.sec_items:
        kept.sec_items = list(other.sec_items)


def _title_match(left: RawArticle, right: RawArticle) -> bool:
    if left.source_kind == "official" or right.source_kind == "official":
        return False
    title = normalize_title(left.title)
    if len(title) < MIN_TITLE_CHARS or title != normalize_title(right.title):
        return False
    if left.published_at is None or right.published_at is None:
        return False
    return abs(left.published_at - right.published_at) <= TITLE_WINDOW


def dedupe_articles(articles: list[RawArticle]) -> DedupeResult:
    result = DedupeResult()
    index: dict[tuple[str, str], int] = {}
    for article in articles:
        hit_key = next((key for key in _keys(article) if key in index), None)
        slot = index.get(hit_key) if hit_key else None
        reason = hit_key[0] if hit_key else None
        if slot is None:
            for position, existing in enumerate(result.unique):
                if _title_match(existing, article):
                    slot, reason = position, "title"
                    break
        if slot is None:
            result.unique.append(article)
            for key in _keys(article):
                index.setdefault(key, len(result.unique) - 1)
            continue
        existing = result.unique[slot]
        kept = _preferred(existing, article)
        loser = article if kept is existing else existing
        _merge(kept, loser)
        result.unique[slot] = kept
        for key in _keys(kept):
            index.setdefault(key, slot)
        result.dropped.append(
            {"reason": str(reason), "kept": kept.canonical_url, "dropped": loser.canonical_url, "dropped_source": loser.source}
        )
    return result
