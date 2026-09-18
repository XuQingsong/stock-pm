"""Freeze one Brain input pack per ticker. No live search."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from stock_pm.brain.llm_steps import compact_evidence_rows
from stock_pm.research.llm_reason import compact_text


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _claim_card(claim: dict[str, Any]) -> dict[str, Any]:
    reasoning = claim.get("reasoning") if isinstance(claim.get("reasoning"), dict) else {}
    return {
        "claim_id": claim.get("claim_id"),
        "claim_key": claim.get("claim_key"),
        "title": claim.get("title"),
        "statement": claim.get("statement"),
        "final_status": claim.get("final_status") or claim.get("status"),
        "confidence": claim.get("confidence"),
        "claim_subject": claim.get("claim_subject"),
        "claim_dimension": claim.get("claim_dimension"),
        "financial_driver": claim.get("financial_driver"),
        "why_core": claim.get("why_core"),
        "unverified_detail": claim.get("unverified_detail"),
        "missing_evidence": reasoning.get("missing_evidence") or claim.get("missing_evidence") or [],
        "supporting_evidence_ids": claim.get("supporting_evidence_ids") or [],
        "opposing_evidence_ids": claim.get("opposing_evidence_ids") or [],
    }


def freeze_from_store(store: Any, research: Any, ticker: str) -> dict[str, Any] | None:
    symbol = str(ticker or "").upper()
    run = store.latest_run(symbol) if store else None
    if not run:
        return None
    audit = run.get("audit") or {}
    run_id = run.get("run_id")
    frozen_row = store.latest_evidence_set(symbol, run_id=run_id) if hasattr(store, "latest_evidence_set") else None
    if not frozen_row:
        frozen_row = store.latest_evidence_set(symbol) if hasattr(store, "latest_evidence_set") else None
    payload = (frozen_row or {}).get("payload") if isinstance(frozen_row, dict) else {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    payload = payload or {}
    rows = list(payload.get("reasoning_rows") or payload.get("rows") or [])
    allowed = list(payload.get("reasoning_allowed_ids") or [str(row.get("id")) for row in rows if row.get("id")])
    claims = []
    if store:
        listed = store.list_claims(symbol, run_id=run_id, core_only=True) or store.list_claims(symbol, core_only=True)
        claims = [_claim_card(row) for row in listed if row.get("is_core")][:5]
    facts = compact_evidence_rows(rows, limit=40)
    pack = {
        "ticker": symbol,
        "snapshot_id": run.get("snapshot_id") or audit.get("snapshot_id"),
        "run_id": run_id,
        "evidence_set_id": (frozen_row or {}).get("evidence_set_id") or audit.get("evidence_set_id") or payload.get("evidence_set_id"),
        "header": run.get("header") or {},
        "related_entities": audit.get("related_entities") or payload.get("related_entities") or [],
        "core_claims": claims,
        "validated_facts": facts,
        "evidence": facts,
        "allowed_evidence_ids": sorted({str(item) for item in allowed if item}),
        "brain_context": audit.get("brain_context") or (payload.get("brain_context") if isinstance(payload, dict) else None),
    }
    pack["input_hash"] = _hash(
        {
            "ticker": pack["ticker"],
            "snapshot_id": pack["snapshot_id"],
            "evidence_set_id": pack["evidence_set_id"],
            "related_entities": pack["related_entities"],
            "core_claims": pack["core_claims"],
            "validated_facts": pack["validated_facts"],
            "allowed_evidence_ids": pack["allowed_evidence_ids"],
        }
    )
    return pack


def freeze_from_artifact(ticker: str, path: Path | None = None) -> dict[str, Any] | None:
    symbol = str(ticker or "").upper()
    target = path or Path("artifacts/brain_integrity") / f"{symbol.lower()}_run2.json"
    if not target.exists():
        return None
    raw = json.loads(target.read_text(encoding="utf-8"))
    claims = []
    for row in raw.get("core_claims") or []:
        claims.append(
            {
                "claim_id": row.get("claim_id"),
                "claim_key": row.get("claim_key"),
                "title": row.get("title"),
                "statement": row.get("statement"),
                "final_status": row.get("final_status"),
                "confidence": row.get("confidence"),
                "claim_subject": row.get("claim_subject"),
                "claim_dimension": row.get("claim_dimension"),
                "financial_driver": row.get("financial_driver"),
                "why_core": row.get("why_core"),
                "unverified_detail": row.get("unverified_detail"),
                "missing_evidence": row.get("missing_evidence") or [],
                "supporting_evidence_ids": [
                    str(item.get("id") or item.get("evidence_id"))
                    for item in (row.get("support_evidence") or row.get("evidence_links") or [])
                    if item.get("id") or item.get("evidence_id")
                ],
                "opposing_evidence_ids": [
                    str(item.get("id") or item.get("evidence_id"))
                    for item in (row.get("counter_evidence") or [])
                    if item.get("id") or item.get("evidence_id")
                ],
            }
        )
    facts = []
    seen: set[str] = set()
    for claim in raw.get("core_claims") or []:
        for ev in (claim.get("support_evidence") or []) + (claim.get("counter_evidence") or []):
            eid = str(ev.get("id") or "")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            facts.append(
                {
                    "id": eid,
                    "fact": compact_text(ev.get("fact") or ev.get("excerpt"), 360),
                    "excerpt": compact_text(ev.get("excerpt") or ev.get("fact"), 240),
                    "source": ev.get("source"),
                    "source_url": ev.get("source_url"),
                    "source_relationship": ev.get("source_relationship"),
                }
            )
    pack = {
        "ticker": symbol,
        "snapshot_id": raw.get("run_id"),
        "run_id": raw.get("run_id"),
        "evidence_set_id": raw.get("evidence_set_id"),
        "header": {
            "ticker": symbol,
            "run_id": raw.get("run_id"),
            "evidence_set_id": raw.get("evidence_set_id"),
            "status": raw.get("status"),
            "prompt_version": raw.get("prompt_version"),
        },
        "related_entities": list(raw.get("related_entities") or []),
        "core_claims": claims,
        "validated_facts": facts,
        "evidence": facts,
        "allowed_evidence_ids": sorted(seen),
        "source": str(target),
    }
    pack["input_hash"] = _hash(
        {
            "ticker": pack["ticker"],
            "snapshot_id": pack["snapshot_id"],
            "evidence_set_id": pack["evidence_set_id"],
            "related_entities": pack["related_entities"],
            "core_claims": pack["core_claims"],
            "validated_facts": pack["validated_facts"],
            "allowed_evidence_ids": pack["allowed_evidence_ids"],
        }
    )
    return pack


def compact_mini_pack(pack: dict[str, Any], *, fact_limit: int = 8, excerpt_width: int = 180) -> dict[str, Any]:
    """Shrink a frozen pack for Mini Benchmark prompts. Does not re-search."""
    evidence = []
    for row in pack.get("validated_facts") or pack.get("evidence") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        evidence.append(
            {
                "id": str(row.get("id")),
                "fact": compact_text(row.get("fact") or row.get("excerpt") or "", excerpt_width),
                "source": compact_text(row.get("source") or "", 40),
            }
        )
        if len(evidence) >= fact_limit:
            break
    related = []
    for item in pack.get("related_entities") or []:
        if isinstance(item, dict):
            text = compact_text(item.get("name") or item.get("ticker") or item.get("id") or "", 40)
        else:
            text = compact_text(item, 40)
        if text and text not in related:
            related.append(text)
        if len(related) >= 8:
            break
    compact = {
        "ticker": pack.get("ticker"),
        "snapshot_id": pack.get("snapshot_id"),
        "evidence_set_id": pack.get("evidence_set_id"),
        "run_id": pack.get("run_id"),
        "freeze_hash": pack.get("input_hash"),
        "related_entities": related,
        "evidence": evidence,
        "allowed_evidence_ids": [row["id"] for row in evidence],
    }
    compact["prompt_input_hash"] = _hash(
        {
            "ticker": compact["ticker"],
            "snapshot_id": compact["snapshot_id"],
            "evidence_set_id": compact["evidence_set_id"],
            "related_entities": compact["related_entities"],
            "evidence": compact["evidence"],
            "allowed_evidence_ids": compact["allowed_evidence_ids"],
        }
    )
    return compact


def freeze_benchmark_input(store: Any, research: Any, ticker: str) -> dict[str, Any]:
    pack = freeze_from_store(store, research, ticker)
    if pack and pack.get("allowed_evidence_ids"):
        return pack
    artifact = freeze_from_artifact(ticker)
    if artifact:
        return artifact
    raise RuntimeError(f"No frozen Brain input for {ticker}. Run Brain first.")
