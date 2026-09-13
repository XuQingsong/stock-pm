"""E8 / E10 accept scoring used by tests and the black-box script.

Live E8 requires a current claim excerpt that actually supports the claim.
URL, publisher, HTTP status, title, or a clickable link cannot pass alone.

E10 requires a traceable Fact → Change → Expectation → Impact → What changes
chain. Five `data-answer` markers are never sufficient.
"""

from __future__ import annotations

from typing import Any

from .analyze import causal_chain_is_complete, closed_loop_summary
from .evidence import excerpt_supports_claim

LAYER_ORDER = ("fact", "change", "expectation", "impact", "what_changes")
PLACEHOLDER_TEXTS = {"", "—", "-", "withhold", "none", "null"}


def current_claim_rows(claims: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = []
    for claim in claims or []:
        if str(claim.get("status") or "") in {"superseded", "revoked"}:
            continue
        rows.append(claim)
    return rows


def current_supporting_excerpts(claims: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    hits = []
    for claim in current_claim_rows(claims):
        excerpt = str(claim.get("excerpt") or claim.get("claim_support_excerpt") or "")
        title = str(claim.get("title") or "")
        if excerpt_supports_claim(str(claim.get("text") or ""), excerpt, title=title):
            hits.append(claim)
    return hits


def collect_event_claims(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events or []:
        rows.extend(event.get("claims") or [])
    return rows


def e8_live_excerpt_ok(
    events: list[dict[str, Any]] | None = None,
    *,
    claims: list[dict[str, Any]] | None = None,
) -> bool:
    """Event lists use the per-event closed loop. Bare claims stay excerpt-only."""
    if events:
        return closed_loop_summary(events)["ok"]
    return bool(current_supporting_excerpts(claims))


def e8_metadata_only_passes(
    *,
    source_url: str,
    publisher: str = "",
    http_status: int = 200,
    title: str = "",
    excerpt: str = "",
    claim: str = "",
) -> bool:
    """Probe helper: official metadata without a supporting excerpt must be False."""
    del http_status
    text = claim or title
    return e8_live_excerpt_ok(
        claims=[
            {
                "text": text,
                "excerpt": excerpt,
                "title": title,
                "status": "current",
                "source_url": source_url,
                "publisher": publisher,
            }
        ]
    )


def events_have_complete_chain(events: list[dict[str, Any]] | None) -> bool:
    """True only when a valid observable closed loop exists and none is leaked."""
    return closed_loop_summary(events)["ok"]


def _one_dom_chain_ok(layers: list[dict[str, Any]] | None) -> bool:
    by_id = {str(row.get("id") or row.get("layer") or ""): row for row in layers or []}
    prev_id = None
    for name in LAYER_ORDER:
        row = by_id.get(name)
        if not row:
            return False
        text = str(row.get("text") or "").strip().lower()
        if text in PLACEHOLDER_TEXTS:
            return False
        layer_id = str(row.get("layerId") or row.get("layer_id") or "")
        if not layer_id:
            return False
        cites = str(row.get("cites") or "")
        cite_ids = {item for item in cites.replace(",", " ").split() if item}
        if prev_id and prev_id not in cite_ids:
            return False
        prev_id = layer_id
    return True


def e10_dom_chains_ok(chains: list[Any] | None) -> bool:
    for chain in chains or []:
        layers = chain if isinstance(chain, list) else chain.get("layers") if isinstance(chain, dict) else []
        if _one_dom_chain_ok(layers):
            return True
    return False


def e10_event_passes(
    analysis: dict[str, Any] | None,
    *,
    dom_answers: list[str] | None = None,
    dom_chains: list[Any] | None = None,
) -> bool:
    """DOM answer markers are ignored. The causal chain must be complete."""
    del dom_answers
    if not causal_chain_is_complete((analysis or {}).get("causal_chain")):
        return False
    if dom_chains is not None:
        return e10_dom_chains_ok(dom_chains)
    return True
