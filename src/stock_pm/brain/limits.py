"""Token/output discipline for Brain structured text."""

from __future__ import annotations

from typing import Any


def limit_words(value: Any, n: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    words = text.split(" ")
    if len(words) <= n:
        return text
    return " ".join(words[:n])
