"""Frozen 5C official-audit pack. Not live and never production latest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .bodies import excerpt_has_body_substance, is_sec_item_metadata
from .types import EventDocument


FROZEN_PACK_PATH = Path(__file__).resolve().parent.parent / "data" / "events_5c_frozen_sample.json"
FROZEN_LABEL = "FROZEN OFFICIAL AUDIT · not production live latest"
BEFORE_COUNTS = {
    "valid_conclusion_count": 31,
    "withheld_count": 92,
    "unsupported_count": 44,
}


class FrozenPackError(RuntimeError):
    """Tampered or malformed frozen official-audit pack."""


def frozen_pack_material(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": payload.get("audit_id"),
        "documents": payload.get("documents") or [],
        "official_extracts": payload.get("official_extracts") or {},
        "must_remain_withheld": payload.get("must_remain_withheld") or [],
        "gained_event_ids": payload.get("gained_event_ids") or [],
        "before": payload.get("before") or {},
        "after": payload.get("after") or {},
        "document_urls": payload.get("document_urls") or [],
        "event_ids": payload.get("event_ids") or [],
        "url_body_sha256": payload.get("url_body_sha256") or {},
    }


def compute_frozen_integrity(payload: dict[str, Any]) -> str:
    encoded = json.dumps(frozen_pack_material(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_frozen_pack(path: Path | None = None) -> dict[str, Any]:
    target = path or FROZEN_PACK_PATH
    if not target.is_file():
        raise FrozenPackError("frozen_pack_missing")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("live") is True:
        raise FrozenPackError("frozen_pack_marked_live")
    if payload.get("data_class") != "frozen_official_audit":
        raise FrozenPackError("frozen_pack_not_audit")
    expected = str(payload.get("integrity_sha256") or "")
    actual = compute_frozen_integrity(payload)
    if not expected or expected != actual:
        raise FrozenPackError("frozen_pack_hash_mismatch")
    return payload


def apply_official_extracts(docs: list[EventDocument], extracts: dict[str, Any]) -> list[EventDocument]:
    """Apply recorded official extracts. Item metadata cannot become a body."""
    upgraded: list[EventDocument] = []
    for doc in docs:
        extra = extracts.get(doc.url) or {}
        items = list(extra.get("filing_items") or getattr(doc, "filing_items", None) or [])
        body = str(extra.get("body") or "")
        source = str(extra.get("body_source") or "")
        claims = list(extra.get("claims") or doc.claims)
        if source == "sec_index_items" or is_sec_item_metadata(body):
            body = doc.body
            claims = list(doc.claims)
            source = doc.body_source or ""
        elif body and not excerpt_has_body_substance(body, (claims[0] if claims else doc.title) or doc.title):
            body = doc.body
            claims = list(doc.claims)
            source = doc.body_source or ""
        else:
            body = body or doc.body
            source = source or doc.body_source or ""
        upgraded.append(
            EventDocument(
                title=doc.title,
                url=doc.url,
                publisher=doc.publisher,
                published_at=doc.published_at,
                event_type=doc.event_type,
                entities=list(doc.entities),
                countries=list(doc.countries),
                claims=claims,
                body=body,
                provider=doc.provider,
                status=doc.status,
                document_role=doc.document_role,
                evidence_role=doc.evidence_role,
                supersedes_url=doc.supersedes_url,
                last_fetched_at=extra.get("fetched_at") or doc.last_fetched_at,
                body_source=source,
                fetch_error=extra.get("error") or doc.fetch_error,
                filing_items=items,
            )
        )
    return upgraded
