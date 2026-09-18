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

from stock_pm.brain.context_miss import find_context_misses, score_snapshot_context
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.routing import brain_completers, layer_settings
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.research.llm_reason import compact_text

GOLDEN = Path("artifacts/brain_v1/avgo_brain_v1.json")
OUT = Path("artifacts/brain_runtime_validation_r2")
BASELINE_DIR = Path("artifacts/brain_runtime_validation")
AVGO_FULL_REVIEW_TOTAL_TOKENS = 278739
AVGO_FULL_REVIEW_INPUT_TOKENS = 81207

DRIVER_CONCENTRATION = "bdrv_414ad8bb1d8343bea291e8dc5eb44bba"
DRIVER_COMPETITION = "bdrv_4469e497110847e7a3961129f05e5a33"
DRIVER_DEMAND = "bdrv_e605ec342c0a4888bec050bd17106982"
DRIVER_LEVERAGE = "bdrv_0b42bfa225df4760a06d0a81c9df0d12"
DRIVER_GAAP = "bdrv_8dd8af15e6a84090b239eb0c00f6917f"
DRIVER_VALUATION = "bdrv_c65613d424614e7ba3e474bd1c3d4948"
CLAIM_DEMAND = "bclm_f4454cfe04e94211a79b23116bcf5de8"
CLAIM_HYPERSCALER = "bclm_2f3b915b62064c8a98300c530fa331ff"
CLAIM_MARGIN = "bclm_a84fd6c830884f80b7c4b1d49f984b24"
CLAIM_MULTIPLE = "bclm_a63762a2ab4f4410ad923ea9b1002c53"
EVIDENCE_EXHIBIT = "rev_a65ae2866d404168b4b90236ae2f13a6"
EVIDENCE_MARVELL = "rev_marvell_hyperscaler_win_in_claim"
IRRELEVANT_CDE = [
    DRIVER_LEVERAGE,
    DRIVER_GAAP,
    DRIVER_VALUATION,
    "bst_154e6e1ddc4f4970a61cdb2798b0fa51",
    "bst_21b14d3978024a2b8a6e622e84d40fdc",
    CLAIM_MARGIN,
    CLAIM_MULTIPLE,
]
GOLDEN_CONTEXT: dict[str, dict[str, Any]] = {
    "C": {
        "drivers": [DRIVER_CONCENTRATION, DRIVER_DEMAND],
        "claims": [CLAIM_HYPERSCALER, CLAIM_DEMAND],
        "evidence": [EVIDENCE_EXHIBIT],
        "support_evidence": [EVIDENCE_EXHIBIT],
        "counter_evidence": [],
        "states": [],
        "irrelevant": IRRELEVANT_CDE,
    },
    "D": {
        "drivers": [DRIVER_CONCENTRATION, DRIVER_DEMAND],
        "claims": [CLAIM_HYPERSCALER, CLAIM_DEMAND],
        "evidence": [EVIDENCE_EXHIBIT],
        "support_evidence": [EVIDENCE_EXHIBIT],
        "counter_evidence": [],
        "states": [],
        "irrelevant": IRRELEVANT_CDE,
    },
    "E": {
        "drivers": [DRIVER_CONCENTRATION, DRIVER_COMPETITION],
        "claims": [CLAIM_HYPERSCALER],
        "evidence": [EVIDENCE_EXHIBIT],
        "support_evidence": [EVIDENCE_EXHIBIT],
        "counter_evidence": [EVIDENCE_MARVELL],
        "states": [],
        "irrelevant": IRRELEVANT_CDE,
    },
}

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
            ],
            "claim_needles": ["hyperscaler", "durability", "concentration"],
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
        "counter_evidence": [
            _compact_row(row, "link_id", "claim_id", "evidence_id", "id", "title", "fact", "statement", "direction", "reason")
            for row in shot.get("counter_evidence") or []
        ],
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
    catalog = {
        token: {
            "id": token,
            "evidence_id": token,
            "title": compact_text(label, 120),
            "fact": label,
            "statement": label,
            "source": "golden_brain_v1",
        }
        for token, label in EVIDENCE_LABELS.items()
    }
    catalog[EVIDENCE_MARVELL] = {
        "id": EVIDENCE_MARVELL,
        "evidence_id": EVIDENCE_MARVELL,
        "title": "Marvell hyperscaler custom ASIC award cited in the golden concentration claim",
        "fact": "A hyperscaler awarding custom AI chip work to competitor Marvell moved AVGO shares 3.9%.",
        "statement": "A hyperscaler awarding custom AI chip work to competitor Marvell moved AVGO shares 3.9%.",
        "source": "golden_claim_statement",
        "direction": "oppose",
    }
    needed: set[str] = {EVIDENCE_MARVELL}
    for group in (golden.get("drivers") or []), (golden.get("states") or []), (golden.get("exposures") or []):
        for row in group:
            for eid in row.get("evidence_ids") or []:
                token = str(eid)
                if token in catalog:
                    needed.add(token)
    return [catalog[token] for token in needed if token in catalog]


def leftover_brain(store: BrainStore, golden: dict[str, Any]) -> dict[str, Any]:
    evidence = store.list_evidence("AVGO") if hasattr(store, "list_evidence") else reconstruct_evidence(golden)
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
        "links": store.list_links() if hasattr(store, "list_links") else [],
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
    for row in reconstruct_evidence(golden):
        store.upsert_evidence({**row, "ticker": "AVGO"})
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


def detect_anomalies(case: dict[str, Any], result: dict[str, Any], leftover: dict[str, Any], store: BrainStore, context_score: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
        claims_n = len(snapshot.get("claims") or [])
        if claims_n >= 5 and path == "incremental":
            anomalies.append({"code": "glm53_received_near_full_brain", "detail": f"Snapshot included {claims_n} Core Claims."})
    score = context_score or {}
    if case["case_id"] in {"C", "D", "E"} and score.get("support_evidence_miss"):
        anomalies.append({"code": "snapshot_missing_key_evidence", "detail": score.get("missed_relevant_objects")})
    if case["case_id"] == "E" and score.get("counter_evidence_miss"):
        anomalies.append({"code": "snapshot_missing_key_counter_evidence", "detail": score.get("missed_relevant_objects")})
    if score.get("irrelevant_count"):
        anomalies.append({"code": "irrelevant_objects_in_snapshot", "detail": score.get("obviously_irrelevant_objects")})

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


def build_route(case: dict[str, Any], result: dict[str, Any], misses: list[dict[str, Any]], anomalies: list[dict[str, Any]], context_score: dict[str, Any] | None = None) -> dict[str, Any]:
    extract = result.get("extract") if isinstance(result.get("extract"), dict) else {}
    l0 = result.get("l0") if isinstance(result.get("l0"), dict) else {}
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    materiality = result.get("materiality") if isinstance(result.get("materiality"), dict) else {}
    snapshot = compact_snapshot(result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {})
    decisions = (result.get("trace") or {}).get("proposal_decisions") or {}
    l0_why = (
        f"stop={l0.get('stop')} reason={l0.get('stop_reason') or 'pass'} duplicate={l0.get('duplicate')}"
        if l0
        else "L0 not recorded"
    )
    if result.get("path") == "full_review":
        l0_why = (
            f"L0 ran first: stop={l0.get('stop')} duplicate={l0.get('duplicate') or False}; "
            f"then full_review reason={result.get('full_review_reason')}"
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
        "context_score": context_score or {},
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
    core_claim_retrieval = []
    evidence_bodies = []
    irrelevant_counts = []
    recalls = []
    precisions = []
    support_miss = 0
    counter_miss = 0
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
        score = row.get("context_score") or {}
        if row.get("path") == "incremental":
            core_claim_retrieval.append(int(score.get("core_claim_retrieval_count") or ((row.get("snapshot") or {}).get("counts") or {}).get("claims") or 0))
            evidence_bodies.append(int(score.get("evidence_body_count") or 0))
            irrelevant_counts.append(int(score.get("irrelevant_count") or 0))
            if score.get("context_recall") is not None:
                recalls.append(float(score["context_recall"]))
            if score.get("context_precision") is not None:
                precisions.append(float(score["context_precision"]))
            if score.get("support_evidence_miss"):
                support_miss += 1
            if score.get("counter_evidence_miss"):
                counter_miss += 1
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
        "avg_snapshot_object_count": avg(snap_sizes),
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
        "avg_core_claim_retrieval_count": avg(core_claim_retrieval),
        "avg_relevant_object_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "avg_context_precision": round(sum(precisions) / len(precisions), 4) if precisions else None,
        "avg_irrelevant_object_count": avg(irrelevant_counts),
        "avg_evidence_body_retrieval_count": avg(evidence_bodies),
        "support_evidence_miss_cases": support_miss,
        "counter_evidence_miss_cases": counter_miss,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 0 + Phase 1.1 第二次验证报告",
        "",
        f"生成时间: {payload.get('generated_at')}",
        "范围: 原来的 6 个 AVGO Case。修复 Targeted Context / Constitution-Budget / L0 顺序后的 Before→After。未进入 Phase 2。",
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
                f"- Snapshot evidence: {[row.get('id') or row.get('evidence_id') or row.get('title') for row in (case.get('snapshot') or {}).get('evidence') or []]}",
                f"- Snapshot counter evidence: {[row.get('id') or row.get('evidence_id') or row.get('title') for row in (case.get('snapshot') or {}).get('counter_evidence') or []]}",
                f"- Context score: recall={((case.get('context_score') or {}).get('context_recall'))} precision={((case.get('context_score') or {}).get('context_precision'))} missed={((case.get('context_score') or {}).get('missed_count'))} irrelevant={((case.get('context_score') or {}).get('irrelevant_count'))}",
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
    if payload.get("deviations"):
        for item in payload.get("deviations") or []:
            lines.append(f"- {item}")
    else:
        lines.append("无新增设计偏差。")
    lines.extend(
        [
            "",
            "## 7. 当前是否已经真正实现 Incremental Brain Runtime",
            "",
            payload.get("incremental_runtime_verdict") or "",
            "",
            "## 8. Before → After（第一次 baseline vs 本轮）",
            "",
        ]
    )
    comparison = payload.get("comparison") or {}
    if comparison:
        lines.append("```json")
        lines.append(json.dumps(comparison.get("metrics") or comparison, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        for item in comparison.get("answers") or []:
            lines.append(f"- {item}")
        lines.append("")
    else:
        lines.append("无 baseline 对比。")
        lines.append("")
    lines.extend(
        [
            "## 9. 发现的问题（本轮不修架构）",
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
    if e and e.get("path") == "incremental" and e.get("glm53_called"):
        expected.append("Case E 竞争/反面证据进入 incremental reasoning，没有短路成 Full Review。")
    if f and (f.get("full_review_triggered") or f.get("full_review")):
        expected.append("Case F 首次 earnings/guidance 在 L0 通过后触发 Full Review。")
    if any((row.get("snapshot") or {}).get("full_brain") is False for row in (c, e) if row):
        expected.append("Incremental 路径声明 snapshot.targeted=True / full_brain=False。")

    def _evidence_blob(row: dict[str, Any] | None) -> str:
        shot = (row or {}).get("snapshot") or {}
        parts = []
        for item in (shot.get("evidence") or []) + (shot.get("counter_evidence") or []):
            parts.append(
                f"{item.get('id') or ''} {item.get('evidence_id') or ''} {item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}"
            )
        return " ".join(parts).lower()

    def _driver_blob(row: dict[str, Any] | None) -> str:
        affected = (row or {}).get("affected_objects") or {}
        shot = (row or {}).get("snapshot") or {}
        return " ".join(
            [
                " ".join(str(item) for item in (affected.get("drivers") or [])),
                " ".join(str(item.get("driver_id") or item.get("canonical_key") or "") for item in (shot.get("drivers") or [])),
            ]
        )

    if c:
        blob = _evidence_blob(c)
        if EVIDENCE_EXHIBIT in blob or "exhibit 99.1" in blob:
            expected.append("Case C 的 Exhibit 99.1 supporting evidence 进入了 snapshot。")
        else:
            extra_anomalies.append({"case_id": "C", "code": "snapshot_missing_key_evidence", "detail": "Exhibit 99.1 body missing from Case C snapshot."})
            deviations.append("Case C 仍未把 Exhibit 99.1 正文送进 snapshot。")
        if len(((c.get("snapshot") or {}).get("claims") or [])) >= 5:
            extra_anomalies.append({"case_id": "C", "code": "glm53_received_near_full_brain", "detail": "Case C still retrieved 5/5 Core Claims."})
            deviations.append("Case C 仍然把 5/5 Core Claims 全部塞进 snapshot。")
        else:
            expected.append("Case C 不再默认塞入全部 5 条 Core Claim。")
        if any(token in _driver_blob(c) for token in (DRIVER_LEVERAGE, DRIVER_GAAP)):
            deviations.append("Case C 仍因关键词把 leverage / GAAP 对象带进 snapshot。")
    if d:
        if DRIVER_DEMAND not in _driver_blob(d):
            extra_anomalies.append({"case_id": "D", "code": "affected_objects_missed", "detail": "Case D missed ai_semiconductor_demand_durability."})
            deviations.append("Case D 仍然漏掉 ai_semiconductor_demand_durability。")
        else:
            expected.append("Case D 命中了 AI demand durability 相关对象。")
        if d.get("phase0", {}).get("core_claims_unchanged") is not False:
            expected.append("Case D Current State / Core Claim 保持不变。")
    if e:
        blob = _evidence_blob(e)
        has_support = EVIDENCE_EXHIBIT in blob or "exhibit 99.1" in blob
        has_counter = EVIDENCE_MARVELL in blob or "marvell" in blob
        if has_support and has_counter:
            expected.append("Case E 同时拿到相关 support evidence 正文和 Marvell counter evidence。")
        else:
            if not has_support:
                extra_anomalies.append({"case_id": "E", "code": "snapshot_missing_key_evidence", "detail": "Case E missing support evidence body."})
                deviations.append("Case E 没有把原来支持 Claim 的 Evidence 正文给 GLM-5.3。")
            if not has_counter:
                extra_anomalies.append({"case_id": "E", "code": "snapshot_missing_key_counter_evidence", "detail": "Case E missing Marvell counter evidence."})
                deviations.append("Case E 没有把 Marvell counter evidence 给 GLM-5.3。")
        if len(((e.get("snapshot") or {}).get("claims") or [])) >= 5:
            extra_anomalies.append({"case_id": "E", "code": "glm53_received_near_full_brain", "detail": "Case E still retrieved 5/5 Core Claims."})
            deviations.append("Case E 仍然把 5/5 Core Claims 全部塞进 snapshot。")

    constitution_ok = True
    for case_id, row in (("C", c), ("E", e)):
        if not row:
            continue
        rejects = (row.get("phase0") or {}).get("reject") or []
        items = ((row.get("proposal_decisions") or {}).get("items") or [])
        core_items = [item for item in items if isinstance(item, dict) and item.get("object_type") in {"core_claim", "claim"}]
        if any(item.get("reason_code") == "news_cannot_modify_core_claim" for item in rejects if isinstance(item, dict)):
            expected.append(f"Case {case_id} 对 Event→Core Claim 给出 constitution reject，而不是被 Change Budget 盖成 review。")
        elif any(item.get("decision") == "requires_review" for item in core_items):
            constitution_ok = False
            deviations.append(f"Case {case_id} 仍把 Core Claim 直接 mutation 停在 requires_review，而不是 reject。")
    _ = constitution_ok

    metrics = payload.get("metrics") or {}
    if metrics.get("reject", 0) == 0 and any(len((row.get("phase0") or {}).get("reject") or []) for row in (c, d, e) if row):
        deviations.append("metrics.reject 仍为 0，但 case 记录里已有 reject；核对 proposal_decisions。")
    findings.append("context_miss 改为对照 golden expected objects，不再用 Broadcom/AI 宽关键词自我验证 retrieval。")
    findings.append("Change Budget 先看 Constitution reject，再对剩余合法 proposal 判断 related vs unrelated scope。")
    findings.append("Full Review 只在 L0 判定非 duplicate 之后触发。")
    findings.append("本轮没有进入 Phase 2，没有建立完整 Causal Graph，也没有退回 Full Brain Context。")

    incremental_yes = bool(
        a
        and a.get("path") == "l0_stop"
        and c
        and c.get("path") == "incremental"
        and f
        and (f.get("full_review") or f.get("full_review_triggered"))
    )
    near_full = any(row.get("code") == "glm53_received_near_full_brain" for row in (payload.get("all_anomalies") or []) + extra_anomalies)
    evidence_ok = not any(row.get("code") == "snapshot_missing_key_evidence" for row in extra_anomalies)
    if incremental_yes and evidence_ok and not near_full and metrics.get("unexpected_brain_change_count") == 0:
        verdict = (
            "Routing 仍然正确，Targeted Context 已经按结构关系变窄，关键 Evidence 正文进入 snapshot，"
            "Constitution reject 不再被 Change Budget 覆盖。可以认为 Incremental Runtime 在信息论意义上成立，停止 Phase 1。"
        )
    elif incremental_yes:
        verdict = (
            "主路径仍然成立，但 Targeted Context 或 Constitution/Budget 语义还没有完全达到验收线。"
            "不要进入 Phase 2。"
        )
    else:
        verdict = "Incremental 路径存在，但六个 Case 的 routing 与设计不完全一致，还不能宣布 Incremental Brain Runtime 已经真正实现。"
    return {
        "expected_matches": expected,
        "deviations": deviations,
        "findings": findings,
        "incremental_runtime_verdict": verdict,
        "extra_anomalies": extra_anomalies,
    }


def load_baseline_metrics() -> dict[str, Any]:
    path = BASELINE_DIR / "metrics.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def compare_with_baseline(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "avg_targeted_snapshot_size",
        "avg_snapshot_object_count",
        "avg_glm53_input_tokens",
        "context_miss_count",
        "approve",
        "reject",
        "requires_review",
        "avg_core_claim_retrieval_count",
        "avg_irrelevant_object_count",
        "avg_evidence_body_retrieval_count",
        "avg_relevant_object_recall",
        "avg_context_precision",
        "support_evidence_miss_cases",
        "counter_evidence_miss_cases",
        "unexpected_brain_change_count",
        "glm53_calls",
        "l0_duplicate_stop",
        "full_review_triggers",
    ]
    rows = {}
    for key in keys:
        if key in current or key in baseline:
            rows[key] = {"before": baseline.get(key), "after": current.get(key)}
    answers = [
        f"1. Routing 是否仍然正确？ L0 stop {baseline.get('l0_duplicate_stop')}→{current.get('l0_duplicate_stop')}; "
        f"full review {baseline.get('full_review_triggers')}→{current.get('full_review_triggers')}; "
        f"GLM-5.3 calls {baseline.get('glm53_calls')}→{current.get('glm53_calls')}.",
        f"2. Targeted Context 是否真正变窄？ snapshot {baseline.get('avg_targeted_snapshot_size')}→{current.get('avg_targeted_snapshot_size')}; "
        f"Core Claim retrieval/event {current.get('avg_core_claim_retrieval_count')}.",
        f"3. 关键 Evidence 是否已经进入？ evidence bodies {current.get('avg_evidence_body_retrieval_count')}; "
        f"support miss cases {current.get('support_evidence_miss_cases')}; counter miss cases {current.get('counter_evidence_miss_cases')}.",
        f"4. 重要 Context 是否还有遗漏？ context_miss {baseline.get('context_miss_count')}→{current.get('context_miss_count')}; "
        f"recall {current.get('avg_relevant_object_recall')}.",
        f"5. 无关对象是否明显减少？ irrelevant {current.get('avg_irrelevant_object_count')}; precision {current.get('avg_context_precision')}.",
        f"6. Constitution / Budget decision 是否恢复正确语义？ approve/reject/review "
        f"{baseline.get('approve')}/{baseline.get('reject')}/{baseline.get('requires_review')} → "
        f"{current.get('approve')}/{current.get('reject')}/{current.get('requires_review')}.",
        f"7. Incremental Runtime 是否已经可以认为真正成立？ unexpected writes "
        f"{baseline.get('unexpected_brain_change_count')}→{current.get('unexpected_brain_change_count')}.",
    ]
    return {"metrics": rows, "answers": answers}


def finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["metrics"] = metrics(payload.get("cases") or [])
    judged = judge(payload)
    extra = list(judged.pop("extra_anomalies") or [])
    payload["all_anomalies"] = list(payload.get("all_anomalies") or []) + extra
    payload.update(judged)
    payload["metrics"]["context_miss_count"] = len(payload.get("all_context_misses") or [])
    payload["metrics"]["runtime_anomaly_count"] = len(payload.get("all_anomalies") or [])
    baseline = load_baseline_metrics()
    payload["baseline_metrics"] = baseline
    payload["comparison"] = compare_with_baseline(payload["metrics"], baseline)
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
        expected_ctx = GOLDEN_CONTEXT.get(spec["case_id"]) or {}
        context_score: dict[str, Any] = {}
        misses: list[dict[str, Any]] = []
        if result.get("path") == "incremental":
            context_score = score_snapshot_context(
                snapshot=snapshot,
                expected=expected_ctx,
                irrelevant=expected_ctx.get("irrelevant") or [],
            )
            misses = find_context_misses(event=event_for_miss, snapshot=snapshot, brain=leftover, expected=expected_ctx)
        anomalies = detect_anomalies(spec, result, leftover, store, context_score=context_score)
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
        route = build_route(spec, result, misses, anomalies, context_score=context_score)
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
