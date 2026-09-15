"""Normalize proposed Evidence. Persistence still goes through ResearchService."""

from __future__ import annotations

from typing import Any


def evidence_fingerprint(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("fact") or "").strip().lower(),
        str(item.get("source") or "").strip().lower(),
        str(item.get("source_time") or "").strip(),
    )
