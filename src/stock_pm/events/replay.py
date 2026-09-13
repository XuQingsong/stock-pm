"""Recorded official originals for repeatable pipeline replay. Not live prints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .policy import is_safe_public_http_url, sanitize_untrusted
from .types import EventDocument


RECORDED_PACK_PATH = Path(__file__).resolve().parent.parent / "data" / "events_recorded_5b.json"
REPLAY_LABEL = "RECORDED REPLAY · real official originals · not production live"


class RecordedPackError(RuntimeError):
    """Tampered or malformed recorded pack."""


def compute_pack_hash(payload: dict[str, Any]) -> str:
    material = {
        "pack_id": payload.get("pack_id"),
        "documents": payload.get("documents") or [],
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_recorded_pack(path: Path | None = None) -> dict[str, Any]:
    target = path or RECORDED_PACK_PATH
    if not target.is_file():
        raise RecordedPackError("recorded_pack_missing")
    payload = json.loads(target.read_text(encoding="utf-8"))
    expected = str(payload.get("integrity_sha256") or "")
    actual = compute_pack_hash(payload)
    if not expected or expected != actual:
        raise RecordedPackError("recorded_pack_hash_mismatch")
    if payload.get("live") is True:
        raise RecordedPackError("recorded_pack_marked_live")
    return payload


def recorded_documents(path: Path | None = None) -> list[EventDocument]:
    payload = load_recorded_pack(path)
    rows: list[EventDocument] = []
    for item in payload.get("documents") or []:
        url = str(item.get("source_url") or "")
        if not is_safe_public_http_url(url):
            raise RecordedPackError("recorded_pack_unsafe_url")
        if int(item.get("http_status") or 0) != 200:
            raise RecordedPackError("recorded_pack_http_not_ok")
        rows.append(
            EventDocument(
                title=str(item.get("title") or ""),
                url=url,
                publisher=str(item.get("publisher") or ""),
                published_at=item.get("published_at") or item.get("event_time"),
                event_type=str(item.get("event_type") or "other"),
                entities=list(item.get("entities") or []),
                countries=list(item.get("countries") or []),
                claims=[sanitize_untrusted(str(claim)) for claim in (item.get("claims") or [])],
                body=sanitize_untrusted(str(item.get("excerpt") or "")),
                provider=str(item.get("provider") or "official"),
                status=str(item.get("status") or "active"),
            )
        )
    return rows


class RecordedReplayProvider:
    name = "recorded_replay"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or RECORDED_PACK_PATH
        self.last_error: str | None = None
        self.last_count = 0
        self.integrity_sha256: str | None = None

    def discover(self) -> list[EventDocument]:
        self.last_error = None
        try:
            payload = load_recorded_pack(self.path)
            docs = recorded_documents(self.path)
        except RecordedPackError as exc:
            self.last_error = str(exc)
            self.last_count = 0
            raise
        self.integrity_sha256 = str(payload.get("integrity_sha256") or "")
        self.last_count = len(docs)
        return docs

    def status(self) -> dict[str, Any]:
        if self.last_error:
            return {
                "provider": self.name,
                "status": "tamper_detected",
                "live": False,
                "reason_code": self.last_error,
                "role": "recorded_replay",
                "request_url": None,
                "last_success_at": None,
                "event_count": 0,
                "note": REPLAY_LABEL,
            }
        try:
            payload = load_recorded_pack(self.path)
        except RecordedPackError as exc:
            return {
                "provider": self.name,
                "status": "tamper_detected",
                "live": False,
                "reason_code": str(exc),
                "role": "recorded_replay",
                "request_url": None,
                "last_success_at": None,
                "event_count": 0,
                "note": REPLAY_LABEL,
            }
        return {
            "provider": self.name,
            "status": "recorded_replay",
            "live": False,
            "reason_code": "recorded_replay_not_live",
            "role": "recorded_replay",
            "request_url": None,
            "last_success_at": payload.get("recorded_at"),
            "event_count": len(payload.get("documents") or []),
            "integrity_sha256": payload.get("integrity_sha256"),
            "note": REPLAY_LABEL,
        }
