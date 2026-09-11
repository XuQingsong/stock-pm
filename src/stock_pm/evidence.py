"""Minimal evidence schema for the judgment card.

Facts point at raw, verifiable rows. Analysis points at derived objects and
must keep `based_on` / `refs` back to facts. Analysis is never labeled fact.
"""

from __future__ import annotations

from typing import Any

from .ux_copy import is_http_url


MODEL_VERSION = "judgment-v1"

LAYER_FACT = "fact"
LAYER_ANALYSIS = "analysis"
LAYERS = (LAYER_FACT, LAYER_ANALYSIS)

COMPLETE = "complete"
PARTIAL = "partial"
MISSING = "missing"
COMPLETENESS = (COMPLETE, PARTIAL, MISSING)

INCOMPLETE_LABEL = "分析依据不完整"

FACT_TABLES = frozenset(
    {
        "market_snapshots",
        "price_bars",
        "earnings_reports",
        "macro_events",
        "news_articles",
        "fundamentals_snapshots",
        "cboe_option_stats",
        "option_wall_snapshots",
        "large_trades",
    }
)
ANALYSIS_TABLES = frozenset(
    {
        "environment_snapshots",
        "tape_analyses",
        "review_notes",
        "daily_reviews",
        "predictions",
    }
)

# Display names only. Never invent a URL for these.
SOURCE_NAMES = {
    "market_snapshots": "Alpaca",
    "price_bars": "Alpaca",
    "option_wall_snapshots": "Alpaca",
    "earnings_reports": None,
    "fundamentals_snapshots": None,
    "macro_events": None,
    "news_articles": None,
    "cboe_option_stats": "Cboe",
    "large_trades": "Alpaca",
}


def _as_of_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:10] if text else None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _ref_id(value: Any) -> str | int | None:
    if value in (None, "", False):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        parsed = int(text)
        return parsed if parsed > 0 else None
    return text


def evidence_item(
    *,
    layer: str,
    ref_table: str | None = None,
    ref_id: Any = None,
    as_of: Any = None,
    text: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    refs: list[dict] | None = None,
    based_on: list[dict] | None = None,
    completeness: str = PARTIAL,
    role: str | None = None,
) -> dict:
    if layer not in LAYERS:
        raise ValueError(f"unsupported evidence layer: {layer}")
    if completeness not in COMPLETENESS:
        completeness = PARTIAL
    url = str(source_url).strip() if source_url else None
    if url and not is_http_url(url):
        url = None
    children = [dict(item) for item in (based_on or refs or []) if isinstance(item, dict)]
    if layer == LAYER_FACT:
        children = []
        if ref_table and ref_table not in FACT_TABLES:
            completeness = PARTIAL
    elif layer == LAYER_ANALYSIS:
        if ref_table and ref_table in FACT_TABLES:
            raise ValueError("analysis evidence cannot use a fact table")
        if not children:
            completeness = PARTIAL if completeness == COMPLETE else completeness
    payload = {
        "layer": layer,
        "ref_table": ref_table,
        "ref_id": _ref_id(ref_id),
        "as_of": _as_of_text(as_of),
        "text": _clean_text(text) or (INCOMPLETE_LABEL if layer == LAYER_ANALYSIS else None),
        "source_name": _clean_text(source_name),
        "source_url": url,
        "refs": children,
        "based_on": children,
        "completeness": completeness,
    }
    if role:
        payload["role"] = role
    if layer == LAYER_ANALYSIS and completeness != COMPLETE:
        if payload["text"] and INCOMPLETE_LABEL not in payload["text"]:
            payload["text"] = f"{payload['text']}（{INCOMPLETE_LABEL}）"
        elif not payload["text"]:
            payload["text"] = INCOMPLETE_LABEL
    return payload


def fact_ref(
    *,
    ref_table: str,
    ref_id: Any = None,
    as_of: Any = None,
    text: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    completeness: str = COMPLETE,
    role: str | None = None,
) -> dict:
    name = source_name if source_name is not None else SOURCE_NAMES.get(ref_table)
    return evidence_item(
        layer=LAYER_FACT,
        ref_table=ref_table,
        ref_id=ref_id,
        as_of=as_of,
        text=text,
        source_name=name,
        source_url=source_url,
        completeness=completeness if ref_id is not None else PARTIAL,
        role=role,
    )


def analysis_ref(
    *,
    ref_table: str,
    ref_id: Any = None,
    as_of: Any = None,
    text: str | None = None,
    based_on: list[dict] | None = None,
    completeness: str | None = None,
    role: str | None = None,
) -> dict:
    children = list(based_on or [])
    resolved = completeness
    if resolved is None:
        if children and all(item.get("completeness") == COMPLETE and item.get("ref_id") for item in children):
            resolved = COMPLETE
        elif children:
            resolved = PARTIAL
        else:
            resolved = PARTIAL
    return evidence_item(
        layer=LAYER_ANALYSIS,
        ref_table=ref_table,
        ref_id=ref_id,
        as_of=as_of,
        text=text,
        based_on=children,
        completeness=resolved,
        role=role,
    )


def evidence_key(item: dict | None) -> tuple[Any, ...]:
    row = item or {}
    return (row.get("layer"), row.get("ref_table"), row.get("ref_id"), row.get("as_of"), row.get("text"))


def public_evidence(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return None
    children = [
        public_evidence(child)
        for child in (item.get("based_on") or item.get("refs") or [])
        if isinstance(child, dict)
    ]
    children = [child for child in children if child]
    return {
        "layer": item.get("layer"),
        "ref_table": item.get("ref_table"),
        "ref_id": item.get("ref_id"),
        "as_of": item.get("as_of"),
        "text": item.get("text"),
        "source_name": item.get("source_name"),
        "source_url": item.get("source_url") if is_http_url(item.get("source_url")) else None,
        "refs": children,
        "based_on": children,
        "completeness": item.get("completeness") or PARTIAL,
        "role": item.get("role"),
    }
