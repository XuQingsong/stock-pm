#!/usr/bin/env python3
"""Brain Integrity golden dump for AAPL / AVGO / LITE. Two runs per ticker."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore

OUT = Path("artifacts/brain_integrity")
TICKERS = ("AAPL", "AVGO", "LITE")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)


def _brief_ev(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "source_relationship": row.get("source_relationship"),
        "source_tier": row.get("source_tier"),
        "fact": (row.get("fact") or "")[:240],
        "excerpt": (row.get("excerpt") or row.get("fact") or "")[:240],
    }


def _claim_card(claim: dict, store: BrainStore, evidence_index: dict) -> dict:
    links = store.list_links(claim_id=claim["claim_id"])
    current_vid = claim.get("current_version_id")
    if current_vid and any(link.get("claim_version_id") == current_vid for link in links):
        links = [link for link in links if link.get("claim_version_id") == current_vid]
    versions = store.list_versions(claim["claim_id"])
    counter = claim.get("counter_search") or {}
    return {
        "claim_key": claim.get("claim_key"),
        "claim_id": claim.get("claim_id"),
        "title": claim.get("title"),
        "statement": claim.get("statement"),
        "proposed_status": claim.get("proposed_status"),
        "final_status": claim.get("final_status") or claim.get("status"),
        "confidence": claim.get("confidence"),
        "lifecycle": claim.get("lifecycle"),
        "claim_subject": claim.get("claim_subject"),
        "claim_dimension": claim.get("claim_dimension"),
        "financial_driver": claim.get("financial_driver"),
        "why_core": claim.get("why_core"),
        "unverified_detail": claim.get("unverified_detail"),
        "reconciliation_reason": claim.get("reconciliation_reason"),
        "match_action": claim.get("match_action"),
        "support_evidence": [
            {
                **(_brief_ev(evidence_index.get(str(link.get("evidence_id")))) or {"id": link.get("evidence_id")}),
                "direction": link.get("direction"),
                "strength": link.get("strength"),
                "relevance": link.get("relevance"),
                "source_relationship": link.get("source_relationship"),
                "reason": link.get("reason"),
                "proves": link.get("proves"),
                "does_not_prove": link.get("does_not_prove"),
                "incomplete": link.get("incomplete"),
            }
            for link in links
            if link.get("direction") == "support"
        ],
        "counter_evidence": [
            {
                **(_brief_ev(evidence_index.get(str(link.get("evidence_id")))) or {"id": link.get("evidence_id")}),
                "direction": link.get("direction"),
                "strength": link.get("strength"),
                "relevance": link.get("relevance"),
                "source_relationship": link.get("source_relationship"),
                "reason": link.get("reason"),
                "proves": link.get("proves"),
                "does_not_prove": link.get("does_not_prove"),
            }
            for link in links
            if link.get("direction") == "oppose"
        ],
        "missing_evidence": (claim.get("reasoning") or {}).get("missing_evidence") or claim.get("missing_evidence") or [],
        "evidence_links": [
            {
                "evidence_id": link.get("evidence_id"),
                "direction": link.get("direction"),
                "strength": link.get("strength"),
                "relevance": link.get("relevance"),
                "source_relationship": link.get("source_relationship"),
                "reason": link.get("reason"),
                "proves": link.get("proves"),
                "does_not_prove": link.get("does_not_prove"),
            }
            for link in links
        ],
        "counter_search": {
            "queries": counter.get("counter_queries") or [],
            "performed": counter.get("counter_search_performed"),
            "results": counter.get("results") or [],
            "counter_evidence_found": counter.get("counter_evidence_found"),
            "counter_evidence_ids": counter.get("counter_evidence_ids") or [],
        },
        "versions": [
            {
                "version": row.get("version"),
                "old_status": row.get("old_status"),
                "new_status": row.get("new_status") or row.get("status"),
                "old_statement": row.get("old_statement"),
                "new_statement": row.get("new_statement") or row.get("statement"),
                "reason_for_change": row.get("reason_for_change"),
                "run_id": row.get("run_id"),
            }
            for row in versions
        ],
    }


def _candidates(store: BrainStore, ticker: str, run_id: str | None) -> list[dict]:
    rows = store.list_candidates(ticker, run_id=run_id)
    return [
        {
            "title": row.get("title"),
            "statement": row.get("statement"),
            "selected_as_core": row.get("selected_as_core"),
            "why_core": row.get("why_core"),
            "why_not_core": row.get("why_not_core"),
            "claim_id": row.get("claim_id"),
        }
        for row in rows
    ]


def _annotate_evidence(research, frozen_rows: list[dict]) -> dict:
    index = {str(row.get("id")): dict(row) for row in (research.store.list_evidence(frozen_rows and frozen_rows[0].get("ticker") or "") or []) if row.get("id")}
    # fallback: use whatever list_evidence of the ticker caller passes separately
    return index


def dump_ticker(ticker: str, result: dict, research, store: BrainStore) -> dict:
    evidence_rows = list(research.store.list_evidence(ticker) or [])
    evidence_index = {str(row.get("id")): row for row in evidence_rows if row.get("id")}
    frozen = (result.get("audit") or {})
    claims = [_claim_card(claim, store, evidence_index) for claim in (result.get("claims") or [])]
    run = result.get("run") or {}
    return {
        "ticker": ticker,
        "generated_at": _now(),
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "prompt_version": run.get("prompt_version") or (result.get("audit") or {}).get("prompt_version"),
        "evidence_set_id": result.get("evidence_set_id") or (result.get("audit") or {}).get("evidence_set_id"),
        "core_claims": claims,
        "candidates": _candidates(store, ticker, run.get("run_id")),
        "pm_consistency": result.get("pm_consistency") or (result.get("pm_synthesis") or {}).get("pm_consistency"),
        "pm_status": (result.get("pm_synthesis") or {}).get("status"),
        "pm_view": (result.get("pm_synthesis") or {}).get("current_view"),
        "integrity_violations": result.get("integrity_violations") or (result.get("audit") or {}).get("integrity_violations") or [],
        "quality": result.get("quality"),
        "claim_versions_changed": (result.get("audit") or {}).get("claim_versions_changed"),
    }


def main() -> None:
    os.environ.setdefault("RESEARCH_BACKFILL_TIMEOUT_SECONDS", "300")
    settings = Settings()
    db = Database(settings)
    research = ResearchService(ResearchStore(db), completer=SettingsCompleter(settings))
    store = BrainStore(db)
    completer = SettingsCompleter(settings)

    first_runs: dict[str, dict] = {}
    second_runs: dict[str, dict] = {}
    version_demo: dict[str, dict] = {}

    for ticker in TICKERS:
        print("brain integrity run 1", ticker, flush=True)
        first = run_brain(research, ticker, store=store, completer=completer, fetch_live=True)
        first_dump = dump_ticker(ticker, first, research, store)
        first_runs[ticker] = first_dump
        _write(f"{ticker.lower()}_run1.json", first_dump)

        print("brain integrity run 2", ticker, flush=True)
        second = run_brain(research, ticker, store=store, completer=completer, fetch_live=True)
        second_dump = dump_ticker(ticker, second, research, store)
        second_runs[ticker] = second_dump
        _write(f"{ticker.lower()}_run2.json", second_dump)

        first_ids = {row["claim_key"]: row["claim_id"] for row in first_dump["core_claims"] if row.get("claim_key")}
        second_ids = {row["claim_key"]: row["claim_id"] for row in second_dump["core_claims"] if row.get("claim_key")}
        shared = sorted(set(first_ids) & set(second_ids))
        version_demo[ticker] = {
            "shared_claim_keys": shared,
            "same_claim_id": all(first_ids[key] == second_ids[key] for key in shared) if shared else False,
            "pairs": [
                {
                    "claim_key": key,
                    "run1_claim_id": first_ids[key],
                    "run2_claim_id": second_ids[key],
                    "same_id": first_ids[key] == second_ids[key],
                    "run1_versions": len(next((row["versions"] for row in first_dump["core_claims"] if row.get("claim_key") == key), [])),
                    "run2_versions": len(next((row["versions"] for row in second_dump["core_claims"] if row.get("claim_key") == key), [])),
                    "run2_versions_changed": second_dump.get("claim_versions_changed"),
                }
                for key in shared
            ],
            "run1_new_ids": sorted(set(first_ids.values())),
            "run2_ids": sorted(set(second_ids.values())),
        }

    acceptance = {
        "generated_at": _now(),
        "prompt_version": "brain-integrity-v1",
        "core_claims": {ticker: second_runs[ticker]["core_claims"] for ticker in TICKERS},
        "candidates": {ticker: second_runs[ticker]["candidates"] for ticker in TICKERS},
        "pm_consistency": {ticker: {"passed": (second_runs[ticker].get("pm_consistency") or {}).get("passed"), "status": second_runs[ticker].get("pm_status"), "reasons": (second_runs[ticker].get("pm_consistency") or {}).get("reasons"), "view": second_runs[ticker].get("pm_view")} for ticker in TICKERS},
        "integrity_violations": {ticker: second_runs[ticker].get("integrity_violations") or [] for ticker in TICKERS},
        "claim_version_demo": version_demo,
        "run1_ids": {ticker: [row.get("claim_id") for row in first_runs[ticker]["core_claims"]] for ticker in TICKERS},
        "run2_ids": {ticker: [row.get("claim_id") for row in second_runs[ticker]["core_claims"]] for ticker in TICKERS},
    }
    _write("acceptance.json", acceptance)
    _write("version_demo.json", version_demo)
    print("done", flush=True)


if __name__ == "__main__":
    main()
