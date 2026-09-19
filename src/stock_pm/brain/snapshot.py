"""Targeted Brain Snapshot for GLM-5.3. Not the whole company Brain."""

from __future__ import annotations

import json
import re
from typing import Any

from stock_pm.research.llm_reason import compact_text

from .claim_integrity import token_overlap
from .shadow import current_states_only

_TOKEN = re.compile(r"[a-z0-9]+")

# Generic words that match almost every AVGO object. Not used as primary needles.
_STOP = {
    "avgo",
    "broadcom",
    "company",
    "companies",
    "management",
    "reported",
    "report",
    "quarter",
    "year",
    "billion",
    "million",
    "revenue",
    "growth",
    "stock",
    "share",
    "shares",
    "price",
    "market",
    "strong",
    "very",
    "next",
    "also",
    "into",
    "from",
    "with",
    "that",
    "this",
    "will",
    "have",
    "been",
    "about",
    "after",
    "over",
    "than",
    "semi",
    "semiconductor",
    "semiconductors",
}

_EVENT_TYPE_CATEGORIES = {
    "customer": ("customer_concentration",),
    "competition": ("competition", "customer_concentration", "market_share"),
    "demand": ("demand",),
    "capex": ("demand", "customer_concentration"),
    "product": ("product_mix",),
    "supply": ("supplier_dependency",),
}

_DEMAND_SIDE = {"customer_concentration", "demand", "competition", "product_mix", "market_share"}
_CUSTOMER_ENTITIES = {
    "google",
    "alphabet",
    "meta",
    "facebook",
    "openai",
    "anthropic",
    "amazon",
    "microsoft",
    "oracle",
    "tesla",
}
_COMPETITOR_ENTITIES = {"marvell", "nvidia", "nvda", "amd", "intel"}


def _hay(row: dict[str, Any] | None) -> str:
    item = row or {}
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "name",
            "title",
            "statement",
            "canonical_key",
            "category",
            "subject",
            "claim_subject",
            "current_state",
            "exposure_type",
        )
    ).lower()


def _tokens(text: str) -> set[str]:
    return {part for part in _TOKEN.findall(text.lower()) if len(part) > 3 and part not in _STOP}


def _row_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row.get(key))
    return ""


def _add(bucket: list[dict[str, Any]], row: dict[str, Any], seen: set[str], *keys: str) -> None:
    token = _row_id(row, *keys)
    if not token or token in seen:
        return
    seen.add(token)
    bucket.append(row)


def _corpus_stops(rows: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    n = 0
    for row in rows:
        toks = _tokens(_hay(row))
        if not toks:
            continue
        n += 1
        for token in toks:
            counts[token] = counts.get(token, 0) + 1
    if not n:
        return set(_STOP)
    return set(_STOP) | {token for token, count in counts.items() if count / n >= 0.4}


def _issuer_stops(ticker: str | None, event: dict[str, Any] | None) -> set[str]:
    extra = {str(ticker or "").lower()}
    extra.discard("")
    blob = f"{(event or {}).get('title') or ''} {(event or {}).get('fact') or ''}".lower()
    if "broadcom" in blob or str(ticker or "").upper() == "AVGO":
        extra.update({"broadcom", "avgo"})
    return extra


def _phrase_hit(row: dict[str, Any], phrase: str, *, stops: set[str]) -> bool:
    raw = str(phrase or "").strip()
    if not raw:
        return False
    ids = {
        str(row.get("state_id") or ""),
        str(row.get("driver_id") or ""),
        str(row.get("claim_id") or ""),
        str(row.get("exposure_id") or ""),
        str(row.get("canonical_key") or ""),
    }
    lowered = raw.lower().replace(" ", "_")
    if lowered in {item.lower() for item in ids if item}:
        return True
    text = _hay(row)
    if raw.lower() in text or lowered.replace("_", " ") in text:
        if len(_tokens(raw) - stops) >= 1 or raw.lower() in text:
            distinctive = _tokens(raw) - stops
            if distinctive and distinctive & _tokens(text):
                return True
    score = token_overlap(raw.replace("_", " "), text)
    return score >= 0.34 and bool(_tokens(raw) - stops)


def _entity_hit(row: dict[str, Any], entity: str, *, stops: set[str]) -> bool:
    token = str(entity or "").strip().lower()
    if len(token) < 4 or token in stops:
        return False
    return token in _hay(row)


def _category_hit(row: dict[str, Any], event_type: str) -> bool:
    wanted = _EVENT_TYPE_CATEGORIES.get(str(event_type or "").lower()) or ()
    if not wanted:
        return False
    cat = str(row.get("category") or row.get("canonical_key") or "").lower()
    if "non_ai" in cat and "demand" in wanted and "customer_concentration" not in cat:
        return False
    return any(item in cat for item in wanted)


def _structured_key_hit(row: dict[str, Any], phrase: str, *, issuer_stops: set[str]) -> bool:
    raw = str(phrase or "").strip().lower().replace(" ", "_")
    if not raw:
        return False
    key = " ".join(
        str(row.get(item) or "")
        for item in ("canonical_key", "category", "name", "state_id", "driver_id", "claim_id", "title")
    ).lower().replace(" ", "_")
    if "non_ai" in key and "non_ai" not in raw:
        return False
    if raw in key:
        return True
    key_tokens = set(_TOKEN.findall(key))
    parts = [part for part in _TOKEN.findall(raw) if len(part) > 2 and part not in issuer_stops]
    if not parts:
        return False
    hits = [part for part in parts if part in key_tokens]
    if len(parts) == 1:
        return bool(hits) and parts[0] not in {"demand", "revenue", "growth"}
    return len(hits) >= 2


def _relation_families(event_type: str, entities: list[str], *, issuer_stops: set[str]) -> set[str]:
    families: set[str] = set()
    et = str(event_type or "").lower()
    ents = {str(item).strip().lower() for item in entities if str(item).strip().lower() not in issuer_stops}
    if et in {"customer", "demand", "capex"} or (ents & _CUSTOMER_ENTITIES):
        families.update({"customer_concentration", "demand_side_ai"})
    if et in {"competition"} or (ents & _COMPETITOR_ENTITIES):
        families.update({"competition", "customer_concentration"})
    if et == "product":
        families.add("product_mix")
    if et == "supply":
        families.add("supplier_dependency")
    return families


def _family_hit(row: dict[str, Any], families: set[str]) -> bool:
    if not families:
        return False
    cat = f"{row.get('category') or ''} {row.get('canonical_key') or ''} {row.get('name') or ''}".lower()
    if "customer_concentration" in families and "customer_concentration" in cat:
        return True
    if "demand_side_ai" in families and "demand" in cat and "ai" in cat and "non_ai" not in cat:
        return True
    if "competition" in families and any(token in cat for token in ("competition", "competitive", "market_share")):
        return True
    if "product_mix" in families and "product_mix" in cat:
        return True
    if "supplier_dependency" in families and "supplier" in cat:
        return True
    return False


def driver_family(row: dict[str, Any] | None) -> str:
    cat = str((row or {}).get("category") or (row or {}).get("canonical_key") or "").lower()
    if any(item in cat for item in _DEMAND_SIDE) or any(item in cat for item in ("hyperscaler", "asic", "silicon", "customer")):
        return "demand_side"
    if any(item in cat for item in ("margin", "pricing", "price")):
        return "margin_side"
    if "valuation" in cat or "multiple" in cat:
        return "valuation_side"
    if any(item in cat for item in ("leverage", "capital", "account", "tax")):
        return "financial_side"
    return cat or "other"


def locate_affected_objects(
    *,
    extract: dict[str, Any] | None,
    event: dict[str, Any] | None,
    states: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
    causal_edges: list[dict[str, Any]] | None = None,
    ticker: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    payload = dict(extract or {})
    item = dict(event or {})
    current = current_states_only(states)
    driver_rows = list(drivers or [])
    claim_rows = list(claims or [])
    exposure_rows = list(exposures or [])
    phrases = [str(value) for value in (payload.get("possible_affected") or payload.get("affected_objects") or []) if str(value).strip()]
    entities = [str(value) for value in (item.get("entities") or payload.get("entities") or []) if str(value).strip()]
    event_type = str(payload.get("event_type") or item.get("event_type") or "")
    issuer_stops = _issuer_stops(ticker, item)
    stops = _corpus_stops(current + driver_rows + claim_rows) | issuer_stops
    families = _relation_families(event_type, entities, issuer_stops=issuer_stops)

    hit_states: list[dict[str, Any]] = []
    hit_drivers: list[dict[str, Any]] = []
    hit_claims: list[dict[str, Any]] = []
    hit_exposures: list[dict[str, Any]] = []
    seen_s: set[str] = set()
    seen_d: set[str] = set()
    seen_c: set[str] = set()
    seen_e: set[str] = set()

    def primary(row: dict[str, Any]) -> bool:
        if any(_structured_key_hit(row, phrase, issuer_stops=issuer_stops) for phrase in phrases):
            return True
        cat = f"{row.get('canonical_key') or ''} {row.get('name') or ''}".lower()
        ai_phrases = [phrase for phrase in phrases if "non_ai" not in phrase.lower()]
        if "non_ai" in cat and ai_phrases and not any("non_ai" in phrase.lower() for phrase in phrases):
            phrase_ok = False
        else:
            phrase_ok = any(_phrase_hit(row, phrase, stops=stops) for phrase in phrases)
        if phrase_ok:
            return True
        if any(_entity_hit(row, entity, stops=stops) for entity in entities):
            return True
        if _family_hit(row, families) or _category_hit(row, event_type):
            return True
        related_ents = {str(item).lower() for item in (row.get("related_entities") or row.get("related_entity_ids") or [])}
        if related_ents & {str(item).lower() for item in entities if str(item).lower() not in issuer_stops}:
            return True
        return False

    for row in current:
        if primary(row):
            _add(hit_states, row, seen_s, "state_id", "name")
    for row in driver_rows:
        if primary(row):
            _add(hit_drivers, row, seen_d, "driver_id", "canonical_key")
    for row in exposure_rows:
        if any(_entity_hit(row, entity, stops=stops) for entity in entities) or any(
            _structured_key_hit(row, phrase, issuer_stops=issuer_stops) for phrase in phrases
        ):
            _add(hit_exposures, row, seen_e, "exposure_id", "exposure_type")
    for row in claim_rows:
        if any(_structured_key_hit(row, phrase, issuer_stops=issuer_stops) for phrase in phrases):
            _add(hit_claims, row, seen_c, "claim_id", "title")
            continue
        if any(_entity_hit(row, entity, stops=stops) for entity in entities):
            _add(hit_claims, row, seen_c, "claim_id", "title")

    driver_ids = {_row_id(row, "driver_id", "canonical_key") for row in hit_drivers}
    for row in driver_rows:
        if _row_id(row, "driver_id", "canonical_key") in driver_ids:
            for cid in row.get("related_claim_ids") or []:
                match = next((item for item in claim_rows if str(item.get("claim_id") or "") == str(cid)), None)
                if match:
                    _add(hit_claims, match, seen_c, "claim_id", "title")
    for row in claim_rows:
        related = {str(item) for item in (row.get("related_driver_ids") or [])}
        if related & driver_ids:
            _add(hit_claims, row, seen_c, "claim_id", "title")

    claim_ids = {_row_id(row, "claim_id") for row in hit_claims}
    for link in links or []:
        cid = str(link.get("claim_id") or "")
        if cid and cid in claim_ids:
            match = next((item for item in claim_rows if str(item.get("claim_id") or "") == cid), None)
            if match:
                _add(hit_claims, match, seen_c, "claim_id", "title")
            continue
        blob = f"{link.get('reason') or ''} {link.get('evidence_id') or ''}".lower()
        if any(str(entity).lower() in blob for entity in entities if str(entity).lower() not in issuer_stops and len(str(entity)) > 3):
            match = next((item for item in claim_rows if str(item.get("claim_id") or "") == cid), None)
            if match:
                _add(hit_claims, match, seen_c, "claim_id", "title")

    object_ids = driver_ids | {_row_id(row, "claim_id") for row in hit_claims} | {_row_id(row, "state_id") for row in hit_states}
    for edge in causal_edges or []:
        ends = {str(edge.get("from_node") or ""), str(edge.get("to_node") or "")}
        if not (ends & object_ids):
            continue
        for token in ends:
            match = next((item for item in claim_rows if str(item.get("claim_id") or "") == token), None)
            if match:
                _add(hit_claims, match, seen_c, "claim_id", "title")

    if not hit_drivers:
        blob = f"{item.get('title') or ''} {item.get('fact') or ''} {payload.get('fact') or ''}"
        fallback = _tokens(blob) - stops
        for row in driver_rows:
            if _family_hit(row, families):
                _add(hit_drivers, row, seen_d, "driver_id", "canonical_key")
            elif fallback & _tokens(_hay(row)) and driver_family(row) in {"demand_side", "margin_side"}:
                if driver_family(row) == "demand_side":
                    _add(hit_drivers, row, seen_d, "driver_id", "canonical_key")

    return expand_related_objects(
        {
            "states": hit_states,
            "drivers": hit_drivers,
            "claims": hit_claims,
            "exposures": hit_exposures,
        },
        states=current,
        drivers=driver_rows,
        claims=claim_rows,
        exposures=exposure_rows,
        links=links,
        causal_edges=causal_edges,
    )


def expand_related_objects(
    affected: dict[str, list[dict[str, Any]]],
    *,
    states: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
    causal_edges: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    expectations: list[dict[str, Any]] | None = None,
    limit: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """One-hop expansion from already-affected objects. Not a Full Brain dump."""
    hit_states = list(affected.get("states") or [])
    hit_drivers = list(affected.get("drivers") or [])
    hit_claims = list(affected.get("claims") or [])
    hit_exposures = list(affected.get("exposures") or [])
    seen_s = {_row_id(row, "state_id", "name") for row in hit_states}
    seen_d = {_row_id(row, "driver_id", "canonical_key") for row in hit_drivers}
    seen_c = {_row_id(row, "claim_id", "title") for row in hit_claims}
    seen_e = {_row_id(row, "exposure_id", "exposure_type") for row in hit_exposures}
    driver_ids = set(seen_d)
    claim_ids = set(seen_c)
    state_ids = set(seen_s)
    evidence_ids: set[str] = set()
    for row in hit_states + hit_drivers + hit_claims + hit_exposures:
        for eid in row.get("evidence_ids") or row.get("supporting_evidence_ids") or []:
            evidence_ids.add(str(eid))
    for row in drivers or []:
        related = {str(item) for item in (row.get("related_claim_ids") or [])}
        if _row_id(row, "driver_id", "canonical_key") in driver_ids or related & claim_ids:
            _add(hit_drivers, row, seen_d, "driver_id", "canonical_key")
            for cid in related:
                match = next((item for item in (claims or []) if str(item.get("claim_id") or "") == cid), None)
                if match:
                    _add(hit_claims, match, seen_c, "claim_id", "title")
        shared = {str(item) for item in (row.get("evidence_ids") or [])} & evidence_ids
        if shared and len(hit_drivers) < len(seen_d) + limit:
            _add(hit_drivers, row, seen_d, "driver_id", "canonical_key")
    for row in claims or []:
        related = {str(item) for item in (row.get("related_driver_ids") or [])}
        if related & driver_ids:
            _add(hit_claims, row, seen_c, "claim_id", "title")
    for row in states or []:
        shared = {str(item) for item in (row.get("evidence_ids") or [])} & evidence_ids
        if shared and len(hit_states) < limit + 2:
            _add(hit_states, row, seen_s, "state_id", "name")
    for row in exposures or []:
        if str(row.get("related_driver_id") or "") in driver_ids or str(row.get("related_claim_id") or "") in claim_ids:
            _add(hit_exposures, row, seen_e, "exposure_id", "exposure_type")
    object_ids = driver_ids | claim_ids | state_ids
    for edge in causal_edges or []:
        ends = {str(edge.get("from_node") or ""), str(edge.get("to_node") or "")}
        if not (ends & object_ids):
            continue
        for token in ends:
            match = next((item for item in (claims or []) if str(item.get("claim_id") or "") == token), None)
            if match:
                _add(hit_claims, match, seen_c, "claim_id", "title")
            match = next((item for item in (drivers or []) if str(item.get("driver_id") or "") == token), None)
            if match:
                _add(hit_drivers, match, seen_d, "driver_id", "canonical_key")
            match = next((item for item in (states or []) if str(item.get("state_id") or "") == token), None)
            if match:
                _add(hit_states, match, seen_s, "state_id", "name")
    extra_hyps = list(hypotheses or [])[:4]
    extra_exp = list(expectations or [])[:3]
    return {
        "states": hit_states[: 4 + limit],
        "drivers": hit_drivers[: 4 + limit],
        "claims": hit_claims[: 4 + limit],
        "exposures": hit_exposures[: 4 + limit],
        "hypotheses": extra_hyps,
        "expectations": extra_exp,
    }


def _evidence_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("evidence_id") or "")


def build_snapshot(
    *,
    event: dict[str, Any],
    affected: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
    causal_edges: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    shadows: list[dict[str, Any]] | None = None,
    causal_paths: list[dict[str, Any]] | None = None,
    causal_gaps: list[dict[str, Any]] | None = None,
    financial_links: list[dict[str, Any]] | None = None,
    market_attentions: list[dict[str, Any]] | None = None,
    expectations: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    price: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claim_ids = {str(row.get("claim_id")) for row in affected.get("claims") or [] if row.get("claim_id")}
    driver_ids = {str(row.get("driver_id")) for row in affected.get("drivers") or [] if row.get("driver_id")}
    state_ids = {str(row.get("state_id")) for row in affected.get("states") or [] if row.get("state_id")}
    object_ids = claim_ids | driver_ids | state_ids | {
        str(row.get("exposure_id") or "") for row in affected.get("exposures") or [] if row.get("exposure_id")
    }
    for path in causal_paths or []:
        object_ids.update(str(node) for node in (path.get("nodes") or []) if str(node))
        object_ids.update(str(edge_id) for edge_id in (path.get("edge_ids") or []) if str(edge_id))
        for edge in path.get("edges") or []:
            if isinstance(edge, dict):
                object_ids.add(str(edge.get("from_node") or ""))
                object_ids.add(str(edge.get("to_node") or ""))
    object_ids.discard("")
    evidence_ids: set[str] = set()
    oppose_ids: set[str] = set()
    for row in (affected.get("states") or []) + (affected.get("drivers") or []) + (affected.get("claims") or []):
        for eid in row.get("evidence_ids") or row.get("supporting_evidence_ids") or []:
            evidence_ids.add(str(eid))
        for eid in row.get("opposing_evidence_ids") or []:
            oppose_ids.add(str(eid))
            evidence_ids.add(str(eid))
    counter_links = [
        row
        for row in (links or [])
        if str(row.get("direction") or "") == "oppose" and str(row.get("claim_id") or "") in claim_ids
    ]
    support_links = [
        row
        for row in (links or [])
        if str(row.get("direction") or "") == "support" and str(row.get("claim_id") or "") in claim_ids
    ]
    for row in counter_links:
        if row.get("evidence_id"):
            oppose_ids.add(str(row.get("evidence_id")))
            evidence_ids.add(str(row.get("evidence_id")))
    for row in support_links:
        if row.get("evidence_id"):
            evidence_ids.add(str(row.get("evidence_id")))
    index = {_evidence_id(row): row for row in (evidence or []) if _evidence_id(row)}
    support_rows = [index[eid] for eid in evidence_ids if eid in index and eid not in oppose_ids]
    counter_rows = []
    for eid in oppose_ids:
        if eid in index:
            counter_rows.append(index[eid])
    if not counter_rows:
        counter_rows = counter_links[:12]
    relevant_edges = [
        row
        for row in (causal_edges or [])
        if {str(row.get("from_node") or ""), str(row.get("to_node") or "")} & object_ids
    ][:8]
    relevant_history = [row for row in (history or []) if str(row.get("object_id") or "") in object_ids][-8:]
    event_blob = f"{event.get('title') or ''} {event.get('fact') or ''} {' '.join(str(x) for x in (event.get('entities') or []))}".lower()
    relevant_shadows = []
    for row in shadows or []:
        text = f"{row.get('name') or ''} {row.get('statement') or ''}".lower()
        if any(token in text for token in _tokens(event_blob) if len(token) > 4):
            relevant_shadows.append(row)
    event_tokens = _tokens(event_blob)
    challenged_ids = _challenged_ids(
        event_tokens,
        states=current_states_only(affected.get("states")),
        drivers=list(affected.get("drivers") or []),
        claims=list(affected.get("claims") or []),
        edges=relevant_edges,
    )
    path_rows = [_compact_path(row) for row in list(causal_paths or [])[:4]]
    gap_rows = [_compact_gap(row) for row in list(causal_gaps or [])[:3]]
    finance_rows = [_compact_finance(row) for row in list(financial_links or [])[:4]]
    attention_rows = [_compact_attention(row) for row in list(market_attentions or [])[:3]]
    expectation_rows = [_compact_expectation(row) for row in list(expectations or [])[:3]]
    hypothesis_rows = [_compact_hypothesis(row) for row in list(hypotheses or [])[:4]]
    state_rows = [_compact_state(row, challenged=_row_id(row, "state_id", "name") in challenged_ids) for row in current_states_only(affected.get("states"))]
    driver_rows = [_compact_driver(row, challenged=_row_id(row, "driver_id", "canonical_key") in challenged_ids) for row in list(affected.get("drivers") or [])]
    claim_rows = [_compact_claim(row, challenged=_row_id(row, "claim_id", "title") in challenged_ids) for row in list(affected.get("claims") or [])]
    exposure_rows = [_compact_exposure(row) for row in list(affected.get("exposures") or [])]
    edge_rows = [_compact_edge(row, challenged=str(row.get("edge_id") or "") in challenged_ids) for row in relevant_edges]
    evidence_rows = [_compact_evidence(row) for row in support_rows[:16]]
    counter_compact = [_compact_evidence(row) for row in counter_rows[:12]]
    history_rows = [_compact_history(row) for row in relevant_history]
    shadow_rows = [_compact_shadow(row) for row in relevant_shadows[:6]]
    event_row = _compact_event(event)
    causal_context = {
        "causal_edges": edge_rows,
        "causal_paths": path_rows,
        "causal_gaps": gap_rows,
        "exposures": exposure_rows,
        "financial_links": finance_rows,
        "market_attentions": attention_rows,
        "expectations": expectation_rows,
        "hypotheses": hypothesis_rows,
    }
    return {
        "event": event_row,
        "states": state_rows,
        "drivers": driver_rows,
        "claims": claim_rows,
        "exposures": exposure_rows,
        "evidence": evidence_rows,
        "counter_evidence": counter_compact,
        "causal_edges": edge_rows,
        "causal_paths": path_rows,
        "causal_gaps": gap_rows,
        "financial_links": finance_rows,
        "market_attentions": attention_rows,
        "expectations": expectation_rows,
        "hypotheses": hypothesis_rows,
        "history": history_rows,
        "shadows": shadow_rows,
        "targeted": True,
        "full_brain": False,
        "compacted": True,
        "challenged_ids": sorted(challenged_ids)[:12],
        "causal_context_tokens": max(0, (len(json.dumps(causal_context, default=str, ensure_ascii=False)) + 3) // 4),
        "context_part_tokens": _context_part_tokens(
            event=event_row,
            states=state_rows,
            evidence=evidence_rows + counter_compact,
            causal=causal_context,
            market={"attentions": attention_rows, "expectations": expectation_rows, "hypotheses": hypothesis_rows},
            history=history_rows,
            price=price
            or {
                "price_change_pct": event.get("price_change_pct"),
                "peers": event.get("peers") or event.get("peer_moves"),
            },
        ),
    }


def _challenged_ids(
    event_tokens: set[str],
    *,
    states: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    ids: set[str] = set()
    for row in states + drivers + claims:
        token = _row_id(row, "state_id", "driver_id", "claim_id", "canonical_key", "name")
        if token and len(event_tokens & _tokens(_hay(row))) >= 2:
            ids.add(token)
    for row in edges:
        blob = f"{row.get('mechanism') or ''} {row.get('from_node') or ''} {row.get('to_node') or ''}"
        if len(event_tokens & _tokens(blob)) >= 2 and row.get("edge_id"):
            ids.add(str(row.get("edge_id")))
    return ids


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_key": event.get("event_key") or event.get("event_id"),
        "title": compact_text(event.get("title") or "", 160),
        "fact": compact_text(event.get("fact") or event.get("statement") or "", 200),
        "event_type": event.get("event_type"),
        "kind": event.get("kind"),
        "entities": list(event.get("entities") or [])[:6],
        "fact_reliability": event.get("fact_reliability"),
        "confirmed": event.get("confirmed"),
        "price_change_pct": event.get("price_change_pct"),
        "peers": event.get("peers") or event.get("peer_moves"),
        "actual": event.get("actual"),
        "expected": event.get("expected"),
    }


def _compact_state(row: dict[str, Any], *, challenged: bool) -> dict[str, Any]:
    limit = 200 if challenged else 80
    return {
        "state_id": row.get("state_id"),
        "name": compact_text(row.get("name") or "", 80),
        "status": row.get("status") or row.get("direction") or row.get("confidence"),
        "summary": compact_text(row.get("statement") or row.get("current_state") or "", limit),
        "confidence": row.get("confidence"),
        "evidence_ids": list(row.get("evidence_ids") or [])[:6],
    }


def _compact_driver(row: dict[str, Any], *, challenged: bool) -> dict[str, Any]:
    limit = 200 if challenged else 80
    return {
        "driver_id": row.get("driver_id"),
        "canonical_key": row.get("canonical_key"),
        "name": compact_text(row.get("name") or "", 80),
        "category": row.get("category"),
        "status": row.get("status") or row.get("current_state"),
        "summary": compact_text(row.get("current_state") or row.get("why_it_matters") or "", limit),
        "confidence": row.get("confidence") or row.get("uncertainty"),
        "evidence_ids": list(row.get("evidence_ids") or [])[:6],
        "related_claim_ids": list(row.get("related_claim_ids") or [])[:4],
    }


def _compact_claim(row: dict[str, Any], *, challenged: bool) -> dict[str, Any]:
    limit = 200 if challenged else 80
    return {
        "claim_id": row.get("claim_id"),
        "title": compact_text(row.get("title") or "", 80),
        "status": row.get("status") or row.get("final_status"),
        "is_core": bool(row.get("is_core")),
        "summary": compact_text(row.get("statement") or "", limit),
        "confidence": row.get("confidence"),
        "evidence_ids": list(row.get("evidence_ids") or row.get("supporting_evidence_ids") or [])[:6],
        "related_driver_ids": list(row.get("related_driver_ids") or [])[:4],
    }


def _compact_edge(row: dict[str, Any], *, challenged: bool) -> dict[str, Any]:
    payload = {
        "edge_id": row.get("edge_id"),
        "source": row.get("from_node") or row.get("source"),
        "target": row.get("to_node") or row.get("target"),
        "from_node": row.get("from_node") or row.get("source"),
        "to_node": row.get("to_node") or row.get("target"),
        "status": row.get("status"),
        "confidence": row.get("confidence"),
        "mechanism_short": compact_text(row.get("mechanism") or row.get("statement") or "", 80),
        "condition": compact_text(row.get("conditions") or row.get("condition") or "", 80),
    }
    if challenged:
        payload["support_evidence_ids"] = list(row.get("support_evidence_ids") or row.get("evidence_ids") or [])[:6]
        payload["counter_evidence_ids"] = list(row.get("counter_evidence_ids") or [])[:4]
    return payload


def _compact_evidence(row: dict[str, Any]) -> dict[str, Any]:
    fact = compact_text(row.get("fact") or row.get("statement") or row.get("excerpt") or "", 160)
    return {
        "id": row.get("id") or row.get("evidence_id"),
        "evidence_id": row.get("evidence_id") or row.get("id"),
        "title": compact_text(row.get("title") or "", 80),
        "fact": fact,
        "excerpt": compact_text(row.get("excerpt") or fact, 160),
    }


def _compact_history(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "history_id": row.get("history_id"),
        "object_id": row.get("object_id"),
        "object_type": row.get("object_type"),
        "reason": compact_text(row.get("reason") or "", 80),
    }


def _compact_hypothesis(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis_id": row.get("hypothesis_id"),
        "canonical_key": row.get("canonical_key"),
        "kind": row.get("kind"),
        "status": row.get("status"),
        "confidence": row.get("confidence"),
        "summary": compact_text(row.get("hypothesis") or row.get("name") or "", 80),
    }


def _compact_expectation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "expectation_id": row.get("expectation_id"),
        "name": compact_text(row.get("name") or "", 80),
        "comparison": row.get("comparison"),
        "trend": row.get("trend"),
        "actual": row.get("actual"),
        "expected": row.get("expected"),
    }


def _compact_attention(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "attention_id": row.get("attention_id"),
        "name": compact_text(row.get("name") or "", 80),
        "summary": compact_text(row.get("statement") or "", 80),
        "alignment": row.get("alignment"),
        "related_objects": list(row.get("related_objects") or [])[:4],
    }


def _compact_exposure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "exposure_id": row.get("exposure_id"),
        "exposure_type": row.get("exposure_type"),
        "subject": compact_text(row.get("subject") or "", 40),
        "object_name": compact_text(row.get("object_name") or "", 80),
        "direction": row.get("direction"),
        "mechanism": compact_text(row.get("mechanism") or row.get("reason") or "", 80),
    }


def _compact_path(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": list(row.get("nodes") or [])[:8],
        "edge_ids": list(row.get("edge_ids") or [])[:8],
        "status": row.get("status"),
        "claim_id": row.get("claim_id"),
    }


def _compact_gap(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": compact_text(row.get("question") or "", 160),
        "reason": compact_text(row.get("reason") or "", 80),
        "to_node": row.get("to_node"),
        "from_node": row.get("from_node"),
    }


def _compact_finance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_node": row.get("from_node"),
        "to_node": row.get("to_node"),
        "relationship_type": row.get("relationship_type"),
        "status": row.get("status"),
        "mechanism": compact_text(row.get("mechanism") or "", 80),
    }


def _compact_shadow(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "shadow_id": row.get("shadow_id"),
        "name": compact_text(row.get("name") or "", 80),
        "summary": compact_text(row.get("statement") or "", 80),
        "status": row.get("status"),
    }


def _approx_tokens(payload: Any) -> int:
    return max(0, (len(json.dumps(payload, default=str, ensure_ascii=False)) + 3) // 4)


def _context_part_tokens(
    *,
    event: dict[str, Any],
    states: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    causal: dict[str, Any],
    market: dict[str, Any],
    history: list[dict[str, Any]],
    price: dict[str, Any] | None = None,
) -> dict[str, int]:
    return {
        "event": _approx_tokens(event),
        "state": _approx_tokens(states),
        "evidence": _approx_tokens(evidence),
        "causal": _approx_tokens(causal),
        "market": _approx_tokens(market),
        "price": _approx_tokens(price or {}),
        "history": _approx_tokens(history),
    }
