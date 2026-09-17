"""Turn full page text into Evidence facts. Search summaries are not facts."""

from __future__ import annotations

import re
from typing import Any

from stock_pm.research.llm_reason import compact_text, complete_structured, dump_user

from .quality import source_family, source_tier
from .queries import load_external_prompt


_SPLIT = re.compile(r"(?<=[.!?])\s+")
_SIGNAL = re.compile(
    r"(\$|%|\b20\d{2}\b|\b(capex|customer|supplier|demand|guidance|outlook|800g|1\.6t|"
    r"tpu|asic|hyperscaler|datacenter|optical|transceiver|iphone|services)\b)",
    re.I,
)


def _sentences(text: str) -> list[str]:
    parts = _SPLIT.split(" ".join(str(text or "").split()))
    return [part.strip() for part in parts if 40 <= len(part.strip()) <= 400]


def deterministic_facts(doc: dict[str, Any], *, limit: int = 2) -> list[dict[str, Any]]:
    if not doc.get("is_full_text"):
        return []
    text = str(doc.get("clean_text") or "")
    out: list[dict[str, Any]] = []
    for sentence in _sentences(text):
        if not _SIGNAL.search(sentence):
            continue
        out.append(
            {
                "fact": sentence,
                "excerpt": sentence,
                "document_id": doc.get("document_id"),
                "source": source_family(doc.get("url")),
                "source_url": doc.get("url"),
                "source_time": doc.get("published_at"),
                "source_tier": source_tier(doc.get("url")),
                "source_type": "sec_filing" if source_tier(doc.get("url")) == 1 else "web_search",
                "extraction": "deterministic",
            }
        )
        if len(out) >= limit:
            break
    return out


def llm_extract_facts(
    completer: Any,
    docs: list[dict[str, Any]],
    *,
    ticker: str,
    claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    usable = [row for row in docs if row.get("is_full_text") and str(row.get("clean_text") or "").strip()][:8]
    if not usable or completer is None:
        return [], {"step": "external_fact_extract", "llm_called": False, "llm_status": "skipped"}
    user = {
        "ticker": ticker,
        "claims": [{"title": compact_text(row.get("title"), 80), "statement": compact_text(row.get("statement"), 160)} for row in claims[:5]],
        "documents": [
            {
                "document_id": row.get("document_id"),
                "title": row.get("title"),
                "url": row.get("url"),
                "published_at": row.get("published_at"),
                "source_domain": row.get("source_domain"),
                "text": compact_text(row.get("clean_text"), 1200),
            }
            for row in usable
        ],
        "rules": [
            "Use only the document text.",
            "Do not copy search-engine summaries.",
            "Each fact needs an excerpt that appears in the text.",
            "If nothing dated and specific, return an empty facts list.",
        ],
    }
    payload, audit = complete_structured(
        completer,
        system=load_external_prompt("external_fact_extract.txt"),
        user=dump_user(user),
    )
    audit = dict(audit or {})
    audit["step"] = "external_fact_extract"
    if not payload:
        return [], audit
    by_id = {str(row.get("document_id")): row for row in usable}
    facts: list[dict[str, Any]] = []
    for item in payload.get("facts") or []:
        if not isinstance(item, dict):
            continue
        doc = by_id.get(str(item.get("document_id") or ""))
        if not doc:
            continue
        fact = compact_text(item.get("fact"), 400)
        excerpt = compact_text(item.get("excerpt") or fact, 400)
        body = str(doc.get("clean_text") or "")
        if not fact or not excerpt:
            continue
        if excerpt.lower()[:40] not in body.lower() and fact.lower()[:40] not in body.lower():
            continue
        facts.append(
            {
                "fact": fact,
                "excerpt": excerpt,
                "document_id": doc.get("document_id"),
                "source": source_family(doc.get("url")),
                "source_url": doc.get("url"),
                "source_time": doc.get("published_at"),
                "source_tier": source_tier(doc.get("url")),
                "source_type": "sec_filing" if source_tier(doc.get("url")) == 1 else "web_search",
                "claim_title": compact_text(item.get("claim_title"), 80) or None,
                "extraction": "llm",
            }
        )
    return facts[:16], audit


def facts_to_evidence_bodies(ticker: str, facts: list[dict[str, Any]], *, retrieved_at: str) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in facts:
        fact = compact_text(item.get("fact"), 800)
        if not fact or fact.lower() in seen:
            continue
        if not item.get("source_url") or not item.get("source_time"):
            continue
        seen.add(fact.lower())
        tier = int(item.get("source_tier") or 5)
        if tier <= 1:
            quality = "primary"
        elif tier == 2:
            quality = "high_quality_secondary"
        else:
            quality = "secondary"
        bodies.append(
            {
                "ticker": ticker.upper(),
                "evidence_type": "news" if tier >= 2 else "filing",
                "fact": fact,
                "excerpt": compact_text(item.get("excerpt") or fact, 600),
                "source": item.get("source") or "web_search",
                "source_url": item.get("source_url"),
                "source_time": item.get("source_time"),
                "retrieved_at": retrieved_at,
                "source_type": item.get("source_type") or "web_search",
                "source_quality": quality,
                "importance": "high" if tier <= 2 else "medium",
                "raw_reference": {
                    "document_id": item.get("document_id"),
                    "source_tier": tier,
                    "source_family": item.get("source"),
                    "extraction": item.get("extraction"),
                    "claim_title": item.get("claim_title"),
                },
            }
        )
    return bodies
