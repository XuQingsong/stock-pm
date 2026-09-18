"""Mini Benchmark. Compact frozen-input comparison. Does not touch production Brain."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from stock_pm.brain.claim_integrity import reject_unknown_ids
from stock_pm.research.llm_reason import compact_text, dump_user

from .freeze import compact_mini_pack, freeze_benchmark_input
from .metrics import (
    count_unsupported_numbers,
    empty_human_scores,
    estimate_cost,
)
from .profiles import completer_for, mini_profiles


OUT_DEFAULT = Path("artifacts/brain_mini_benchmark")

ROUND1_EVENT = {
    "event_id": "avgo_custom_silicon",
    "title": "Hyperscaler internal custom AI silicon",
    "summary": "Google / Meta accelerate internally designed custom AI silicon, reducing reliance on external/custom silicon partners.",
}

ROUND2_EVENTS = {
    "AVGO": [
        {"event_id": "avgo_r2_e1", "title": "Hyperscaler AI capex up", "summary": "hyperscaler AI capex significantly increases"},
        {"event_id": "avgo_r2_e2", "title": "Internal ASIC accelerates", "summary": "Google/Meta internally designed ASIC accelerates"},
        {"event_id": "avgo_r2_e3", "title": "Power/deployment delay", "summary": "datacenter power/deployment delay"},
    ],
    "LITE": [
        {"event_id": "lite_r2_e1", "title": "800G/1.6T demand up", "summary": "800G/1.6T hyperscaler demand accelerates"},
        {"event_id": "lite_r2_e2", "title": "Peer capacity expansion", "summary": "Coherent/Fabrinet capacity expansion"},
        {"event_id": "lite_r2_e3", "title": "Optical pricing pressure", "summary": "optical pricing pressure / inventory build"},
    ],
}

MINI_HUMAN_SCORES = {
    "driver_recall": None,
    "core_claim_quality": None,
    "event_transmission": None,
    "counter_reasoning": None,
    "evidence_discipline": None,
    "unsupported_assertion_rate": None,
    "overall": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prompt(name: str) -> str:
    return files("stock_pm").joinpath(f"brain/benchmark/prompts/{name}").read_text(encoding="utf-8").strip()


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)


def _call(completer: Any, *, step: str, prompt: str, user: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = completer.complete_json(system=_prompt(prompt), user=dump_user(user))
    if not isinstance(result, dict):
        result = {"status": "failed", "payload": None, "llm_status": "failed", "error": "non-dict"}
    audit = {
        "step": step,
        "llm_called": result.get("llm_called"),
        "llm_status": result.get("llm_status") or result.get("status"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "latency_ms": result.get("latency_ms"),
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "error": result.get("error"),
    }
    payload = result.get("payload") if result.get("status") == "ok" else None
    return (payload if isinstance(payload, dict) else None), audit


def _ids(values: Any, allowed: set[str]) -> tuple[list[str], list[str]]:
    return reject_unknown_ids(values, allowed)


def _score_round1(pack: dict[str, Any], drivers: dict[str, Any] | None, claims: dict[str, Any] | None, event: dict[str, Any] | None, audits: list[dict[str, Any]], model: str) -> dict[str, Any]:
    allowed = set(pack.get("allowed_evidence_ids") or [])
    blob = " ".join(str(row.get("fact") or "") for row in pack.get("evidence") or [])
    value_drivers = [row for row in (drivers or {}).get("value_drivers") or [] if isinstance(row, dict)][:8]
    core_claims = [row for row in (claims or {}).get("core_claims") or [] if isinstance(row, dict)][:3]
    invalid: list[str] = []
    unsupported: list[str] = []
    cleaned_drivers = []
    for row in value_drivers:
        kept, bad = _ids(row.get("evidence_ids") or [], allowed)
        invalid.extend(bad)
        unsupported.extend(count_unsupported_numbers(" ".join(str(row.get(k) or "") for k in ("driver", "why_it_matters")), blob))
        cleaned_drivers.append(
            {
                "driver": compact_text(row.get("driver") or row.get("driver_name") or "", 160),
                "why_it_matters": compact_text(row.get("why_it_matters") or "", 180),
                "financial_link": compact_text(row.get("financial_link") or "", 40),
                "uncertainty": compact_text(row.get("uncertainty") or "", 16),
                "evidence_ids": kept,
            }
        )
    cleaned_claims = []
    for row in core_claims:
        kept, bad = _ids(row.get("evidence_ids") or [], allowed)
        invalid.extend(bad)
        statement = compact_text(row.get("claim") or row.get("statement") or "", 220)
        unsupported.extend(count_unsupported_numbers(statement, blob))
        cleaned_claims.append(
            {
                "claim": statement,
                "why_core": compact_text(row.get("why_core") or "", 180),
                "strongest_support": compact_text(row.get("strongest_support") or "", 180),
                "strongest_counter": compact_text(row.get("strongest_counter") or "", 180),
                "missing_evidence": compact_text(row.get("missing_evidence") or "", 160),
                "evidence_ids": kept,
            }
        )
    event_row = event.get("event") if isinstance(event, dict) and isinstance(event.get("event"), dict) else (event if isinstance(event, dict) else {})
    tokens_in = sum(int(row.get("input_tokens") or 0) for row in audits)
    tokens_out = sum(int(row.get("output_tokens") or 0) for row in audits)
    latency = sum(int(row.get("latency_ms") or 0) for row in audits)
    failures = [row for row in audits if row.get("llm_status") not in {"ok"}]
    return {
        "drivers": cleaned_drivers,
        "core_claims": cleaned_claims,
        "event": {
            "event_id": ROUND1_EVENT["event_id"],
            "affected_drivers": [compact_text(item, 80) for item in (event_row.get("affected_drivers") or []) if str(item).strip()][:6],
            "affected_claims": [compact_text(item, 80) for item in (event_row.get("affected_claims") or []) if str(item).strip()][:6],
            "direction": compact_text(event_row.get("direction") or "", 16),
            "strength": compact_text(event_row.get("strength") or "", 16),
            "transmission_chain": compact_text(event_row.get("transmission_chain") or "", 220),
            "short_term_impact": compact_text(event_row.get("short_term_impact") or "", 180),
            "long_term_impact": compact_text(event_row.get("long_term_impact") or "", 180),
            "base_case_change": compact_text(event_row.get("base_case_change") or "", 8),
            "scenario_only": compact_text(event_row.get("scenario_only") or "", 8),
            "confidence": compact_text(event_row.get("confidence") or "", 12),
        },
        "metrics": {
            "driver_count": len(cleaned_drivers),
            "core_claim_count": len(cleaned_claims),
            "invalid_evidence_ids": list(dict.fromkeys(invalid)),
            "invalid_evidence_id_count": len(list(dict.fromkeys(invalid))),
            "unsupported_assertions": list(dict.fromkeys(unsupported))[:12],
            "unsupported_assertion_count": len(list(dict.fromkeys(unsupported))),
            "consistency_failures": len(failures),
            "latency_ms": latency,
            "input_tokens": tokens_in or None,
            "output_tokens": tokens_out or None,
            "estimated_cost": estimate_cost(model, tokens_in, tokens_out),
            "human_scores": dict(MINI_HUMAN_SCORES),
        },
    }


def run_round1_model(profile: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    if not profile.get("api_key_present"):
        empty_audits = [{"step": step, "llm_called": False, "llm_status": "skipped", "error": "missing API key", "latency_ms": 0} for step in ("drivers", "claims", "event")]
        scored = _score_round1(pack, {}, {}, {}, empty_audits, str(profile.get("model") or ""))
        return {
            "generated_at": _now(),
            "round": 1,
            "ticker": pack.get("ticker"),
            "model": profile.get("model"),
            "file_label": profile.get("file_label"),
            "freeze_hash": pack.get("freeze_hash"),
            "prompt_input_hash": pack.get("prompt_input_hash"),
            "searched": False,
            "note": "API key missing; model not called",
            **scored,
            "llm_calls": empty_audits,
        }
    completer = completer_for(profile)
    base = {
        "ticker": pack.get("ticker"),
        "snapshot_id": pack.get("snapshot_id"),
        "evidence_set_id": pack.get("evidence_set_id"),
        "related_entities": pack.get("related_entities") or [],
        "evidence": pack.get("evidence") or [],
        "rules": ["Do not search.", "Cite evidence[].id only.", "No invented numbers.", "Short fields only."],
    }
    audits: list[dict[str, Any]] = []
    drivers, a1 = _call(completer, step="drivers", prompt="mini_drivers.txt", user=base)
    audits.append(a1)
    claims, a2 = _call(
        completer,
        step="claims",
        prompt="mini_claims.txt",
        user={**base, "value_drivers": (drivers or {}).get("value_drivers") or []},
    )
    audits.append(a2)
    event, a3 = _call(
        completer,
        step="event",
        prompt="mini_event.txt",
        user={
            **base,
            "value_drivers": (drivers or {}).get("value_drivers") or [],
            "core_claims": (claims or {}).get("core_claims") or [],
            "event": ROUND1_EVENT,
        },
    )
    audits.append(a3)
    scored = _score_round1(pack, drivers, claims, event, audits, str(profile.get("model") or ""))
    return {
        "generated_at": _now(),
        "round": 1,
        "ticker": pack.get("ticker"),
        "model": profile.get("model"),
        "file_label": profile.get("file_label"),
        "provider": profile.get("provider"),
        "base_url": profile.get("base_url"),
        "freeze_hash": pack.get("freeze_hash"),
        "prompt_input_hash": pack.get("prompt_input_hash"),
        "searched": False,
        **scored,
        "llm_calls": audits,
    }


def run_round1(
    *,
    store: Any = None,
    research: Any = None,
    settings: Any = None,
    out_dir: Path = OUT_DEFAULT,
) -> dict[str, Any]:
    from stock_pm.config import Settings

    config = settings or Settings()
    frozen = freeze_benchmark_input(store, research, "AVGO")
    pack = compact_mini_pack(frozen)
    profiles = mini_profiles(config)
    results: dict[str, dict[str, Any]] = {}
    hashes = set()
    for profile in profiles:
        print("mini round1", profile.get("file_label"), profile.get("model"), flush=True)
        payload = run_round1_model(profile, pack)
        hashes.add(payload.get("prompt_input_hash"))
        results[str(profile.get("file_label"))] = payload
        _write(out_dir / f"avgo_{profile.get('file_label')}.json", payload)
    if len(hashes) != 1:
        raise RuntimeError("mini round1 models did not share prompt_input_hash")
def _round1_summary(pack: dict[str, Any], profiles: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": _now(),
        "round": 1,
        "ticker": "AVGO",
        "event": ROUND1_EVENT,
        "freeze_hash": pack.get("freeze_hash"),
        "prompt_input_hash": pack.get("prompt_input_hash"),
        "snapshot_id": pack.get("snapshot_id"),
        "evidence_set_id": pack.get("evidence_set_id"),
        "evidence_count": len(pack.get("evidence") or []),
        "searched": False,
        "winner": None,
        "note": "No automatic winner. Human scores remain null. Round 2 waits for manual Top 2.",
        "models": [
            {
                "file_label": profile.get("file_label"),
                "model": profile.get("model"),
                "role": profile.get("role"),
            }
            for profile in profiles
        ],
        "by_model": {
            label: {
                "model": payload.get("model"),
                "driver_count": (payload.get("metrics") or {}).get("driver_count"),
                "core_claim_count": (payload.get("metrics") or {}).get("core_claim_count"),
                "invalid_evidence_ids": (payload.get("metrics") or {}).get("invalid_evidence_ids"),
                "unsupported_assertions": (payload.get("metrics") or {}).get("unsupported_assertions"),
                "latency_ms": (payload.get("metrics") or {}).get("latency_ms"),
                "input_tokens": (payload.get("metrics") or {}).get("input_tokens"),
                "output_tokens": (payload.get("metrics") or {}).get("output_tokens"),
                "estimated_cost": (payload.get("metrics") or {}).get("estimated_cost"),
                "consistency_failures": (payload.get("metrics") or {}).get("consistency_failures"),
                "drivers": [row.get("driver") for row in payload.get("drivers") or []],
                "core_claims": [row.get("claim") for row in payload.get("core_claims") or []],
                "event_direction": (payload.get("event") or {}).get("direction"),
                "event_transmission": (payload.get("event") or {}).get("transmission_chain"),
                "human_scores": (payload.get("metrics") or {}).get("human_scores") or empty_human_scores(),
            }
            for label, payload in results.items()
        },
        "human_scores": dict(MINI_HUMAN_SCORES),
        "round2": {
            "status": "waiting_for_manual_top2",
            "tickers": ["AVGO", "LITE"],
            "events": ROUND2_EVENTS,
        },
    }


def run_round1(
    *,
    store: Any = None,
    research: Any = None,
    settings: Any = None,
    out_dir: Path = OUT_DEFAULT,
    only: str | None = None,
) -> dict[str, Any]:
    from stock_pm.config import Settings

    config = settings or Settings()
    frozen = freeze_benchmark_input(store, research, "AVGO")
    pack = compact_mini_pack(frozen)
    profiles = mini_profiles(config)
    results: dict[str, dict[str, Any]] = {}
    if only:
        existing_dir = Path(out_dir)
        for profile in profiles:
            label = str(profile.get("file_label"))
            path = existing_dir / f"avgo_{label}.json"
            if path.exists() and label != only:
                results[label] = json.loads(path.read_text(encoding="utf-8"))
    hashes = set()
    for profile in profiles:
        label = str(profile.get("file_label"))
        if only and label != only:
            if label in results:
                hashes.add(results[label].get("prompt_input_hash"))
            continue
        print("mini round1", label, profile.get("model"), flush=True)
        payload = run_round1_model(profile, pack)
        hashes.add(payload.get("prompt_input_hash"))
        results[label] = payload
        _write(out_dir / f"avgo_{label}.json", payload)
    hashes.discard(None)
    if len(hashes) != 1:
        raise RuntimeError("mini round1 models did not share prompt_input_hash")
    summary = _round1_summary(pack, profiles, results)
    _write(out_dir / "round1_summary.json", summary)
    return {"summary": summary, "results": results}


def run_round2(
    *,
    models: list[str],
    store: Any = None,
    research: Any = None,
    settings: Any = None,
    out_dir: Path = OUT_DEFAULT,
) -> dict[str, Any]:
    raise RuntimeError(
        "Round 2 is gated until a human picks Top 2 models. "
        "Pass those labels after screening Round 1; do not auto-select a winner."
    )
