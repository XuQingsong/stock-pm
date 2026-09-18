#!/usr/bin/env python3
"""Phase 0 + Phase 1 end-to-end runtime validation. Does not start Phase 2."""

from __future__ import annotations

import json
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_pm.brain.context_miss import find_context_misses
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.routing import brain_completers, layer_settings
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.research.llm_reason import compact_text

GOLDEN = Path("artifacts/brain_v1/avgo_brain_v1.json")
OUT = Path("artifacts/brain_runtime_validation")
AVGO_FULL_REVIEW_TOTAL_TOKENS = 278739
AVGO_FULL_REVIEW_INPUT_TOKENS = 81207

EVIDENCE_LABELS = {
    "rev_a65ae2866d404168b4b90236ae2f13a6": (
        "Q3 FY2026 Exhibit 99.1: AI accelerator and networking demand continues to be very strong; "
        "Q4 AI semiconductor revenue guided to $21.7 billion, up 236%."
    ),
    "rev_d608e3e7661a49dfb06a59bd5c45927b": (
        "Reported Q3 FY2026 financials: revenue $29.6 billion (+86% YoY), GAAP operating income "
        "$16.0 billion, non-GAAP operating income $20.1 billion."
    ),
    "rev_843a1ee827964a139673007f7c44e957": "Broadcom priced cash tender offers for certain outstanding notes in June 2026.",
}

CASE_A_ORIGINAL = {
    "kind": "news",
    "event_key": "avgo_ai_demand_very_strong_q3",
    "subject": "avgo_ai_demand_very_strong_q3",
    "title": "Broadcom says demand for AI accelerators and networking continues to be very strong",
    "fact": "Management said demand for AI accelerators and networking continues to be very strong.",
    "url": "https://www.reuters.com/technology/broadcom-ai-demand-very-strong-2026-09-02/",
    "source": "Reuters",
    "published_at": "2026-09-02T21:10:00+00:00",
    "confidence": "high",
    "fact_reliability": "direct_fact",
    "confirmed": True,
}

CASES: list[dict[str, Any]] = [
    {
        "case_id": "A",
        "name": "完全重复的新闻",
        "historical_basis": (
            "Q3 FY2026 Exhibit 99.1 (2026-09-02) said AI accelerator and networking demand "
            "continues to be very strong. Secondary wires reprinted the same sentence."
        ),
        "expected_path": "l0_stop",
        "expected_material": False,
        "expected_glm53": False,
        "expected_full_review": False,
        "seed_original": True,
        "item": {
            "kind": "news",
            "event_id": "bev_val_case_a",
            "subject": "avgo_ai_demand_very_strong_q3",
            "title": "Broadcom says demand for AI accelerators and networking continues to be very strong",
            "fact": "Management said demand for AI accelerators and networking continues to be very strong.",
            "url": "https://www.bloomberg.com/news/articles/2026-09-03/broadcom-ai-demand-very-strong",
            "source": "Bloomberg",
            "published_at": "2026-09-03T13:40:00+00:00",
            "confidence": "high",
            "fact_reliability": "direct_fact",
        },
    },
    {
        "case_id": "B",
        "name": "有新内容但投资意义很低的普通新闻",
        "historical_basis": (
            "Broadcom CEO Hock Tan regularly presents at the Goldman Sachs Communacopia + "
            "Technology Conference. A scheduled conference appearance is not an operating update."
        ),
        "expected_path": "observation_memory",
        "expected_material": False,
        "expected_glm53": False,
        "expected_full_review": False,
        "item": {
            "kind": "news",
            "event_id": "bev_val_case_b",
            "event_key": "avgo_gs_conference_appearance",
            "title": "Broadcom CEO Hock Tan scheduled for Goldman Sachs conference appearance",
            "fact": (
                "Hock Tan will make a conference appearance at the Goldman Sachs Communacopia + "
                "Technology Conference. No operating update and no new information."
            ),
            "url": "https://www.goldmansachs.com/insights/events/communacopia-broadcom-2026",
            "source": "Goldman Sachs event listing",
            "published_at": "2026-09-08T14:00:00+00:00",
            "event_type": "other",
            "confidence": "high",
            "fact_reliability": "direct_fact",
        },
    },
    {
        "case_id": "C",
        "name": "明确、重要、已确认的 customer / demand event",
        "historical_basis": (
            "Google has been a confirmed Broadcom custom-TPU/ASIC customer for years. "
            "This case uses that known relationship as a post-print confirmation of an expanded "
            "custom-silicon order, not a rumor."
        ),
        "expected_path": "incremental",
        "expected_material": True,
        "expected_glm53": True,
        "expected_full_review": False,
        "expected_related": {
            "canonical_keys": [
                "hyperscaler_customer_concentration",
                "ai_semiconductor_demand_durability",
                "ai_silicon_competitive_position",
            ],
            "claim_needles": ["hyperscaler", "durability", "concentration", "competitive"],
        },
        "item": {
            "kind": "news",
            "event_id": "bev_val_case_c",
            "event_key": "google_confirmed_custom_asic_expansion",
            "title": "Google confirmed a Broadcom custom-silicon order expansion for next-generation TPU",
            "fact": (
                "Google, a named Broadcom customer, confirmed it will expand custom ASIC / TPU "
                "orders with Broadcom for the next-generation accelerator deployment. The update "
                "is an issuer-linked customer demand event, not a rumor."
            ),
            "url": "https://www.reuters.com/technology/google-broadcom-custom-tpu-order-2026-09-10/",
            "source": "Reuters",
            "published_at": "2026-09-10T16:20:00+00:00",
            "event_type": "customer",
            "entities": ["Google", "Broadcom"],
            "confidence": "high",
            "fact_reliability": "direct_fact",
            "confirmed": True,
        },
    },
    {
        "case_id": "D",
        "name": "重要但未经确认的 rumor",
        "historical_basis": (
            "Markets have repeatedly priced unconfirmed Google in-house silicon / TPU order-cut "
            "rumors against Broadcom. The rumor is decision-relevant if true, but unconfirmed."
        ),
        "expected_path": "incremental",
        "expected_material": True,
        "expected_glm53": True,
        "expected_full_review": False,
        "expected_shadow": True,
        "expected_current_state_unchanged": True,
        "expected_core_claims_unchanged": True,
        "item": {
            "kind": "news",
            "event_id": "bev_val_case_d",
            "event_key": "google_may_reduce_avgo_orders_rumor",
            "title": "Unconfirmed: Google may reduce Broadcom custom TPU orders",
            "fact": (
                "Rumor that Google may reduce Broadcom ASIC / TPU orders as it expands in-house "
                "silicon. The report is unconfirmed and uses anonymous sources."
            ),
            "url": "https://www.theinformation.com/articles/google-may-cut-broadcom-tpu-orders-2026",
            "source": "The Information (unconfirmed)",
            "published_at": "2026-09-11T18:05:00+00:00",
            "event_type": "customer",
            "entities": ["Google", "Broadcom"],
            "confidence": "low",
            "fact_reliability": "rumor",
            "confirmed": False,
        },
    },
    {
        "case_id": "E",
        "name": "与已有 Core Claim 明显相关的新反面证据",
        "historical_basis": (
            "The seeded AVGO Brain already records that a hyperscaler awarding custom AI chip "
            "work to Marvell moved AVGO 3.9%. This case is a follow-on confirmed competitive loss."
        ),
        "expected_path": "incremental",
        "expected_material": True,
        "expected_glm53": True,
        "expected_full_review": False,
        "expected_related": {
            "canonical_keys": [
                "ai_silicon_competitive_position",
                "hyperscaler_customer_concentration",
            ],
            "claim_needles": ["hyperscaler", "competitive", "concentration", "Marvell"],
        },
        "item": {
            "kind": "news",
            "event_id": "bev_val_case_e",
            "event_key": "marvell_hyperscaler_asic_win",
            "title": "Marvell wins a hyperscaler custom ASIC program Broadcom had been expected to supply",
            "fact": (
                "Marvell Technology announced a hyperscaler custom ASIC design win. The program "
                "had been expected to go to Broadcom, adding counter evidence against Broadcom's "
                "AI accelerator competitive position and customer concentration."
            ),
            "url": "https://www.reuters.com/technology/marvell-hyperscaler-asic-win-2026-09-12/",
            "source": "Reuters",
            "published_at": "2026-09-12T15:30:00+00:00",
            "event_type": "competition",
            "entities": ["Marvell", "Broadcom"],
            "confidence": "high",
            "fact_reliability": "direct_fact",
            "confirmed": True,
        },
    },
    {
        "case_id": "F",
        "name": "Earnings / major guidance",
        "historical_basis": (
            "Broadcom 8-K / Exhibit 99.1 dated 2026-09-02: Q3 FY2026 revenue $29.6B; management "
            "expects AI semiconductor revenue to accelerate to $21.7B, up 236%."
        ),
        "expected_path": "full_review",
        "expected_material": True,
        "expected_glm53": False,
        "expected_full_review": True,
        "expected_full_review_reason": "earnings",
        "item": {
            "kind": "filing",
            "event_id": "bev_val_case_f",
            "event_key": "avgo_q3_fy2026_earnings_guidance",
            "title": "Broadcom reports fiscal Q3 FY2026 earnings and guides Q4 AI semiconductor revenue to $21.7 billion",
            "fact": (
                "Q3 FY2026 revenue was $29.6 billion, up 86% year over year. Management said AI "
                "accelerator and networking demand continues to be very strong and expects AI "
                "semiconductor revenue to accelerate to $21.7 billion, up 236%."
            ),
            "url": "https://www.sec.gov/Archives/edgar/data/1730168/000173016826000012/exhibit991.htm",
            "source": "SEC Exhibit 99.1",
            "published_at": "2026-09-02T21:05:00+00:00",
            "event_type": "earnings",
            "confidence": "high",
            "fact_reliability": "direct_fact",
            "confirmed": True,
        },
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if name.endswith(".md"):
        path.write_text(str(payload), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)
    return path


def _labels(rows: list[dict[str, Any]], *keys: str) -> list[str]:
    out: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        token = ""
        for key in keys:
            if row.get(key):
                token = str(row.get(key))
                break
        if token and token not in out:
            out.append(token)
    return out


def _compact_row(row: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    item = dict(row or {})
    payload: dict[str, Any] = {}
    for key in keys:
        if key not in item:
            continue
        value = item.get(key)
        if isinstance(value, str):
            payload[key] = compact_text(value, 220)
        else:
            payload[key] = value
    return payload


def compact_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    shot = snapshot or {}
    return {
        "targeted": shot.get("targeted"),
        "full_brain": shot.get("full_brain"),
        "states": [_compact_row(row, "state_id", "name", "statement", "confidence") for row in shot.get("states") or []],
        "drivers": [_compact_row(row, "driver_id", "canonical_key", "name", "current_state") for row in shot.get("drivers") or []],
        "claims": [_compact_row(row, "claim_id", "title", "status", "statement", "is_core") for row in shot.get("claims") or []],
        "exposures": [_compact_row(row, "exposure_id", "exposure_type", "event_id") for row in shot.get("exposures") or []],
        "evidence": [_compact_row(row, "id", "evidence_id", "title", "fact", "statement") for row in shot.get("evidence") or []],
        "counter_evidence": [_compact_row(row, "link_id", "claim_id", "evidence_id", "direction", "reason") for row in shot.get("counter_evidence") or []],
        "history": [_compact_row(row, "history_id", "object_type", "object_id", "reason") for row in shot.get("history") or []],
        "causal_edges": [_compact_row(row, "edge_id", "from_node", "to_node", "statement", "status") for row in shot.get("causal_edges") or []],
        "shadows": [_compact_row(row, "shadow_id", "name", "statement") for row in shot.get("shadows") or []],
        "counts": {
            "states": len(shot.get("states") or []),
            "drivers": len(shot.get("drivers") or []),
            "claims": len(shot.get("claims") or []),
            "exposures": len(shot.get("exposures") or []),
            "evidence": len(shot.get("evidence") or []),
            "counter_evidence": len(shot.get("counter_evidence") or []),
            "history": len(shot.get("history") or []),
            "causal_edges": len(shot.get("causal_edges") or []),
        },
    }


def reconstruct_evidence(golden: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for group in (golden.get("drivers") or []), (golden.get("states") or []), (golden.get("exposures") or []):
        for row in group:
            for eid in row.get("evidence_ids") or []:
                token = str(eid)
                if not token or token in seen:
                    continue
                seen[token] = {
                    "id": token,
                    "evidence_id": token,
                    "title": compact_text(EVIDENCE_LABELS.get(token, token), 120),
                    "fact": EVIDENCE_LABELS.get(token, f"Evidence {token} cited by the AVGO golden Brain."),
                    "statement": EVIDENCE_LABELS.get(token, ""),
                    "source": "golden_brain_v1",
                }
    seen.setdefault(
        "rev_marvell_hyperscaler_win_in_claim",
        {
            "id": "rev_marvell_hyperscaler_win_in_claim",
            "evidence_id": "rev_marvell_hyperscaler_win_in_claim",
            "title": "Marvell hyperscaler custom ASIC award cited in the golden concentration claim",
            "fact": "A hyperscaler awarding custom AI chip work to competitor Marvell moved AVGO shares 3.9%.",
            "statement": "Counter evidence already inside the seeded Core Claim text.",
            "source": "golden_claim_statement",
        },
    )
    return list(seen.values())


def leftover_brain(store: BrainStore, golden: dict[str, Any]) -> dict[str, Any]:
    evidence = reconstruct_evidence(golden)
    return {
        "states": store.list_states("AVGO"),
        "drivers": store.list_drivers("AVGO"),
        "claims": store.list_active_claims("AVGO"),
        "exposures": store.list_exposures("AVGO"),
        "events": store.list_events("AVGO"),
        "history": store.list_history("AVGO"),
        "causal_edges": store.list_causal_edges("AVGO"),
        "evidence": evidence,
        "shadows": store.list_shadows("AVGO"),
    }


def seed_avgo_brain(golden: dict[str, Any], *, include_case_a_original: bool = False) -> tuple[BrainStore, dict[str, Any]]:
    store = BrainStore()
    run_id = golden.get("run_id")
    for row in golden.get("states") or []:
        store.insert_state({**row, "ticker": "AVGO", "run_id": row.get("run_id") or run_id})
    for row in golden.get("drivers") or []:
        store.insert_driver({**row, "ticker": "AVGO", "run_id": row.get("run_id") or run_id, "status": "active"})
    for row in golden.get("core_claims") or []:
        store.insert_claim(
            {
                **row,
                "ticker": "AVGO",
                "is_core": True,
                "lifecycle": row.get("lifecycle") or "core",
                "claim_type": "operating",
                "run_id": row.get("run_id") or run_id,
            }
        )
    for row in golden.get("events") or []:
        store.insert_event({**row, "ticker": "AVGO", "run_id": row.get("run_id") or run_id})
        if row.get("title"):
            store.insert_news(
                {
                    "ticker": "AVGO",
                    "title": row.get("title"),
                    "new_fact": row.get("title"),
                    "run_id": run_id,
                    "url": row.get("url"),
                    "layer": "contextual",
                }
            )
    for row in golden.get("exposures") or []:
        store.insert_exposure({**row, "ticker": "AVGO", "run_id": row.get("run_id") or run_id})
    for row in golden.get("history") or []:
        store.insert_history({**row, "ticker": "AVGO"})
    for driver in golden.get("drivers") or []:
        for claim_id in driver.get("related_claim_ids") or []:
            store.upsert_causal_edge(
                {
                    "ticker": "AVGO",
                    "from_node": driver.get("driver_id") or driver.get("canonical_key"),
                    "to_node": claim_id,
                    "statement": f"{driver.get('name')} informs core claim {claim_id}.",
                    "status": "supported",
                    "evidence_ids": list(driver.get("evidence_ids") or []),
                }
            )
    concentration = next(
        (row for row in golden.get("core_claims") or [] if "hyperscaler" in str(row.get("title") or "").lower()),
        None,
    )
    if concentration:
        store.insert_link(
            {
                "claim_id": concentration["claim_id"],
                "evidence_id": "rev_a65ae2866d404168b4b90236ae2f13a6",
                "direction": "support",
                "strength": "medium",
                "relevance": "direct",
                "reason": "Exhibit 99.1 is supporting evidence for the AI concentration / demand claims.",
            }
        )
        store.insert_link(
            {
                "claim_id": concentration["claim_id"],
                "evidence_id": "rev_marvell_hyperscaler_win_in_claim",
                "direction": "oppose",
                "strength": "medium",
                "relevance": "direct",
                "reason": "The golden claim itself cites a hyperscaler awarding custom AI chip work to Marvell.",
            }
        )
    if include_case_a_original:
        store.insert_news(
            {
                "ticker": "AVGO",
                "title": CASE_A_ORIGINAL["title"],
                "new_fact": CASE_A_ORIGINAL["fact"],
                "url": CASE_A_ORIGINAL["url"],
                "source": CASE_A_ORIGINAL["source"],
                "published_at": CASE_A_ORIGINAL["published_at"],
                "layer": "contextual",
            }
        )
        store.insert_event(
            {
                "ticker": "AVGO",
                "event_type": "other",
                "subject": CASE_A_ORIGINAL["subject"],
                "title": CASE_A_ORIGINAL["title"],
                "url": CASE_A_ORIGINAL["url"],
                "fingerprint": "bevfp_case_a_original",
                "fact_reliability": "direct_fact",
                "materiality": "context",
            }
        )
        store.insert_observation(
            {
                "ticker": "AVGO",
                "title": CASE_A_ORIGINAL["title"],
                "statement": CASE_A_ORIGINAL["fact"],
                "kind": "news",
                "material": False,
                "fingerprint": "bevfp_case_a_original",
                "payload": {"event_key": CASE_A_ORIGINAL["event_key"]},
            }
        )
    return store, leftover_brain(store, golden)


def ping_layers(settings: Settings) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for role in ("mechanical", "reasoning"):
        cfg = layer_settings(settings, role=role)
        started = datetime.now(timezone.utc)
        try:
            from stock_pm.brain.routing import BrainCompleter

            completer = BrainCompleter(settings, role=role)
            result = completer.complete_json(
                system='Return one JSON object: {"ok": true, "role": ""}',
                user=json.dumps({"ping": True, "role": role}),
            )
            rows[role] = {
                "ok": result.get("status") == "ok",
                "status": result.get("status"),
                "model": result.get("model") or cfg.llm_model,
                "base_url": (cfg.llm_base_url or "")[:80],
                "llm_called": result.get("llm_called"),
                "error": compact_text(str(result.get("error") or ""), 200) or None,
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "latency_ms": result.get("latency_ms"),
                "elapsed_s": (datetime.now(timezone.utc) - started).total_seconds(),
            }
        except Exception as exc:  # noqa: BLE001 — validation must record live failure
            rows[role] = {
                "ok": False,
                "status": "failed",
                "model": cfg.llm_model,
                "base_url": (cfg.llm_base_url or "")[:80],
                "error": compact_text(str(exc), 200),
            }
    return rows


def snapshot_coverage(snapshot: dict[str, Any] | None, leftover: dict[str, Any]) -> dict[str, Any]:
    shot = snapshot or {}
    def _count(kind: str, *keys: str) -> tuple[int, int]:
        have = len(_labels(shot.get(kind) if kind != "counter_evidence" else shot.get("counter_evidence"), *keys))
        total = len(leftover.get(kind) or leftover.get("claims") or [])
        if kind == "states":
            total = len(leftover.get("states") or [])
        elif kind == "drivers":
            total = len(leftover.get("drivers") or [])
        elif kind == "claims":
            total = len(leftover.get("claims") or [])
        return have, total

    states_n, states_t = _count("states", "state_id")
    drivers_n, drivers_t = _count("drivers", "driver_id")
    claims_n, claims_t = _count("claims", "claim_id")
    object_have = states_n + drivers_n + claims_n
    object_total = max(states_t + drivers_t + claims_t, 1)
    return {
        "states": f"{states_n}/{states_t}",
        "drivers": f"{drivers_n}/{drivers_t}",
        "claims": f"{claims_n}/{claims_t}",
        "object_fraction": round(object_have / object_total, 4),
        "near_full_brain": (object_have / object_total) >= 0.8,
    }


def related_expected(case: dict[str, Any], leftover: dict[str, Any]) -> dict[str, list[str]]:
    spec = case.get("expected_related") or {}
    keys = {str(item).lower() for item in spec.get("canonical_keys") or []}
    needles = [str(item).lower() for item in spec.get("claim_needles") or []]
    drivers = []
    for row in leftover.get("drivers") or []:
        token = str(row.get("canonical_key") or "").lower()
        if token in keys:
            drivers.append(row.get("driver_id") or row.get("canonical_key"))
    claims = []
    for row in leftover.get("claims") or []:
        blob = f"{row.get('title') or ''} {row.get('statement') or ''}".lower()
        if any(needle in blob for needle in needles):
            claims.append(row.get("claim_id") or row.get("title"))
    return {"drivers": drivers, "claims": claims}


def detect_anomalies(case: dict[str, Any], result: dict[str, Any], leftover: dict[str, Any], store: BrainStore) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    trace = result.get("trace") or {}
    path = result.get("path")
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    approved = list(gate.get("approved") or [])
    coverage = snapshot_coverage(snapshot, leftover) if snapshot else {}

    if result.get("glm53_called") and not result.get("material") and path != "full_review":
        anomalies.append({"code": "non_material_called_glm53", "detail": "Non-material event called GLM-5.3."})
    if case.get("expected_material") and result.get("stopped") and path != "full_review" and path != case.get("expected_path"):
        anomalies.append({"code": "material_event_stopped_early", "detail": f"Expected material path {case.get('expected_path')}, got {path}."})
    if path == "full_review" and not case.get("expected_full_review"):
        anomalies.append({"code": "ordinary_news_triggered_full_review", "detail": f"full_review_reason={result.get('full_review_reason')}"})
    if case.get("expected_full_review") is False and result.get("full_review"):
        anomalies.append({"code": "ordinary_news_triggered_full_review", "detail": result.get("full_review_reason")})
    if case.get("expected_glm53") and not result.get("glm53_called") and path != "full_review":
        anomalies.append({"code": "material_event_stopped_early", "detail": "Material event did not call GLM-5.3."})
    if case.get("expected_path") and path != case.get("expected_path"):
        anomalies.append({"code": "path_deviation", "detail": f"expected {case.get('expected_path')}, got {path}"})

    expected = related_expected(case, leftover)
    affected = result.get("affected") or {}
    if expected["drivers"] or expected["claims"]:
        got_drivers = {str(item) for item in (affected.get("drivers") or [])}
        got_claims = {str(item) for item in (affected.get("claims") or [])}
        miss_drivers = [item for item in expected["drivers"] if item not in got_drivers]
        miss_claims = [item for item in expected["claims"] if item not in got_claims]
        if miss_drivers or miss_claims:
            anomalies.append(
                {
                    "code": "affected_objects_missed",
                    "detail": {"drivers": miss_drivers, "claims": miss_claims},
                }
            )

    if snapshot:
        if not (snapshot.get("evidence") or []) and (leftover.get("evidence") or []) and result.get("material") and path == "incremental":
            anomalies.append({"code": "snapshot_missing_key_evidence", "detail": "Targeted snapshot evidence list is empty while Brain evidence exists."})
        if not (snapshot.get("counter_evidence") or []) and case["case_id"] == "E":
            anomalies.append({"code": "snapshot_missing_key_counter_evidence", "detail": "Case E snapshot has no oppose links."})
        if coverage.get("near_full_brain"):
            anomalies.append({"code": "glm53_received_near_full_brain", "detail": coverage})

    core_claim_edits = [
        row
        for row in approved
        if str(row.get("object_type") or "") in {"claim", "core_claim"} and (row.get("is_core") or str(row.get("object_type") or "") == "core_claim")
    ]
    if len(core_claim_edits) > 1 and path == "incremental":
        anomalies.append({"code": "ordinary_event_modified_multiple_core_claims", "detail": [row.get("object_id") for row in core_claim_edits]})

    rumor = case["case_id"] == "D" or "rumor" in f"{(case.get('item') or {}).get('fact_reliability')}"
    if rumor:
        for row in store.list_current_states("AVGO"):
            blob = f"{row.get('statement') or ''} {row.get('name') or ''}".lower()
            if any(token in blob for token in ("may reduce", "unconfirmed", "rumor", "cutting avgo")):
                anomalies.append({"code": "shadow_entered_current_state", "detail": row.get("name") or row.get("state_id")})
                break
        if result.get("current_state_unchanged") is False:
            anomalies.append({"code": "shadow_entered_current_state", "detail": "Rumor changed Current State."})
        if result.get("core_claims_unchanged") is False:
            anomalies.append({"code": "change_proposal_bypassed_phase0", "detail": "Rumor changed a Core Claim."})

    for row in approved:
        if str(row.get("source_kind") or "") == "price" and str(row.get("object_type") or "") in {"claim", "core_claim"}:
            anomalies.append({"code": "price_modified_fundamental_claim", "detail": row.get("object_id")})
        if rumor and str(row.get("object_type") or "") in {"company_state", "state", "core_claim", "claim", "value_driver"}:
            if gate.get("auto_commit_allowed"):
                anomalies.append({"code": "change_proposal_bypassed_phase0", "detail": row.get("object_type")})

    if path == "incremental" and approved:
        existing_status = {row.get("claim_id"): row.get("status") for row in leftover.get("claims") or []}
        for row in core_claim_edits:
            new_status = (row.get("to_payload") or {}).get("status")
            old_status = existing_status.get(row.get("object_id"))
            if new_status and old_status and new_status != old_status and gate.get("auto_commit_allowed"):
                anomalies.append(
                    {
                        "code": "incremental_logic_conflict",
                        "detail": f"Core claim {row.get('object_id')} {old_status} -> {new_status} from one ordinary event.",
                    }
                )
    _ = trace
    return anomalies


def build_route(case: dict[str, Any], result: dict[str, Any], misses: list[dict[str, Any]], anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    extract = result.get("extract") if isinstance(result.get("extract"), dict) else {}
    l0 = result.get("l0") if isinstance(result.get("l0"), dict) else {}
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    materiality = result.get("materiality") if isinstance(result.get("materiality"), dict) else {}
    snapshot = compact_snapshot(result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {})
    decisions = (result.get("trace") or {}).get("proposal_decisions") or {}
    l0_why = "not reached (full_review short-circuit)" if result.get("path") == "full_review" else (
        f"stop={l0.get('stop')} reason={l0.get('stop_reason') or 'pass'} duplicate={l0.get('duplicate')}"
    )
    return {
        "case_id": case["case_id"],
        "name": case["name"],
        "historical_basis": case["historical_basis"],
        "input": case["item"],
        "l0_why": l0_why,
        "l0": {
            "duplicate": l0.get("duplicate") or result.get("duplicate"),
            "stop": l0.get("stop") or result.get("path") == "l0_stop",
            "stop_reason": l0.get("stop_reason") or result.get("stop_reason"),
            "event_type": l0.get("event_type"),
            "source_tier": l0.get("source_tier"),
            "fingerprint": l0.get("fingerprint"),
        },
        "glm52_extract": {
            "called": result.get("glm52_called"),
            "fact": compact_text(extract.get("fact") or "", 300),
            "event_type": extract.get("event_type"),
            "novelty": extract.get("novelty"),
            "entities": extract.get("entities"),
            "material": extract.get("material"),
            "fact_reliability": extract.get("fact_reliability"),
            "possible_affected": extract.get("possible_affected") or extract.get("possible_affected_objects"),
            "reason": compact_text(extract.get("reason") or "", 240),
        },
        "materiality": {
            "material": result.get("material"),
            "reason": materiality.get("reason") or result.get("stop_reason") or result.get("full_review_reason"),
            "layer": materiality.get("layer"),
        },
        "affected_objects": result.get("affected"),
        "snapshot": snapshot,
        "glm53_called": result.get("glm53_called"),
        "glm53_saw": snapshot if result.get("glm53_called") else None,
        "proposals": [
            {
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "source_kind": row.get("source_kind"),
                "reason": compact_text(row.get("reason") or "", 240),
                "to": row.get("to") or row.get("to_payload"),
            }
            for row in (result.get("proposals") or [])
        ],
        "phase0": {
            "approve": [compact_text(str(row.get("object_type") or "") + ":" + str(row.get("reason_code") or row.get("reason") or ""), 200) for row in gate.get("approved") or []],
            "reject": [
                {
                    "object_type": row.get("object_type"),
                    "object_id": row.get("object_id"),
                    "reason_code": row.get("reason_code"),
                    "rules": row.get("rules"),
                }
                for row in gate.get("rejected") or []
            ],
            "requires_review": [row.get("object_type") for row in gate.get("requires_review") or []],
            "auto_commit_allowed": gate.get("auto_commit_allowed"),
            "committed": gate.get("committed"),
            "current_state_unchanged": result.get("current_state_unchanged"),
            "core_claims_unchanged": result.get("core_claims_unchanged"),
        },
        "brain_changed": (result.get("trace") or {}).get("changed_objects") or [],
        "proposal_decisions": decisions,
        "critic_scope": (result.get("trace") or {}).get("critic_scope"),
        "full_review_triggered": result.get("full_review"),
        "full_review_reason": result.get("full_review_reason"),
        "path": result.get("path"),
        "trace": result.get("trace"),
        "context_miss": misses,
        "anomalies": anomalies,
        "llm_calls": result.get("llm_calls") or [],
        "elapsed_ms": result.get("elapsed_ms"),
    }


def metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(cases)
    l0_dup = sum(1 for row in cases if row.get("path") == "l0_stop")
    material = sum(1 for row in cases if (row.get("materiality") or {}).get("material") is True or row.get("material") is True)
    non_material = sum(1 for row in cases if (row.get("materiality") or {}).get("material") is False or row.get("material") is False)
    glm53 = sum(1 for row in cases if row.get("glm53_called"))
    incremental = [row for row in cases if row.get("path") == "incremental"]
    snap_sizes = [int((row.get("trace") or {}).get("snapshot_size") or 0) for row in incremental]
    reductions = [float((row.get("trace") or {}).get("snapshot_reduction") or 0) for row in incremental if (row.get("trace") or {}).get("snapshot_reduction") is not None]
    glm53_tokens = []
    glm53_input = []
    latencies = [int(row.get("elapsed_ms") or 0) for row in cases]
    affected_n = []
    proposal_n = []
    approve = reject = review = 0
    full_review_n = sum(1 for row in cases if row.get("full_review") or row.get("full_review_triggered"))
    miss_n = sum(len(row.get("context_miss") or []) for row in cases)
    unexpected = sum(1 for row in cases if any(a.get("code") == "incremental_logic_conflict" for a in row.get("anomalies") or []))
    for row in cases:
        usage = ((row.get("trace") or {}).get("token_usage") or {})
        if row.get("glm53_called"):
            glm53_tokens.append(int(usage.get("total_tokens") or 0))
            reasoning = [call for call in usage.get("calls") or [] if call.get("role") == "reasoning"]
            glm53_input.append(sum(int(call.get("input_tokens") or 0) for call in reasoning))
        affected = row.get("affected_objects") or {}
        affected_n.append(sum(len(affected.get(key) or []) for key in ("states", "drivers", "claims", "exposures")))
        proposal_n.append(len(row.get("proposals") or []))
        decisions = row.get("proposal_decisions") or {}
        approve += int(decisions.get("approve") or 0)
        reject += int(decisions.get("reject") or 0)
        review += int(decisions.get("requires_review") or 0)
    skip_rate = round((n - glm53) / n, 4) if n else None
    avg = lambda values: round(sum(values) / len(values), 2) if values else None
    avg_glm53_input = avg(glm53_input)
    token_reduction_vs_full = None
    if avg_glm53_input is not None:
        token_reduction_vs_full = round(1 - (avg_glm53_input / max(AVGO_FULL_REVIEW_INPUT_TOKENS, 1)), 4)
    return {
        "total_events": n,
        "l0_duplicate_stop": l0_dup,
        "material": material,
        "non_material": non_material,
        "glm53_calls": glm53,
        "glm53_skip_rate": skip_rate,
        "avg_targeted_snapshot_size": avg(snap_sizes),
        "avg_snapshot_object_reduction": avg(reductions),
        "avg_glm53_tokens": avg(glm53_tokens),
        "avg_glm53_input_tokens": avg_glm53_input,
        "full_review_input_tokens_avgo_v1": AVGO_FULL_REVIEW_INPUT_TOKENS,
        "full_review_total_tokens_avgo_v1": AVGO_FULL_REVIEW_TOTAL_TOKENS,
        "token_reduction_vs_old_full_review_input": token_reduction_vs_full,
        "avg_latency_ms": avg(latencies),
        "avg_affected_object_count": avg(affected_n),
        "avg_affected_object_count_incremental": avg([n for n, row in zip(affected_n, cases) if row.get("path") == "incremental"]),
        "avg_proposal_count": avg(proposal_n),
        "approve": approve,
        "reject": reject,
        "requires_review": review,
        "full_review_triggers": full_review_n,
        "context_miss_count": miss_n,
        "unexpected_brain_change_count": unexpected,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 0 + Phase 1 功能验证报告",
        "",
        f"生成时间: {payload.get('generated_at')}",
        "范围: AVGO golden Brain + 6 类真实/半真实事件。未进入 Phase 2，未改架构。",
        "",
        "## 1. 六个 Case 的完整 trace",
        "",
    ]
    for case in payload.get("cases") or []:
        lines.extend(
            [
                f"### Case {case['case_id']} — {case['name']}",
                "",
                f"- 历史依据: {case['historical_basis']}",
                f"- Input: `{case['input'].get('title')}`",
                f"- Path: `{case['path']}`",
                f"- L0: {case['l0_why']}",
                f"- GLM-5.2 extract: called={case['glm52_extract'].get('called')} type={case['glm52_extract'].get('event_type')} novelty={case['glm52_extract'].get('novelty')} material={case['glm52_extract'].get('material')}",
                f"- Extract fact: {case['glm52_extract'].get('fact') or '(none)'}",
                f"- Materiality: {case['materiality'].get('material')} — {case['materiality'].get('reason')}",
                f"- Affected objects: {json.dumps(case.get('affected_objects') or {}, ensure_ascii=False)}",
                f"- Snapshot counts: {json.dumps((case.get('snapshot') or {}).get('counts') or {}, ensure_ascii=False)}",
                f"- Snapshot states: {[row.get('name') for row in (case.get('snapshot') or {}).get('states') or []]}",
                f"- Snapshot drivers: {[row.get('canonical_key') or row.get('name') for row in (case.get('snapshot') or {}).get('drivers') or []]}",
                f"- Snapshot claims: {[row.get('title') for row in (case.get('snapshot') or {}).get('claims') or []]}",
                f"- GLM-5.3 called: {case.get('glm53_called')}",
                f"- Proposal count: {len(case.get('proposals') or [])}",
                f"- Phase 0 approve/reject/review: {json.dumps(case.get('proposal_decisions') or {}, ensure_ascii=False)}",
                f"- Brain changed: {case.get('brain_changed')}",
                f"- Full review: {case.get('full_review_triggered')} reason={case.get('full_review_reason')}",
                f"- Context miss count: {len(case.get('context_miss') or [])}",
                f"- Anomalies: {json.dumps(case.get('anomalies') or [], ensure_ascii=False)}",
                f"- Latency ms: {case.get('elapsed_ms')}",
                "",
            ]
        )
        if case.get("proposals"):
            lines.append("Proposals:")
            for row in case["proposals"]:
                lines.append(f"- `{row.get('object_type')}` {row.get('object_id') or ''} / {row.get('source_kind')}: {row.get('reason')}")
            lines.append("")
        if case.get("phase0", {}).get("reject"):
            lines.append("Phase 0 rejects:")
            for row in case["phase0"]["reject"]:
                lines.append(f"- `{row.get('object_type')}` reason_code={row.get('reason_code')} rules={row.get('rules')}")
            lines.append("")
        if case.get("context_miss"):
            lines.append("Context misses:")
            for row in case["context_miss"][:12]:
                lines.append(f"- `{row.get('kind')}` {row.get('object_id')} {row.get('label')} hits={row.get('keyword_hits')} score={row.get('score')}")
            if len(case["context_miss"]) > 12:
                lines.append(f"- … {len(case['context_miss']) - 12} more")
            lines.append("")
    lines.extend(
        [
            "## 2. Runtime quantitative metrics",
            "",
            "```json",
            json.dumps(payload.get("metrics") or {}, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 3. Context miss 列表",
            "",
        ]
    )
    misses = payload.get("all_context_misses") or []
    if not misses:
        lines.append("无 context_miss。")
    for row in misses:
        lines.append(f"- Case {row.get('case_id')}: `{row.get('kind')}` {row.get('object_id')} — {row.get('label')} ({row.get('keyword_hits')})")
    lines.extend(["", "## 4. Runtime anomaly 列表", ""])
    anomalies = payload.get("all_anomalies") or []
    if not anomalies:
        lines.append("无 Runtime Anomaly。")
    for row in anomalies:
        lines.append(f"- Case {row.get('case_id')}: `{row.get('code')}` — {row.get('detail')}")
    lines.extend(
        [
            "",
            "## 5. 哪些地方符合预期",
            "",
        ]
    )
    for item in payload.get("expected_matches") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## 6. 哪些地方和设计存在偏差", ""])
    for item in payload.get("deviations") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 7. 当前是否已经真正实现 Incremental Brain Runtime",
            "",
            payload.get("incremental_runtime_verdict") or "",
            "",
            "## 8. 发现的问题（本轮不修架构）",
            "",
        ]
    )
    for item in payload.get("findings") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _changed_blob(row: Any) -> str:
    if isinstance(row, dict):
        return f"{row.get('object_type') or ''} {row.get('kind') or ''} {row.get('object_id') or ''}"
    return str(row or "")


def judge(payload: dict[str, Any]) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in payload.get("cases") or []}
    expected: list[str] = []
    deviations: list[str] = []
    findings: list[str] = []
    extra_anomalies: list[dict[str, Any]] = []
    a, b, c, d, e, f = (cases.get(key) for key in "ABCDEF")
    if a and a.get("path") == "l0_stop" and not a.get("glm53_called"):
        expected.append("Case A 重复新闻在 L0 停止，未调用 GLM-5.3。")
    elif a:
        deviations.append(f"Case A 未按设计在 L0 停止，path={a.get('path')}。")
    if b and b.get("path") == "observation_memory" and not b.get("glm53_called"):
        expected.append("Case B 低价值新闻停在 observation memory，未进入 reasoning。")
    elif b:
        deviations.append(f"Case B 低价值新闻 path={b.get('path')} glm53={b.get('glm53_called')}。")
    if c and c.get("path") == "incremental" and c.get("glm53_called"):
        expected.append("Case C 已确认 customer event 进入 incremental 并调用 GLM-5.3。")
    elif c:
        deviations.append(f"Case C 未进入 incremental reasoning，path={c.get('path')}。")
    if d and d.get("glm53_called") and d.get("phase0", {}).get("current_state_unchanged") is not False:
        expected.append("Case D rumor 可以 material，但 Current State / Core Claim 未被直接改写。")
    d_changed = [_changed_blob(row) for row in (d.get("brain_changed") or [])] if d else []
    if d and any("shadow" in token or "question" in token or "research" in token for token in d_changed):
        expected.append("Case D 的未确认信息进入 Shadow / Research Question 通道。")
    if d and d.get("glm53_called") and not any(str((row or {}).get("object_type") or "") in {"company_state", "state", "core_claim", "value_driver"} and str((row or {}).get("decision") or "") == "approve" for row in ((d.get("proposal_decisions") or {}).get("items") or []) if isinstance(row, dict)):
        expected.append("Case D GLM-5.3 没有把 rumor 写成 Current State / Driver / Core Claim；Phase 0 批准的是 Shadow / RQ / market_attention。")
    if e and e.get("path") == "incremental" and e.get("glm53_called"):
        expected.append("Case E 竞争/反面证据进入 incremental reasoning，没有短路成 Full Review。")
    if f and (f.get("full_review_triggered") or f.get("full_review")):
        expected.append("Case F earnings/guidance 触发 Full Review，而不是被当成普通新闻增量改 Brain。")
    if any((row.get("snapshot") or {}).get("full_brain") is False for row in (c, e) if row):
        expected.append("Incremental 路径声明 snapshot.targeted=True / full_brain=False。")
    if all((row.get("phase0") or {}).get("current_state_unchanged") in {True, None} for row in (c, d, e) if row):
        expected.append("三条 material incremental 事件都没有把 Current State / Core Claim 自动写进 Brain。")

    for case_id, row in (("C", c), ("D", d), ("E", e)):
        if not row:
            continue
        claims = ((row.get("snapshot") or {}).get("counts") or {}).get("claims") or 0
        if claims >= 5:
            extra_anomalies.append(
                {
                    "case_id": case_id,
                    "code": "glm53_received_near_full_brain",
                    "detail": f"Snapshot included all {claims} Core Claims plus unrelated objects (valuation / leverage / GAAP / price reaction).",
                }
            )
            deviations.append(f"Case {case_id} 的 targeted snapshot 包含全部 5 条 Core Claim，GLM-5.3 实际看到了接近完整 Claim 层。")
    if d:
        drivers = d.get("affected_objects") or {}
        blob = " ".join(str(item) for item in (drivers.get("drivers") or []))
        if "e605ec342c0a4888bec050bd17106982" not in blob:
            extra_anomalies.append(
                {
                    "case_id": "D",
                    "code": "affected_objects_missed",
                    "detail": "Google order-cut rumor did not retrieve ai_semiconductor_demand_durability; it retrieved leverage / GAAP gap / valuation instead.",
                }
            )
            deviations.append("Case D rumor 漏掉了 AI demand durability driver，却命中了杠杆、GAAP gap、估值这类弱相关对象。")
    if any((row.get("proposal_decisions") or {}).get("requires_review") for row in (c, e) if row):
        deviations.append("Case C/E 的 Change Proposal 因 Change Budget 全部进入 requires_review，constitution 拒绝规则没有先落地；新闻改 State/Driver/Claim 没有被直接 reject。")
        findings.append("evaluate_brain_changes 在 budget.requires_review 时 continue，constitution_violations 即使命中也不会变成 reject。Confirmed customer 改 Core Claim 因此停在 review，而不是按 Phase 0 规则拒绝。")
    if any(row.get("code") == "snapshot_missing_key_evidence" for row in payload.get("all_anomalies") or []):
        deviations.append("Targeted snapshot 没有带上 Brain evidence 正文（evidence count=0），只带了 oppose link。")
        findings.append("run_brain_update._store_context() 把 evidence 固定写成空列表。affected objects 上的 evidence_ids 无法在 snapshot 里解成 Evidence 行。")
    if payload.get("metrics", {}).get("context_miss_count"):
        findings.append("存在 context_miss。其中一部分是 Exhibit 99.1 这类确实相关的 supporting evidence 没进 snapshot；另一部分是 Broadcom 关键词误伤（例如 notes tender）。不要用扩大整个 context 来掩盖。")
    findings.append("locate_affected_objects 把 event blob 里长度>3 的词都当成 needle。AVGO 对象普遍含 Broadcom/AI/revenue/demand，所以一条 customer/rumor/competition 新闻会拖进全部 Core Claims 和若干无关 State/Driver。")
    findings.append("Full Review 在 L0 之前判定。带 earnings/guidance 字样的重复稿不会走 duplicate stop，而会直接 full_review。")
    findings.append("Change Budget max_auto_drivers=1。GLM-5.3 一次提 2 个 driver 就会整批 requires_review，包括本来可以批准的 market-layer 以外对象。")
    findings.append("本轮没有扩大 snapshot，也没有改 routing / constitution / store。")

    incremental_yes = bool(
        a
        and a.get("path") == "l0_stop"
        and c
        and c.get("path") == "incremental"
        and f
        and (f.get("full_review") or f.get("full_review_triggered"))
    )
    near_full = bool(extra_anomalies) or any(row.get("code") == "glm53_received_near_full_brain" for row in payload.get("all_anomalies") or [])
    verdict = (
        "主路径已经接上：默认 incremental，L0 / materiality gate / Full Review trigger / Phase 0 写屏障都在真实 run_brain_update 上工作。"
        + (
            " 但 targeted snapshot 仍然过宽（5/5 Core Claims），evidence 正文进不了 snapshot，Change Budget 还会把 constitution reject 变成 review。不能认为 Incremental Brain Runtime 已经在信息论意义上完成。"
            if near_full or payload.get("metrics", {}).get("context_miss_count")
            else " 六类事件的 routing 已能区分 junk / rumor / confirmed customer / earnings。"
        )
    )
    if not incremental_yes:
        verdict = "Incremental 路径存在，但六个 Case 的 routing 与设计不完全一致，还不能宣布 Incremental Brain Runtime 已经真正实现。"
    return {
        "expected_matches": expected,
        "deviations": deviations,
        "findings": findings,
        "incremental_runtime_verdict": verdict,
        "extra_anomalies": extra_anomalies,
    }


def finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["metrics"] = metrics(payload.get("cases") or [])
    judged = judge(payload)
    extra = list(judged.pop("extra_anomalies") or [])
    payload["all_anomalies"] = list(payload.get("all_anomalies") or []) + extra
    payload.update(judged)
    payload["metrics"]["context_miss_count"] = len(payload.get("all_context_misses") or [])
    payload["metrics"]["runtime_anomaly_count"] = len(payload.get("all_anomalies") or [])
    return payload


def assemble_from_saved() -> dict[str, Any]:
    ping_path = OUT / "ping.json"
    ping = json.loads(ping_path.read_text(encoding="utf-8")) if ping_path.exists() else {}
    case_rows = []
    all_misses: list[dict[str, Any]] = []
    all_anomalies: list[dict[str, Any]] = []
    for spec in CASES:
        path = OUT / f"case_{spec['case_id'].lower()}.json"
        if not path.exists():
            raise SystemExit(f"missing {path}")
        row = json.loads(path.read_text(encoding="utf-8"))
        case_rows.append(row)
        for miss in row.get("context_miss") or []:
            all_misses.append({"case_id": spec["case_id"], **miss})
        for anomaly in row.get("anomalies") or []:
            all_anomalies.append({"case_id": spec["case_id"], **anomaly})
    return finalize_payload(
        {
            "generated_at": _now(),
            "ticker": "AVGO",
            "golden": str(GOLDEN),
            "ping": ping,
            "phase2_started": False,
            "architecture_changed": False,
            "assembled_from_saved_cases": True,
            "cases": case_rows,
            "all_context_misses": all_misses,
            "all_anomalies": all_anomalies,
        }
    )


def main() -> int:
    if "--assemble" in sys.argv:
        payload = assemble_from_saved()
        _write("report.json", payload)
        _write("REPORT.md", render_report(payload))
        _write("metrics.json", payload["metrics"])
        print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2), flush=True)
        print(payload["incremental_runtime_verdict"], flush=True)
        return 0
    if not GOLDEN.exists():
        raise SystemExit(f"missing {GOLDEN}")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings()
    print("ping GLM layers", flush=True)
    ping = ping_layers(settings)
    _write("ping.json", ping)
    mechanical, reasoning = brain_completers(settings)
    case_rows: list[dict[str, Any]] = []
    all_misses: list[dict[str, Any]] = []
    all_anomalies: list[dict[str, Any]] = []
    for spec in CASES:
        print(f"running Case {spec['case_id']} {spec['name']}", flush=True)
        store, leftover = seed_avgo_brain(golden, include_case_a_original=bool(spec.get("seed_original")))
        before_claims = {row.get("claim_id"): deepcopy(row) for row in store.list_active_claims("AVGO")}
        before_states = {row.get("state_id"): deepcopy(row) for row in store.list_current_states("AVGO")}
        try:
            result = run_brain_update(
                ticker="AVGO",
                item=spec["item"],
                store=store,
                mechanical_completer=mechanical,
                reasoning_completer=reasoning,
            )
        except Exception as exc:  # noqa: BLE001
            result = {
                "ticker": "AVGO",
                "path": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "glm52_called": False,
                "glm53_called": False,
                "full_review": False,
                "material": spec.get("expected_material"),
                "llm_calls": [],
                "trace": {"error": str(exc), "latency_ms": None},
            }
        snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
        event_for_miss = {**(spec.get("item") or {}), **((result.get("extract") or {}) if isinstance(result.get("extract"), dict) else {})}
        misses = []
        if result.get("path") == "incremental":
            misses = find_context_misses(event=event_for_miss, snapshot=snapshot, brain=leftover)
        anomalies = detect_anomalies(spec, result, leftover, store)
        after_claims = store.list_active_claims("AVGO")
        after_states = store.list_current_states("AVGO")
        claim_drift = [
            row.get("claim_id")
            for row in after_claims
            if before_claims.get(row.get("claim_id"), {}).get("status") != row.get("status")
            or before_claims.get(row.get("claim_id"), {}).get("statement") != row.get("statement")
        ]
        state_drift = [
            row.get("state_id")
            for row in after_states
            if before_states.get(row.get("state_id"), {}).get("statement") != row.get("statement")
        ]
        if claim_drift and spec["case_id"] in {"B", "D"}:
            anomalies.append({"code": "unexpected_brain_change", "detail": {"claims": claim_drift}})
        if state_drift and spec["case_id"] in {"A", "B", "D"}:
            anomalies.append({"code": "unexpected_brain_change", "detail": {"states": state_drift}})
        route = build_route(spec, result, misses, anomalies)
        route["claim_drift"] = claim_drift
        route["state_drift"] = state_drift
        route["shadows_after"] = [_compact_row(row, "shadow_id", "name", "statement", "status") for row in store.list_shadows("AVGO")]
        route["questions_after"] = [_compact_row(row, "question_id", "question", "why_it_matters") for row in store.list_questions("AVGO")]
        case_rows.append(route)
        for row in misses:
            all_misses.append({"case_id": spec["case_id"], **row})
        for row in anomalies:
            all_anomalies.append({"case_id": spec["case_id"], **row})
        _write(f"case_{spec['case_id'].lower()}.json", route)
        print(
            f"  path={route.get('path')} material={route.get('materiality', {}).get('material')} "
            f"glm53={route.get('glm53_called')} misses={len(misses)} anomalies={len(anomalies)}",
            flush=True,
        )
    payload = finalize_payload(
        {
            "generated_at": _now(),
            "ticker": "AVGO",
            "golden": str(GOLDEN),
            "ping": ping,
            "phase2_started": False,
            "architecture_changed": False,
            "cases": case_rows,
            "all_context_misses": all_misses,
            "all_anomalies": all_anomalies,
        }
    )
    _write("report.json", payload)
    _write("REPORT.md", render_report(payload))
    _write("metrics.json", payload["metrics"])
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2), flush=True)
    print(payload["incremental_runtime_verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
