"""Read-only assembly of the stock judgment card.

Never writes to the database, never calls an LLM, and never invents a
direction / window / bound when a stored prediction is missing or gated.
"""

from __future__ import annotations

from typing import Any, Callable

from .analytics import _number
from .evidence import (
    COMPLETE,
    INCOMPLETE_LABEL,
    MISSING,
    MODEL_VERSION,
    PARTIAL,
    analysis_ref,
    fact_ref,
    public_evidence,
)
from .prediction import (
    GATE_ANALYSIS_ABSTAIN,
    GATE_BOUNDS_TOO_TIGHT,
    GATE_LABELS,
    GATE_PREMISE_MISSING,
    KIND_LABEL,
    STATE_LABELS,
    diagnose_quality_gate,
    has_real_bounds,
)
from .tape import env_tape_conflict_sentence
from .ux_copy import is_http_url


NO_STORED_LABEL = "尚未落库判断，未编造方向、时间窗或涨跌数字。"
ABSTAIN_LABEL = GATE_LABELS[GATE_ANALYSIS_ABSTAIN]
INTERNAL_MARKERS = ("诱多", "逃跑", "吸筹", "转势", "补涨", "续涨")


def public_reason_text(text: str | None) -> str | None:
    """Keep rule jargon off the default judgment card."""
    if not text:
        return None
    cleaned = str(text)
    for marker in INTERNAL_MARKERS:
        cleaned = cleaned.replace(f"{marker}（推断）", "")
        cleaned = cleaned.replace(f"推断：{marker}", "对照后未形成方向")
        cleaned = cleaned.replace(marker, "")
    cleaned = "，".join(part for part in (bit.strip(" ，；") for bit in cleaned.split("，")) if part)
    return cleaned or None


def _as_of(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:10] if text else None


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    number = abs(float(value))
    return f"{number:.0f}%" if number == int(number) else f"{number:.1f}%"


def _gate_payload(
    *,
    reason: str | None,
    label: str,
    missing_flags: list[str] | None = None,
    detail: str | None = None,
) -> dict:
    return {
        "reason": reason,
        "label": label,
        "missingFlags": list(missing_flags or []),
        "detail": detail,
    }


def diagnose_from_stored(
    *,
    prediction: dict | None,
    environment: dict | None,
    tape: dict | None,
    review_note: dict | None,
    as_of_date: str | None,
    daily_review: dict | None = None,
) -> dict:
    """Explain a stored row. Does not invent bounds."""
    pred = prediction or {}
    if has_real_bounds(pred):
        return {
            "gate_reason": pred.get("gate_reason") or (pred.get("struct") or {}).get("gate_reason"),
            "missingFlags": [],
            "label": None,
            "tight": (pred.get("struct") or {}).get("tight") or [],
            "ready": True,
        }
    chips = (tape or {}).get("chips") or {}
    entry = (
        _number(pred.get("entry_price"))
        or _number(chips.get("close"))
        or _number((daily_review or {}).get("close_price"))
    )
    support = _number(chips.get("support"))
    resistance = _number(chips.get("resistance"))
    diagnosed = diagnose_quality_gate(
        environment=environment,
        tape=tape,
        review_note=review_note,
        entry_price=entry,
        support=support,
        resistance=resistance,
        as_of_date=as_of_date or pred.get("as_of_date"),
    )
    stored_reason = pred.get("gate_reason") or (pred.get("struct") or {}).get("gate_reason")
    if stored_reason in {GATE_PREMISE_MISSING, GATE_BOUNDS_TOO_TIGHT, GATE_ANALYSIS_ABSTAIN}:
        if diagnosed["gate_reason"] is None or stored_reason == diagnosed["gate_reason"]:
            pass
    return diagnosed


def _analysis_from(
    row: dict | None,
    *,
    table: str,
    text: str | None,
    based_on: list[dict],
    role: str,
) -> dict | None:
    if not row:
        return None
    clause = public_reason_text(
        text or row.get("one_liner") or row.get("summary") or row.get("thesis")
    )
    if not clause:
        return None
    return analysis_ref(
        ref_table=table,
        ref_id=row.get("id"),
        as_of=row.get("as_of_date") or row.get("review_date"),
        text=clause,
        based_on=based_on,
        role=role,
    )


def _fact_from_candidate(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return None
    if item.get("layer") != "fact":
        return None
    if item.get("ref_id") in (None, "", False):
        return None
    built = fact_ref(
        ref_table=str(item.get("ref_table") or ""),
        ref_id=item.get("ref_id"),
        as_of=item.get("as_of"),
        text=item.get("text"),
        source_name=item.get("source_name"),
        source_url=item.get("source_url") if is_http_url(item.get("source_url")) else None,
        completeness=item.get("completeness") or COMPLETE,
        role=item.get("role"),
    )
    return built


def _unique(items: list[dict]) -> list[dict]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict] = []
    for item in items:
        key = (
            item.get("layer"),
            item.get("ref_table"),
            item.get("ref_id"),
            item.get("as_of"),
            item.get("role"),
            item.get("text"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _conflict_item(environment: dict | None, tape: dict | None) -> dict | None:
    env = environment or {}
    tape_row = tape or {}
    if not (env.get("conflict") or tape_row.get("conflict")):
        return None
    sentence = env_tape_conflict_sentence(env, tape_row)
    based_on: list[dict] = []
    return analysis_ref(
        ref_table="tape_analyses" if tape_row.get("id") else "environment_snapshots",
        ref_id=tape_row.get("id") or env.get("id"),
        as_of=tape_row.get("as_of_date") or env.get("as_of_date"),
        text=sentence or "环境与昨盘方向不一致",
        based_on=based_on,
        completeness=PARTIAL,
        role="counter",
    )


def _invalidation_from(pred: dict | None) -> list[dict]:
    if not has_real_bounds(pred):
        return []
    items = []
    down = _number(pred.get("downside_price"))
    up = _number(pred.get("upside_price"))
    window_end = pred.get("window_end")
    if down is not None:
        items.append(
            {
                "kind": "downside_break",
                "text": f"期间低点跌破 {_price(down)}，区间假设失效",
            }
        )
    if window_end and up is not None:
        items.append(
            {
                "kind": "window_expiry",
                "text": (
                    f"窗口到期（{window_end}）仍未触及 {_price(up)}"
                    f"（约{_pct(pred.get('upside_bound_pct'))}），区间假设失效"
                ),
            }
        )
    return items


def _judgment_block(pred: dict | None, diagnosed: dict) -> dict:
    if has_real_bounds(pred):
        window = pred.get("window_label") or "窗口"
        line = (
            f"{window}上沿约{_pct(pred.get('upside_bound_pct'))}"
            f"，下沿约{_pct(pred.get('downside_bound_pct'))}"
        )
        return {
            "kind": "range_hypothesis",
            "kind_label": KIND_LABEL,
            "state": pred.get("state"),
            "state_label": pred.get("state_label") or STATE_LABELS.get(pred.get("state") or "", ""),
            "as_of_date": pred.get("as_of_date"),
            "id": pred.get("id"),
            "one_liner": f"区间假设：{line}。",
            "thesis": pred.get("thesis"),
            "window_start": pred.get("window_start"),
            "window_end": pred.get("window_end"),
            "window_label": pred.get("window_label"),
            "entry_price": pred.get("entry_price"),
            "upside_bound_pct": pred.get("upside_bound_pct"),
            "downside_bound_pct": pred.get("downside_bound_pct"),
            "upside_price": pred.get("upside_price"),
            "downside_price": pred.get("downside_price"),
            "prediction_ready": True,
        }
    reason = diagnosed.get("gate_reason") or GATE_PREMISE_MISSING
    label = diagnosed.get("label") or NO_STORED_LABEL
    return {
        "kind": "range_hypothesis",
        "kind_label": KIND_LABEL,
        "state": "missing",
        "state_label": STATE_LABELS["missing"],
        "as_of_date": (pred or {}).get("as_of_date"),
        "id": (pred or {}).get("id"),
        "one_liner": label,
        "thesis": label,
        "window_start": None,
        "window_end": None,
        "window_label": None,
        "entry_price": None,
        "upside_bound_pct": None,
        "downside_bound_pct": None,
        "upside_price": None,
        "downside_price": None,
        "prediction_ready": False,
    }


def assemble_judgment(
    *,
    symbol: str,
    as_of_date: str | None,
    prediction: dict | None = None,
    environment: dict | None = None,
    tape: dict | None = None,
    review_note: dict | None = None,
    daily_review: dict | None = None,
    resolved_facts: list[dict] | None = None,
    generated_at: str | None = None,
    model_version: str = MODEL_VERSION,
) -> dict:
    """Assemble a judgment payload from already-persisted objects only."""
    facts = [_fact_from_candidate(item) for item in (resolved_facts or [])]
    facts = _unique([item for item in facts if item])
    fact_by_role = {item.get("role"): item for item in facts if item.get("role")}

    def facts_for(*roles: str) -> list[dict]:
        return [fact_by_role[role] for role in roles if role in fact_by_role]

    reasons: list[dict] = []
    env_reason = _analysis_from(
        environment,
        table="environment_snapshots",
        text=(environment or {}).get("one_liner") or (environment or {}).get("synthesis"),
        based_on=facts_for("price", "earnings", "news", "macro"),
        role="environment",
    )
    tape_clause = (
        ((tape or {}).get("volume_price") or {}).get("clause")
        or (tape or {}).get("one_liner")
    )
    tape_reason = _analysis_from(
        tape,
        table="tape_analyses",
        text=tape_clause,
        based_on=facts_for("price"),
        role="tape",
    )
    note_text = (review_note or {}).get("summary")
    explanation = (review_note or {}).get("explanation") or ""
    if explanation and not any(marker in explanation for marker in INTERNAL_MARKERS):
        note_text = explanation
    note_reason = _analysis_from(
        review_note,
        table="review_notes",
        text=note_text,
        based_on=facts_for("price", "news"),
        role="review_note",
    )
    review_reason = None
    if daily_review:
        review_reason = _analysis_from(
            daily_review,
            table="daily_reviews",
            text=daily_review.get("summary"),
            based_on=facts_for("price"),
            role="daily_review",
        )
    for item in (env_reason, tape_reason, note_reason, review_reason):
        if item:
            reasons.append(item)

    stored = prediction
    if stored is None:
        gate = _gate_payload(reason="missing", label=NO_STORED_LABEL)
        judgment = {
            "kind": "range_hypothesis",
            "kind_label": KIND_LABEL,
            "state": "missing",
            "state_label": STATE_LABELS["missing"],
            "as_of_date": as_of_date,
            "id": None,
            "one_liner": NO_STORED_LABEL,
            "thesis": NO_STORED_LABEL,
            "window_start": None,
            "window_end": None,
            "window_label": None,
            "entry_price": None,
            "upside_bound_pct": None,
            "downside_bound_pct": None,
            "upside_price": None,
            "downside_price": None,
            "prediction_ready": False,
        }
        completeness = MISSING
    else:
        diagnosed = diagnose_from_stored(
            prediction=stored,
            environment=environment,
            tape=tape,
            review_note=review_note,
            as_of_date=as_of_date,
            daily_review=daily_review,
        )
        judgment = _judgment_block(stored, diagnosed)
        if has_real_bounds(stored):
            gate = _gate_payload(reason=None, label="已形成区间假设", missing_flags=[])
        else:
            gate = _gate_payload(
                reason=diagnosed.get("gate_reason") or GATE_PREMISE_MISSING,
                label=diagnosed.get("label") or NO_STORED_LABEL,
                missing_flags=diagnosed.get("missingFlags") or [],
                detail=";".join(
                    str(item.get("message") or "")
                    for item in (diagnosed.get("tight") or [])
                    if item.get("message")
                )
                or None,
            )
        completeness = COMPLETE if reasons and facts and has_real_bounds(stored) else PARTIAL

    if not facts and reasons:
        completeness = PARTIAL
        for item in reasons:
            if item.get("completeness") == COMPLETE:
                item["completeness"] = PARTIAL
                text = item.get("text") or ""
                if INCOMPLETE_LABEL not in text:
                    item["text"] = f"{text}（{INCOMPLETE_LABEL}）" if text else INCOMPLETE_LABEL

    counter = []
    conflict = _conflict_item(environment, tape)
    if conflict:
        counter.append(conflict)

    snapshot_parts = []
    for prefix, row in (
        ("p", stored),
        ("e", environment),
        ("t", tape),
        ("n", review_note),
    ):
        if row and row.get("id") is not None:
            snapshot_parts.append(f"{prefix}{row['id']}")
    data_snapshot_id = ":".join(snapshot_parts) or None

    return {
        "symbol": symbol.upper(),
        "as_of_date": as_of_date,
        "judgment": judgment,
        "reasons": [public_evidence(item) for item in reasons if public_evidence(item)],
        "facts": [public_evidence(item) for item in facts if public_evidence(item)],
        "counter_evidence": [public_evidence(item) for item in counter if public_evidence(item)],
        "invalidation": _invalidation_from(stored if has_real_bounds(stored) else None),
        "gate": gate,
        "generated_at": generated_at or (stored or {}).get("created_at"),
        "model_version": model_version,
        "data_snapshot_id": data_snapshot_id,
        "completeness": completeness,
    }


FactLookup = Callable[[str, Any, str | None, str | None], dict | None]
