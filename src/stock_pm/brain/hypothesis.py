"""Market Driver Hypothesis: what the tape *may* be trading. Never a fact."""

from __future__ import annotations

import re
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .types import CONFIDENCE, HYPOTHESIS_KINDS, HYPOTHESIS_STATUSES, LOW_RELIABILITY

_KIND_NEEDLES = (
    ("customer_concentration", ("customer", "google", "meta", "concentration", "order", "tpu")),
    ("ai_demand", ("ai demand", "capex", "ai revenue", "hyperscaler", "custom silicon", "asic", "xpu")),
    ("company_specific", ("marvell", "design win", "lost socket", "share loss")),
    ("valuation", ("valuation", "multiple", "compression", "de-rate", "derate")),
    ("sector_macro", ("sector", "macro", "rates", "sox")),
)

_STATUS_RANK = {
    "closed": 0,
    "retired": 0,
    "unresolved": 1,
    "candidate": 2,
    "weakened": 3,
    "open": 4,
    "supported": 5,
}

_RISK = ("delay", "reduce", "cut", "miss", "cancel", "weaker", "concern", "slow", "dump", "lose", "lost")
_RELIEF = ("confirm", "confirmed", "expand", "beat", "win", "stronger", "accelerat", "printed")


def _has_token(blob: str, tokens: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(token)}", blob) for token in tokens)


def event_polarity(event: dict[str, Any] | None) -> str:
    item = event or {}
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    rumor = str(item.get("fact_reliability") or "") in LOW_RELIABILITY or str(item.get("kind") or "") == "rumor"
    risk = _has_token(blob, _RISK)
    relief = _has_token(blob, _RELIEF)
    if "unconfirmed" in blob:
        relief = False
    if rumor and not relief:
        return "risk"
    if relief and not risk:
        return "relief"
    if risk and not relief:
        return "risk"
    return "mixed"


def hypothesis_canonical_key(raw: dict[str, Any] | str) -> str:
    if isinstance(raw, str):
        text = raw
        kind = ""
    else:
        kind = str(raw.get("kind") or raw.get("canonical_key") or "")
        text = str(raw.get("hypothesis") or raw.get("name") or raw.get("statement") or kind)
    blob = f"{kind} {text}".lower()
    for token, needles in _KIND_NEEDLES:
        if token in blob or any(needle in blob for needle in needles):
            return token
    key = compact_text(text.lower().replace(" ", "_"), 40)
    return key or "other"


def infer_kind(raw: dict[str, Any] | str) -> str:
    key = hypothesis_canonical_key(raw)
    return key if key in HYPOTHESIS_KINDS else "other"


def normalize_hypothesis(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or raw.get("ticker") or "").upper()
    statement = compact_text(raw.get("hypothesis") or raw.get("statement") or raw.get("name") or "", 240)
    kind = str(raw.get("kind") or infer_kind(raw))
    if kind not in HYPOTHESIS_KINDS:
        kind = "other"
    canonical = compact_text(raw.get("canonical_key") or hypothesis_canonical_key({**raw, "kind": kind}), 40) or kind
    status = str(raw.get("status") or "candidate")
    if status not in HYPOTHESIS_STATUSES:
        status = "candidate"
    confidence = str(raw.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    if str(raw.get("source_kind") or "") in {"rumor", "signal"} or str(raw.get("fact_reliability") or "") in LOW_RELIABILITY:
        confidence = "low"
        if status in {"supported", "established"}:
            status = "open"
    return {
        "hypothesis_id": raw.get("hypothesis_id") or new_id("bmdh"),
        "ticker": symbol,
        "canonical_key": canonical,
        "kind": kind,
        "hypothesis": statement or canonical.replace("_", " "),
        "name": compact_text(raw.get("name") or canonical, 80),
        "confidence": confidence,
        "status": status,
        "supporting_observations": [str(item) for item in (raw.get("supporting_observations") or []) if str(item).strip()][:12],
        "counter_observations": [str(item) for item in (raw.get("counter_observations") or []) if str(item).strip()][:12],
        "related_expectation_id": raw.get("related_expectation_id"),
        "related_attention_id": raw.get("related_attention_id"),
        "related_causal_path": list(raw.get("related_causal_path") or [])[:8],
        "source_kind": str(raw.get("source_kind") or "news"),
        "reason": compact_text(raw.get("reason") or statement, 240),
        "polarity": str(raw.get("polarity") or "mixed"),
    }


def peer_pattern(issuer_pct: Any, peers: dict[str, Any] | None) -> str | None:
    try:
        issuer = float(issuer_pct)
    except (TypeError, ValueError):
        return None
    if abs(issuer) < 3:
        return None
    rows = {}
    for key, value in (peers or {}).items():
        try:
            rows[str(key).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    values = list(rows.values())
    avg = sum(values) / len(values)
    same_sign = sum(1 for value in values if value * issuer > 0)
    if abs(issuer) >= 5 and all(abs(value) <= 1.5 for value in values):
        return "company_specific"
    if abs(avg) >= 3 and same_sign >= max(1, int(0.6 * len(values))) and abs(avg - issuer) <= 4:
        return "sector_macro"
    return None


def apply_observation(existing: dict[str, Any], *, observation: str, direction: str, resolve: bool = False) -> dict[str, Any]:
    row = dict(existing)
    key = "supporting_observations" if direction == "support" else "counter_observations"
    items = list(row.get(key) or [])
    if observation and observation not in items:
        items.append(observation)
    row[key] = items[:12]
    rank = _STATUS_RANK.get(str(row.get("status") or "candidate"), 2)
    if direction == "support":
        if str(row.get("status") or "") in {"closed", "retired"}:
            row["status"] = "candidate"
        else:
            row["status"] = "supported" if rank >= _STATUS_RANK["open"] else "open"
        if str(row.get("confidence") or "low") == "low":
            row["confidence"] = "medium"
    else:
        counters = list(row.get("counter_observations") or [])
        if resolve or len(counters) >= 1:
            row["status"] = "closed"
            row["confidence"] = "low"
        else:
            row["status"] = "weakened"
    return row


def hypotheses_from_event(
    event: dict[str, Any] | None,
    *,
    ticker: str,
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = event or {}
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()
    wanted: list[str] = []
    for kind in item.get("candidate_hypotheses") or []:
        token = hypothesis_canonical_key(str(kind))
        if token not in wanted:
            wanted.append(token)
    for kind, needles in _KIND_NEEDLES:
        if any(needle in blob for needle in needles) and kind not in wanted:
            wanted.append(kind)
    issuer = item.get("price_change_pct")
    pattern = peer_pattern(issuer, item.get("peers") or item.get("peer_moves"))
    if pattern and pattern not in wanted:
        wanted.append(pattern)
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    duplicates = 0
    closed = 0
    index = {str(row.get("canonical_key") or ""): row for row in (existing or [])}
    rumor = str(item.get("fact_reliability") or "") in LOW_RELIABILITY or str(item.get("kind") or "") == "rumor"
    polarity = event_polarity(item)
    observation = compact_text(item.get("title") or item.get("fact") or "event", 160)
    for kind in wanted[:5]:
        if kind == "other" and kind not in (item.get("candidate_hypotheses") or []):
            continue
        payload = {
            "kind": kind if kind in HYPOTHESIS_KINDS else "other",
            "canonical_key": kind,
            "hypothesis": _label(kind),
            "source_kind": "rumor" if rumor else (item.get("kind") or "news"),
            "fact_reliability": item.get("fact_reliability"),
            "status": "candidate",
            "confidence": "low" if rumor else "medium",
            "supporting_observations": [observation] if observation else [],
            "polarity": polarity,
        }
        if kind in index:
            duplicates += 1
            prior = index[kind]
            prior_polarity = str(prior.get("polarity") or event_polarity({"title": prior.get("hypothesis"), "fact": " ".join(prior.get("supporting_observations") or [])}))
            oppose = prior_polarity in {"risk", "relief"} and polarity in {"risk", "relief"} and prior_polarity != polarity
            direction = "weaken" if oppose else "support"
            resolve = oppose and (not rumor) and str(item.get("confirmed") or "").lower() in {"1", "true", "yes"} or (
                oppose and str(item.get("fact_reliability") or "") == "direct_fact"
            )
            merged = apply_observation(prior, observation=observation, direction=direction, resolve=bool(resolve))
            merged["polarity"] = polarity if not oppose else prior_polarity
            if not rumor:
                merged["source_kind"] = item.get("kind") or "news"
                merged["fact_reliability"] = item.get("fact_reliability")
            updated.append(normalize_hypothesis(merged, ticker=ticker))
        else:
            created.append(normalize_hypothesis(payload, ticker=ticker))
    strengthened = 0
    weakened = 0
    if pattern:
        target_kind = pattern
        pool = created + updated
        hit = next((row for row in pool if row.get("canonical_key") == target_kind or row.get("kind") == target_kind), None)
        note = f"price {issuer} peers {item.get('peers') or item.get('peer_moves')}"
        if hit:
            next_row = apply_observation(hit, observation=note, direction="support")
            if not rumor:
                next_row["status"] = "supported"
                if str(next_row.get("confidence") or "low") == "low":
                    next_row["confidence"] = "medium"
            next_row = normalize_hypothesis(next_row, ticker=ticker)
            if hit in created:
                created[created.index(hit)] = next_row
            else:
                updated[updated.index(hit)] = next_row
            strengthened += 1
        if pattern == "sector_macro":
            for row in list(created) + list(updated):
                if str(row.get("kind") or "") != "company_specific":
                    continue
                weakened_row = apply_observation(row, observation=note, direction="weaken")
                weakened_row = normalize_hypothesis(weakened_row, ticker=ticker)
                if row in created:
                    created[created.index(row)] = weakened_row
                else:
                    updated[updated.index(row)] = weakened_row
                weakened += 1
    for row in updated:
        status = str(row.get("status") or "")
        if status == "weakened":
            weakened += 1
        elif status in {"closed", "retired"}:
            closed += 1
        elif status in {"supported", "open"}:
            strengthened += 1
    return {
        "created": created,
        "updated": updated,
        "duplicates_prevented": duplicates,
        "peer_pattern": pattern,
        "peer_observations_used": 1 if pattern else 0,
        "hypothesis_strengthened": strengthened,
        "hypothesis_weakened": weakened,
        "hypothesis_closed": closed,
    }


def _label(kind: str) -> str:
    return {
        "ai_demand": "AI demand expectations are weakening",
        "customer_concentration": "Customer concentration concern is increasing",
        "valuation": "Valuation compression",
        "sector_macro": "Sector / macro move",
        "company_specific": "Company-specific concern",
    }.get(kind, kind.replace("_", " "))


def is_unresolved_price(
    event: dict[str, Any] | None,
    *,
    expectation: dict[str, Any] | None,
    peer: str | None,
) -> bool:
    item = event or {}
    try:
        move = abs(float(item.get("price_change_pct")))
    except (TypeError, ValueError):
        return False
    if move < 5:
        return False
    comparison = str((expectation or {}).get("comparison") or "")
    if comparison in {"above", "below"}:
        return False
    if peer in {"company_specific", "sector_macro"}:
        return False
    blob = f"{item.get('title') or ''} {item.get('fact') or ''}".lower()
    if any(token in blob for token in ("capex", "guidance", "earnings", "order", "demand", "customer")):
        return False
    return True
