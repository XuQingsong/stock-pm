"""Targeted Brain Snapshot for GLM-5.3. Not the whole company Brain."""

from __future__ import annotations

import json
import re
from typing import Any

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

    return {
        "states": hit_states,
        "drivers": hit_drivers,
        "claims": hit_claims,
        "exposures": hit_exposures,
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
    path_rows = list(causal_paths or [])[:4]
    gap_rows = list(causal_gaps or [])[:3]
    finance_rows = list(financial_links or [])[:4]
    attention_rows = list(market_attentions or [])[:3]
    expectation_rows = list(expectations or [])[:3]
    hypothesis_rows = list(hypotheses or [])[:4]
    causal_context = {
        "causal_edges": relevant_edges,
        "causal_paths": path_rows,
        "causal_gaps": gap_rows,
        "exposures": list(affected.get("exposures") or []),
        "financial_links": finance_rows,
        "market_attentions": attention_rows,
        "expectations": expectation_rows,
        "hypotheses": hypothesis_rows,
    }
    return {
        "event": event,
        "states": current_states_only(affected.get("states")),
        "drivers": list(affected.get("drivers") or []),
        "claims": list(affected.get("claims") or []),
        "exposures": list(affected.get("exposures") or []),
        "evidence": support_rows[:16],
        "counter_evidence": counter_rows[:12],
        "causal_edges": relevant_edges,
        "causal_paths": path_rows,
        "causal_gaps": gap_rows,
        "financial_links": finance_rows,
        "market_attentions": attention_rows,
        "expectations": expectation_rows,
        "hypotheses": hypothesis_rows,
        "history": relevant_history,
        "shadows": relevant_shadows[:6],
        "targeted": True,
        "full_brain": False,
        "causal_context_tokens": max(0, (len(json.dumps(causal_context, default=str, ensure_ascii=False)) + 3) // 4),
    }
