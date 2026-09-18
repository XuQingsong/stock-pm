#!/usr/bin/env python3
"""Brain v1 golden dump for AAPL / AVGO / LITE. Does not hardcode answers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from stock_pm.brain.history import why_thesis_changed
from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.routing import layer_settings
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore

OUT = Path("artifacts/brain_v1")
TICKERS = ("AAPL", "AVGO", "LITE")
THEMES = {
    "AAPL": (
        ("services", "regulation", "app store", "dma"),
        ("product", "iphone", "ai cycle", "hardware"),
        ("margin", "mix"),
        ("valuation", "multiple", "growth"),
    ),
    "AVGO": (
        ("ai", "silicon", "asic", "xpu", "custom"),
        ("customer", "hyperscaler", "concentration"),
        ("network", "networking"),
        ("competition", "asic", "internal"),
        ("margin", "mix"),
        ("valuation", "multiple"),
    ),
    "LITE": (
        ("optical", "datacom", "800g", "1.6"),
        ("margin", "cyclical", "structural"),
        ("capacity", "competition"),
        ("customer", "concentration"),
        ("valuation", "multiple"),
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)
    return path


def _blob(rows: list[dict]) -> str:
    parts = []
    for row in rows:
        parts.extend(str(row.get(key) or "") for key in ("name", "canonical_key", "category", "title", "statement", "description", "why_it_matters"))
    return " ".join(parts).lower()


def theme_gaps(ticker: str, drivers: list[dict], claims: list[dict]) -> list[str]:
    hay = _blob(list(drivers) + list(claims))
    missing = []
    for family in THEMES.get(ticker, ()):
        if not any(token in hay for token in family):
            missing.append("|".join(family))
    return missing


def slim_result(ticker: str, result: dict, store: BrainStore) -> dict:
    claims = result.get("claims") or []
    drivers = result.get("drivers") or store.list_drivers(ticker)
    events = result.get("events") or store.list_events(ticker)
    return {
        "ticker": ticker,
        "run_id": (result.get("run") or {}).get("run_id"),
        "status": (result.get("run") or {}).get("status"),
        "prompt_version": (result.get("run") or {}).get("prompt_version"),
        "run_mode": result.get("run_mode"),
        "header": result.get("header"),
        "quality": result.get("quality"),
        "drivers": [
            {
                "driver_id": row.get("driver_id"),
                "canonical_key": row.get("canonical_key"),
                "name": row.get("name"),
                "category": row.get("category"),
                "financial_link": row.get("financial_link"),
                "current_state": row.get("current_state"),
                "importance": row.get("importance"),
                "uncertainty": row.get("uncertainty"),
                "why_it_matters": row.get("why_it_matters"),
                "evidence_ids": row.get("evidence_ids"),
                "related_claim_ids": row.get("related_claim_ids"),
            }
            for row in drivers
        ],
        "core_claims": [
            {
                "claim_id": row.get("claim_id"),
                "claim_key": row.get("claim_key"),
                "title": row.get("title"),
                "statement": row.get("statement"),
                "status": row.get("final_status") or row.get("status"),
                "lifecycle": row.get("lifecycle"),
                "related_driver_ids": row.get("related_driver_ids"),
                "why_it_matters": row.get("why_it_matters"),
            }
            for row in claims
        ],
        "states": result.get("states") or store.list_states(ticker),
        "events": [
            {
                "event_id": row.get("event_id"),
                "event_type": row.get("event_type"),
                "title": row.get("title"),
                "materiality": row.get("materiality"),
                "fingerprint": row.get("fingerprint"),
            }
            for row in events
        ],
        "exposures": result.get("exposures") or store.list_exposures(ticker),
        "transmissions": result.get("transmissions") or [],
        "financial_impacts": result.get("financial_impacts") or store.list_financial_impacts(ticker),
        "critic": result.get("critic") or {},
        "pm_synthesis": result.get("pm_synthesis") or {},
        "history": (result.get("history") or store.list_history(ticker))[-20:],
        "theme_gaps": theme_gaps(ticker, drivers, claims),
        "material_events": [
            {
                "event_id": row.get("event_id"),
                "event_type": row.get("event_type"),
                "title": row.get("title"),
                "materiality": row.get("materiality"),
                "subject": row.get("subject"),
            }
            for row in events
            if str(row.get("materiality") or "") == "material" and not row.get("duplicate")
        ],
        "integrity_violations": result.get("integrity_violations") or [],
        "audit": {
            "llm_invoked": (result.get("audit") or {}).get("llm_invoked"),
            "driver_count": (result.get("audit") or {}).get("driver_count"),
            "core_claim_count": (result.get("audit") or {}).get("core_claim_count"),
            "model": (result.get("audit") or {}).get("model"),
            "input_tokens": (result.get("audit") or {}).get("input_tokens"),
            "output_tokens": (result.get("audit") or {}).get("output_tokens"),
            "fallbacks": (result.get("audit") or {}).get("fallbacks"),
        },
    }


def chain_gaps(payload: dict) -> list[str]:
    gaps: list[str] = []
    status = payload.get("status")
    drivers = payload.get("drivers") or []
    claims = payload.get("core_claims") or []
    states = payload.get("states") or []
    transmissions = payload.get("transmissions") or []
    financial = payload.get("financial_impacts") or []
    pm = payload.get("pm_synthesis") or {}
    ticker = payload.get("ticker")
    if status in {None, "failed"}:
        gaps.append(f"{ticker} run failed")
    if len(drivers) < 5:
        gaps.append(f"{ticker} driver universe too thin ({len(drivers)})")
    if len(claims) < 3:
        gaps.append(f"{ticker} missing core claims ({len(claims)})")
    if not states:
        gaps.append(f"{ticker} state layer empty")
    if not financial:
        gaps.append(f"{ticker} financial impact bridge empty")
    if not pm or pm.get("status") in {None, "failed"}:
        gaps.append(f"{ticker} PM synthesis missing")
    theme = payload.get("theme_gaps") or []
    if theme:
        gaps.append(f"{ticker} theme gaps: {theme}")
        if len(theme) >= max(2, len(THEMES.get(ticker, ())) // 2):
            gaps.append(f"{ticker} systematic driver miss")
    material = payload.get("material_events") or []
    if material and not transmissions:
        gaps.append(f"{ticker} material events without transmission")
    return gaps


def architecture() -> dict:
    settings = Settings()
    mechanical = layer_settings(settings, role="mechanical")
    reasoning = layer_settings(settings, role="reasoning")
    return {
        "version": "brain-v1",
        "chain": [
            "Information",
            "Knowledge",
            "State",
            "Value Driver",
            "Claim",
            "Exposure",
            "Financial Impact",
            "Scenario",
            "Valuation",
            "Thesis",
        ],
        "event_chain": ["New Event", "State", "Company Exposure", "Driver", "Claim", "Scenario then Base"],
        "models": {
            "mechanical": {"provider": mechanical.llm_provider, "model": mechanical.llm_model, "base_url": mechanical.llm_base_url},
            "reasoning": {"provider": reasoning.llm_provider, "model": reasoning.llm_model, "base_url": reasoning.llm_base_url},
            "not_in_production": ["kimi-k3", "deepseek-chat as Brain default"],
        },
        "layers_preserved": [
            "Data Layer",
            "Evidence Set Builder",
            "Brain Integrity",
            "Claim identity/versioning",
            "Counter Search",
            "Existing valuation/research infrastructure",
        ],
        "migrations": [
            "0016_brain_value_drivers.sql",
            "0017_brain_state_event_exposure.sql",
            "0018_brain_financial_scenario.sql",
            "0019_brain_history.sql",
        ],
    }


def acceptance(summary: dict, payloads: dict[str, dict], tests: dict) -> dict:
    transmissions = []
    history_examples = []
    critic_findings = []
    pm = {}
    universes = {}
    claims = {}
    material = {}
    for ticker, payload in payloads.items():
        universes[ticker] = payload.get("drivers") or []
        claims[ticker] = payload.get("core_claims") or []
        material[ticker] = payload.get("material_events") or []
        for row in (payload.get("transmissions") or [])[:3]:
            transmissions.append({"ticker": ticker, **row})
        timeline = why_thesis_changed(payload.get("history") or [])
        if timeline:
            history_examples.append({"ticker": ticker, "timeline": timeline[-8:]})
        critic_findings.append({"ticker": ticker, **(payload.get("critic") or {})})
        pm[ticker] = payload.get("pm_synthesis") or {}
    blocking = [
        item
        for item in summary.get("unresolved_gaps") or []
        if any(token in item for token in ("failed", "too thin", "missing core", "state layer empty", "systematic driver miss"))
    ]
    return {
        "1_architecture": architecture(),
        "2_migrations": architecture()["migrations"],
        "3_tests": tests,
        "4_aapl": payloads.get("AAPL") or {},
        "5_avgo": payloads.get("AVGO") or {},
        "6_lite": payloads.get("LITE") or {},
        "7_value_driver_universe": universes,
        "8_core_claims": claims,
        "9_material_events": material,
        "10_event_transmission_examples": transmissions,
        "11_claim_driver_history_example": history_examples,
        "12_critic_findings": critic_findings,
        "13_pm_synthesis": pm,
        "14_unresolved_gaps": summary.get("unresolved_gaps") or [],
        "brain_v1_complete": bool(summary.get("brain_v1_complete")) and not blocking,
        "generated_at": summary.get("generated_at"),
    }


def _evidence_rows(store: BrainStore, ticker: str) -> list[dict]:
    run = store.latest_run(ticker) or {}
    row = store.latest_evidence_set(ticker, run_id=run.get("run_id")) or store.latest_evidence_set(ticker) or {}
    payload = row.get("payload") or {}
    return list(payload.get("reasoning_rows") or payload.get("rows") or [])[:16]


def backfill_transmissions(store: BrainStore) -> dict[str, list[dict]]:
    from stock_pm.brain.llm_steps import compact_evidence_rows, event_transmission
    from stock_pm.brain.routing import BrainCompleter, ROLE_REASONING
    from stock_pm.brain.scenario import apply_scenario_policy, qualifies_for_base
    from stock_pm.brain.transmission import validate_transmission

    reason_llm = BrainCompleter(role=ROLE_REASONING)
    out: dict[str, list[dict]] = {}
    for ticker in TICKERS:
        events = [row for row in store.list_events(ticker) if str(row.get("materiality") or "") == "material" and not row.get("duplicate")]
        if not events:
            out[ticker] = []
            continue
        run = store.latest_run(ticker) or {}
        run_id = run.get("run_id")
        exposures = store.list_exposures(ticker, run_id=run_id)
        by_event_exp = {str(row.get("event_id")): row for row in exposures if row.get("event_id")}
        drivers = store.list_drivers(ticker)
        claims = [row for row in store.list_active_claims(ticker) if row.get("is_core")]
        evidence = _evidence_rows(store, ticker)
        allowed = {str(row.get("id")) for row in evidence if row.get("id")} | {
            str(row.get("event_id")) for row in events
        } | {str(row.get("driver_id")) for row in drivers if row.get("driver_id")} | {
            str(row.get("claim_id")) for row in claims if row.get("claim_id")
        }
        context = {
            "ticker": ticker,
            "exposures": exposures,
            "states": store.list_states(ticker, run_id=run_id),
            "drivers": [
                {"driver_id": row.get("driver_id"), "canonical_key": row.get("canonical_key"), "name": row.get("name")}
                for row in drivers
            ],
            "claims": [{"claim_id": row.get("claim_id"), "title": row.get("title"), "statement": row.get("statement")} for row in claims],
            "evidence": compact_evidence_rows(evidence, limit=12),
        }
        rows: list[dict] = []
        for event in events[:3]:
            print("transmission", ticker, event.get("event_id"), flush=True)
            payload, audit = event_transmission(
                reason_llm,
                {
                    **context,
                    "events": [
                        {
                            "event_id": event.get("event_id"),
                            "event_type": event.get("event_type"),
                            "subject": event.get("subject"),
                            "title": event.get("title"),
                            "materiality": event.get("materiality"),
                            "evidence_ids": event.get("evidence_ids") or [],
                        }
                    ],
                },
                allowed_ids=allowed,
            )
            print("transmission_status", ticker, audit.get("llm_status"), audit.get("error"), flush=True)
            raw_item = ((payload or {}).get("items") or [{}])[0]
            checked = validate_transmission(raw_item, allowed_ids=allowed, exposure=by_event_exp.get(str(event.get("event_id"))))
            checked["event_id"] = event.get("event_id")
            checked["title"] = event.get("title")
            decision = qualifies_for_base(ticker=ticker, event=event, transmission=checked, evidence_rows=evidence)
            checked = apply_scenario_policy(checked, decision)
            checked["scenario_policy"] = decision
            rows.append(checked)
        out[ticker] = rows
        path = OUT / f"{ticker.lower()}_brain_v1.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["transmissions"] = rows
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out


def main() -> None:
    import sys

    tests_path = OUT / "tests.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8")) if tests_path.exists() else {"status": "unknown"}
    db = Database()
    research = ResearchService(ResearchStore(db))
    store = BrainStore(db)
    if "--transmissions-only" in sys.argv:
        rows = backfill_transmissions(store)
        _write("transmission_backfill.json", rows)
        print("transmission backfill", {key: len(value) for key, value in rows.items()}, flush=True)
        return
    tests_path = OUT / "tests.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8")) if tests_path.exists() else {"status": "unknown"}
    db = Database()
    research = ResearchService(ResearchStore(db))
    store = BrainStore(db)
    _write("architecture.json", architecture())
    summary = {"generated_at": _now(), "tickers": {}, "tests": tests}
    payloads: dict[str, dict] = {}
    for ticker in TICKERS:
        print("running", ticker, flush=True)
        result = run_brain(research, ticker, store=store, fetch_live=True, mode="full")
        payload = slim_result(ticker, result, store)
        payloads[ticker] = payload
        _write(f"{ticker.lower()}_brain_v1.json", payload)
        summary["tickers"][ticker] = {
            "status": payload["status"],
            "drivers": len(payload["drivers"]),
            "core_claims": len(payload["core_claims"]),
            "states": len(payload.get("states") or []),
            "events": len(payload["events"]),
            "material_events": len(payload.get("material_events") or []),
            "transmissions": len(payload["transmissions"]),
            "financial_impacts": len(payload.get("financial_impacts") or []),
            "theme_gaps": payload["theme_gaps"],
            "critic_inconsistent": bool((payload.get("critic") or {}).get("inconsistent")),
            "pm_status": (payload.get("pm_synthesis") or {}).get("status"),
            "chain_gaps": chain_gaps(payload),
        }
        print("done", ticker, summary["tickers"][ticker], flush=True)
    gaps: list[str] = []
    for ticker, row in summary["tickers"].items():
        gaps.extend(row.get("chain_gaps") or [])
    blocking = [item for item in gaps if any(token in item for token in ("failed", "too thin", "missing core", "state layer empty", "systematic driver miss"))]
    summary["unresolved_gaps"] = gaps
    summary["brain_v1_complete"] = not blocking
    _write("summary.json", summary)
    _write("acceptance.json", acceptance(summary, payloads, tests))
    print("summary", json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
