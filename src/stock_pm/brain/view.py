"""Read-only Brain page payload. No invented numbers."""

from __future__ import annotations

from typing import Any

from .quality import assess_brain_quality


def _evidence_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _brief_evidence(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "fact": row.get("fact"),
        "excerpt": row.get("excerpt") or row.get("fact"),
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "source_time": row.get("source_time"),
        "source_type": row.get("source_type"),
        "source_quality": row.get("source_quality"),
        "independence_key": row.get("independence_key"),
        "evidence_family": (row.get("raw_reference") or {}).get("evidence_side") if isinstance(row.get("raw_reference"), dict) else row.get("source_type"),
    }


def build_brain_view(
    store: Any,
    research: Any,
    ticker: str,
    *,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = ticker.upper()
    latest = run or store.latest_run(symbol)
    pack = research.get_pack(symbol) if research else {}
    evidence_rows = research.store.list_evidence(symbol) if research else []
    evidence_index = _evidence_map(evidence_rows)
    if not latest:
        return {
            "ticker": symbol,
            "status": "missing",
            "run": None,
            "header": {"ticker": symbol},
            "quality": {
                "axes": {
                    "data_coverage": "Poor",
                    "news_coverage": "Poor",
                    "evidence_quality": "Poor",
                    "independent_evidence": "Poor",
                    "llm_reasoning": "Poor",
                    "freshness": "Poor",
                },
                "warnings": [
                    {
                        "code": "BRAIN QUALITY WARNING",
                        "axis": "LLM Reasoning",
                        "reason": "No Brain run exists yet. POST /api/brain/%s/runs to execute Phase 1." % symbol,
                    }
                ],
                "poor_axes": ["llm_reasoning"],
            },
            "core_claims": [],
            "news": [],
            "pm": {},
            "pack_present": bool(pack),
        }
    run_id = latest.get("run_id")
    claims = store.list_claims(symbol, run_id=run_id, core_only=False)
    core = [row for row in claims if row.get("is_core")][:5]
    cards = []
    for claim in core:
        links = store.list_links(claim_id=claim["claim_id"])
        support = [link for link in links if link.get("direction") == "support"]
        oppose = [link for link in links if link.get("direction") == "oppose"]
        support_ev = [_brief_evidence(evidence_index.get(str(link.get("evidence_id")))) for link in support[:3]]
        oppose_ev = [_brief_evidence(evidence_index.get(str(link.get("evidence_id")))) for link in oppose[:1]]
        versions = store.list_versions(claim["claim_id"])
        reasoning = claim.get("reasoning") or {}
        cards.append(
            {
                "claim_id": claim.get("claim_id"),
                "title": claim.get("title"),
                "statement": claim.get("statement"),
                "status": claim.get("status"),
                "confidence": claim.get("confidence"),
                "importance": claim.get("importance"),
                "time_horizon": claim.get("time_horizon"),
                "why_it_matters": claim.get("why_it_matters"),
                "financial_driver": claim.get("financial_driver"),
                "conclusion": (reasoning.get("current_conclusion") if isinstance(reasoning, dict) else None) or claim.get("statement"),
                "support_evidence": [item for item in support_ev if item],
                "opposing_evidence": [item for item in oppose_ev if item],
                "missing_evidence": (reasoning.get("missing_evidence") if isinstance(reasoning, dict) else None) or [],
                "changed": len(versions) > 1,
                "version_count": len(versions),
            }
        )
    news = store.list_news(symbol, run_id=run_id)
    material = [row for row in news if row.get("layer") == "material"]
    quality = assess_brain_quality(
        header=latest.get("header") or {},
        evidence=evidence_rows,
        news=news,
        claims=core,
        llm_calls=(latest.get("audit") or {}).get("llm_calls") or latest.get("llm_calls") or [],
        pack=pack,
    )
    stored_quality = latest.get("quality") or {}
    if stored_quality.get("warnings"):
        seen = {(item.get("axis"), item.get("reason")) for item in quality.get("warnings") or []}
        for item in stored_quality["warnings"]:
            key = (item.get("axis"), item.get("reason"))
            if key not in seen:
                quality.setdefault("warnings", []).append(item)
                seen.add(key)
    pm = latest.get("pm_synthesis") or {}
    return {
        "ticker": symbol,
        "status": latest.get("status"),
        "run_id": run_id,
        "snapshot_id": latest.get("snapshot_id"),
        "model": latest.get("model"),
        "prompt_version": latest.get("prompt_version"),
        "header": latest.get("header") or {},
        "quality": quality,
        "company_understanding": latest.get("company_understanding") or {},
        "pm": {
            "current_view": pm.get("current_view"),
            "decisive_variables": (pm.get("decisive_variables") or [])[:3],
            "strongest_claim_id": pm.get("strongest_claim_id"),
            "weakest_claim_id": pm.get("weakest_claim_id"),
            "what_changed_last_7d": pm.get("what_changed_last_7d") or [],
            "most_likely_wrong": pm.get("most_likely_wrong"),
            "next_information_to_seek": pm.get("next_information_to_seek"),
            "short_view": pm.get("short_view"),
            "mid_view": pm.get("mid_view"),
            "long_view": pm.get("long_view"),
            "cannot_conclude": pm.get("cannot_conclude") or [],
        },
        "core_claims": cards,
        "news": material,
        "news_all": news,
        "states": store.list_states(symbol, run_id=run_id),
        "questions": store.list_questions(symbol, run_id=run_id),
        "audit": latest.get("audit") or {},
        "warnings": latest.get("warnings") or (latest.get("quality") or {}).get("warnings") or [],
        "created_at": latest.get("created_at"),
        "completed_at": latest.get("completed_at"),
    }


def build_claim_detail(store: Any, research: Any, ticker: str, claim_id: str) -> dict[str, Any] | None:
    claim = store.get_claim(claim_id)
    if not claim or str(claim.get("ticker") or "").upper() != ticker.upper():
        return None
    evidence_index = _evidence_map(research.store.list_evidence(ticker) if research else [])
    links = store.list_links(claim_id=claim_id)
    def _bundle(direction: str) -> list[dict[str, Any]]:
        out = []
        for link in links:
            if link.get("direction") != direction:
                continue
            ev = _brief_evidence(evidence_index.get(str(link.get("evidence_id")))) or {"id": link.get("evidence_id")}
            ev = dict(ev)
            ev["link"] = {
                "direction": link.get("direction"),
                "strength": link.get("strength"),
                "relevance": link.get("relevance"),
                "reason": link.get("reason"),
                "proves": link.get("proves"),
                "does_not_prove": link.get("does_not_prove"),
            }
            out.append(ev)
        return out
    reasoning = claim.get("reasoning") if isinstance(claim.get("reasoning"), dict) else {}
    news = [
        row
        for row in store.list_news(ticker, run_id=claim.get("run_id"))
        if row.get("affected_claim_id") == claim_id or row.get("layer") == "material"
    ]
    return {
        "ticker": ticker.upper(),
        "claim": claim,
        "support_evidence": _bundle("support"),
        "opposing_evidence": _bundle("oppose"),
        "contextual_evidence": _bundle("contextual"),
        "reasoning": reasoning,
        "history": store.list_versions(claim_id),
        "questions": [row for row in store.list_questions(ticker, run_id=claim.get("run_id")) if row.get("related_claim_id") == claim_id],
        "news": news,
    }


def build_evidence_detail(store: Any, research: Any, ticker: str, evidence_id: str) -> dict[str, Any] | None:
    row = research.store.get_evidence(evidence_id) if research else None
    if not row:
        return None
    if str(row.get("ticker") or "").upper() != ticker.upper():
        return None
    links = store.list_links(evidence_id=evidence_id)
    claims = []
    for link in links:
        claim = store.get_claim(str(link.get("claim_id")))
        if claim:
            claims.append(
                {
                    "claim_id": claim.get("claim_id"),
                    "title": claim.get("title"),
                    "direction": link.get("direction"),
                    "proves": link.get("proves"),
                    "does_not_prove": link.get("does_not_prove"),
                }
            )
    return {
        "ticker": ticker.upper(),
        "evidence": _brief_evidence(row),
        "raw_reference": row.get("raw_reference") if isinstance(row.get("raw_reference"), dict) else {},
        "proves": next((link.get("proves") for link in links if link.get("proves")), None),
        "does_not_prove": next((link.get("does_not_prove") for link in links if link.get("does_not_prove")), None),
        "used_by_claims": claims,
        "lineage": {
            "raw_value": None,
            "note": "Financial numbers live on the Research Pack header, not on news evidence rows.",
        },
    }
