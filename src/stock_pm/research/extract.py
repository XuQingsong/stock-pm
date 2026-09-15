"""Generic extractors for growth, guidance, and management commitments.

Patterns are about document language, never a specific issuer.
"""

from __future__ import annotations

import re
from typing import Any


COMMITMENT_PATTERNS = (
    re.compile(
        r"(long[- ]term|multi-year|by\s+FY?\s*20\d{2}|over the next \d+ years).{0,160}"
        r"(target|goal|commit|capacity|revenue|customer|pipeline|design[- ]win)",
        re.I | re.S,
    ),
    re.compile(
        r"(capacity|output|production|throughput).{0,80}"
        r"(\d[\d,\.]*)\s*(gw|gigawatt|mw|units|wafers?)",
        re.I | re.S,
    ),
    re.compile(
        r"(ai|asic|custom silicon|accelerat\w*).{0,100}(growth|demand|revenue|capacity|ramp)",
        re.I | re.S,
    ),
)

GUIDANCE_PATTERNS = (
    re.compile(r"(raise[sd]?|increas(?:e|ed)|lifted|upward).{0,48}guidance", re.I | re.S),
    re.compile(r"(lower(?:ed)?|cut|reduc(?:e|ed)|downward).{0,48}guidance", re.I | re.S),
    re.compile(r"guidance.{0,48}(raise[sd]?|lower(?:ed)?|unchanged|maintain|reaffirm)", re.I | re.S),
    re.compile(
        r"(full[- ]year|next quarter|outlook|expect(?:s|ed)?).{0,80}(revenue|eps|margin).{0,40}(\$|\d)",
        re.I | re.S,
    ),
)

CONCLUSION_MARKERS = re.compile(
    r"\b(buy|sell|overweight|underweight|price target|fair value|undervalued|overvalued|accumulate)\b",
    re.I,
)


def to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round(100.0 * (new / old - 1.0), 2)


def yoy_from_quarters(rows: list[dict[str, Any]], field: str) -> float | None:
    if len(rows) < 5:
        return None
    return pct_change(to_number(rows[0].get(field)), to_number(rows[4].get(field)))


def beat_label(actual: float | None, estimate: float | None) -> str | None:
    if actual is None or estimate is None:
        return None
    if actual > estimate:
        return "beat"
    if actual < estimate:
        return "miss"
    return "inline"


def _clean_span(text: str, limit: int = 280) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:limit]


def _scan(patterns: tuple[re.Pattern[str], ...], text: str, *, kind: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            quote = _clean_span(match.group(0))
            key = quote.lower()
            if len(quote) < 12 or key in seen:
                continue
            seen.add(key)
            found.append({"kind": kind, "quote": quote})
    return found


def extract_commitments(text: str) -> list[dict[str, str]]:
    return _scan(COMMITMENT_PATTERNS, text, kind="management_commitment")


def extract_guidance_mentions(text: str) -> list[dict[str, str]]:
    items = _scan(GUIDANCE_PATTERNS, text, kind="guidance")
    for item in items:
        quote = item["quote"].lower()
        if re.search(r"raise|increas|lifted|upward", quote):
            item["move"] = "raised"
        elif re.search(r"lower|cut|reduc|downward", quote):
            item["move"] = "lowered"
        elif re.search(r"unchanged|maintain|reaffirm", quote):
            item["move"] = "maintained"
        else:
            item["move"] = "stated"
    return items


def guidance_move_from_history(rows: list[dict[str, Any]]) -> str | None:
    moves = [str(row.get("move") or "").lower() for row in rows if row.get("move")]
    if not moves:
        return None
    return moves[0]


def net_margin(revenue: float | None, earnings: float | None) -> float | None:
    if revenue in (None, 0) or earnings is None:
        return None
    return round(100.0 * (earnings / revenue), 2)


def nested_get(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_present(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if payload.get(name) not in (None, "", []):
            return payload.get(name)
    return None


def materials_text(pack: dict[str, Any]) -> str:
    chunks: list[str] = []
    profile = pack.get("company_profile") or {}
    for item in profile.get("transcripts") or []:
        chunks.append(str(item.get("text") or ""))
        for excerpt in item.get("excerpts") or []:
            if isinstance(excerpt, dict):
                chunks.append(str(excerpt.get("text") or excerpt.get("excerpt") or ""))
            else:
                chunks.append(str(excerpt))
    for row in pack.get("earnings_history") or []:
        chunks.append(str(row.get("transcript_text") or ""))
        for excerpt in row.get("transcript_excerpts") or []:
            if isinstance(excerpt, dict):
                chunks.append(str(excerpt.get("text") or excerpt.get("excerpt") or ""))
            else:
                chunks.append(str(excerpt))
    for row in pack.get("guidance_history") or []:
        chunks.append(" ".join(str(row.get(key) or "") for key in ("text", "quote", "summary")))
    for row in pack.get("major_events") or []:
        chunks.append(" ".join(str(row.get(key) or "") for key in ("title", "summary", "text")))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def has_conclusion_language(text: str) -> bool:
    return bool(CONCLUSION_MARKERS.search(text or ""))
