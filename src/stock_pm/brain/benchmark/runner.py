"""Run Driver / Claim / Event / Counter tests on a frozen Brain pack."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from stock_pm.brain.claim_integrity import reject_unknown_ids, strip_unbound_facts
from stock_pm.research.llm_reason import compact_text, complete_structured, dump_user

from .events import events_for
from .freeze import freeze_benchmark_input
from .metrics import driver_names, overlap_metrics, score_run
from .profiles import completer_for, model_profiles


OUT_DEFAULT = Path("artifacts/brain_benchmark")
TICKERS = ("AAPL", "AVGO", "LITE")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prompt(name: str) -> str:
    return files("stock_pm").joinpath(f"brain/benchmark/prompts/{name}").read_text(encoding="utf-8").strip()


def _call(completer: Any, *, step: str, prompt: str, user: dict[str, Any], allowed: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload, audit = complete_structured(
        completer,
        system=_prompt(prompt),
        user=dump_user(user),
        allowed_ids=allowed,
    )
    audit = dict(audit or {})
    audit["step"] = step
    return payload, audit


def _clean_claims(raw: dict[str, Any] | None, pack: dict[str, Any]) -> dict[str, Any]:
    allowed = set(pack.get("allowed_evidence_ids") or [])
    evidence = list(pack.get("validated_facts") or [])
    by_id = {str(row.get("id")): row for row in evidence if row.get("id")}
    out = []
    rejected = []
    for index, row in enumerate((raw or {}).get("core_claims") or []):
        if not isinstance(row, dict):
            continue
        support, bad_s = reject_unknown_ids(row.get("supporting_evidence_ids") or [], allowed)
        oppose, bad_o = reject_unknown_ids(row.get("opposing_evidence_ids") or [], allowed)
        rejected.extend(bad_s + bad_o)
        bound = [by_id[eid] for eid in support if eid in by_id]
        stripped = strip_unbound_facts(str(row.get("statement") or ""), bound)
        statement = stripped.get("statement") or compact_text(row.get("statement") or "", 600)
        if stripped.get("unsupported_tokens") and len(statement) < 24:
            statement = compact_text(row.get("title") or "Unverified decision variable", 160)
        out.append(
            {
                "claim_id": row.get("claim_id") or f"bench_{index+1}",
                "title": compact_text(row.get("title") or statement, 120),
                "statement": statement,
                "claim_subject": compact_text(row.get("claim_subject") or "", 80),
                "claim_dimension": compact_text(row.get("claim_dimension") or "", 80),
                "financial_driver": compact_text(row.get("financial_driver") or "", 80),
                "time_horizon": row.get("time_horizon"),
                "why_core": compact_text(row.get("why_core") or "", 240),
                "supporting_evidence_ids": support,
                "opposing_evidence_ids": oppose,
                "missing_evidence": [compact_text(item, 160) for item in (row.get("missing_evidence") or []) if str(item).strip()][:6],
                "unverified_detail": stripped.get("unverified_detail") or compact_text(row.get("unverified_detail") or "", 240),
            }
        )
        if len(out) >= 5:
            break
    return {"core_claims": out, "rejected_evidence_ids": list(dict.fromkeys(rejected))}


def run_model_on_pack(profile: dict[str, Any], pack: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    if not profile.get("api_key_present"):
        audits = [
            {
                "step": step,
                "llm_called": False,
                "llm_status": "skipped",
                "error": "STRONG_MODEL_API_KEY / DASHSCOPE_API_KEY missing",
                "model": profile.get("model"),
                "provider": profile.get("provider"),
                "input_tokens": None,
                "output_tokens": None,
                "latency_ms": 0,
            }
            for step in ("driver_discovery", "core_claim_test", "event_impact", "counter_reasoning")
        ]
        metrics = score_run(
            pack=pack,
            drivers={},
            claims={},
            events={},
            counters={},
            audits=audits,
            expected_event_ids=[str(row.get("event_id")) for row in events],
            model=str(profile.get("model") or ""),
        )
        return {
            "generated_at": _now(),
            "ticker": pack.get("ticker"),
            "model_label": profile.get("label"),
            "model": profile.get("model"),
            "provider": profile.get("provider"),
            "base_url": profile.get("base_url"),
            "role": profile.get("role"),
            "input_hash": pack.get("input_hash"),
            "snapshot_id": pack.get("snapshot_id"),
            "evidence_set_id": pack.get("evidence_set_id"),
            "run_id": pack.get("run_id"),
            "searched": False,
            "driver_discovery": {},
            "core_claims": [],
            "event_impact": {},
            "counter_reasoning": {},
            "metrics": metrics,
            "llm_calls": audits,
            "rejected_evidence_ids": [],
            "note": "STRONG_MODEL_API_KEY / DASHSCOPE_API_KEY missing; model not called",
        }
    completer = completer_for(profile)
    allowed = set(pack.get("allowed_evidence_ids") or [])
    audits: list[dict[str, Any]] = []
    user_base = {
        "ticker": pack.get("ticker"),
        "snapshot_id": pack.get("snapshot_id"),
        "evidence_set_id": pack.get("evidence_set_id"),
        "header": pack.get("header") or {},
        "related_entities": pack.get("related_entities") or [],
        "current_core_claims": pack.get("core_claims") or [],
        "evidence": pack.get("validated_facts") or [],
        "rules": [
            "Do not search.",
            "Use only this JSON.",
            "Cite evidence_id values from evidence[] only.",
            "Do not invent numbers.",
        ],
    }
    drivers, audit_a = _call(
        completer,
        step="driver_discovery",
        prompt="driver_discovery.txt",
        user=user_base,
        allowed=allowed,
    )
    audits.append(audit_a)
    claims_raw, audit_b = _call(
        completer,
        step="core_claim_test",
        prompt="core_claim_test.txt",
        user={**user_base, "value_drivers": (drivers or {}).get("value_drivers") or [], "core_drivers": (drivers or {}).get("core_drivers") or []},
        allowed=allowed,
    )
    audits.append(audit_b)
    claims = _clean_claims(claims_raw, pack)
    events_payload, audit_c = _call(
        completer,
        step="event_impact",
        prompt="event_impact.txt",
        user={
            **user_base,
            "core_drivers": (drivers or {}).get("core_drivers") or [],
            "core_claims": claims.get("core_claims") or pack.get("core_claims") or [],
            "events": events,
        },
        allowed=allowed,
    )
    audits.append(audit_c)
    counters, audit_d = _call(
        completer,
        step="counter_reasoning",
        prompt="counter_reasoning.txt",
        user={
            **user_base,
            "core_claims": claims.get("core_claims") or pack.get("core_claims") or [],
        },
        allowed=allowed,
    )
    audits.append(audit_d)
    metrics = score_run(
        pack=pack,
        drivers=drivers,
        claims=claims,
        events=events_payload,
        counters=counters,
        audits=audits,
        expected_event_ids=[str(row.get("event_id")) for row in events],
        model=str(profile.get("model") or ""),
    )
    return {
        "generated_at": _now(),
        "ticker": pack.get("ticker"),
        "model_label": profile.get("label"),
        "model": profile.get("model"),
        "provider": profile.get("provider"),
        "base_url": profile.get("base_url"),
        "role": profile.get("role"),
        "input_hash": pack.get("input_hash"),
        "snapshot_id": pack.get("snapshot_id"),
        "evidence_set_id": pack.get("evidence_set_id"),
        "run_id": pack.get("run_id"),
        "searched": False,
        "driver_discovery": drivers or {},
        "core_claims": claims.get("core_claims") or [],
        "event_impact": events_payload or {},
        "counter_reasoning": counters or {},
        "metrics": metrics,
        "llm_calls": audits,
        "rejected_evidence_ids": claims.get("rejected_evidence_ids") or [],
    }


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)


def run_benchmark(
    *,
    store: Any = None,
    research: Any = None,
    settings: Any = None,
    tickers: tuple[str, ...] = TICKERS,
    out_dir: Path = OUT_DEFAULT,
) -> dict[str, Any]:
    from stock_pm.config import Settings

    config = settings or Settings()
    profiles = model_profiles(config)
    frozen: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        frozen[ticker] = freeze_benchmark_input(store, research, ticker)
    results: dict[str, dict[str, dict[str, Any]]] = {ticker: {} for ticker in tickers}
    audit_rows: list[dict[str, Any]] = []
    for ticker in tickers:
        pack = frozen[ticker]
        events = events_for(ticker)
        by_label: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            print(
                "benchmark",
                ticker,
                profile.get("label"),
                profile.get("model"),
                "key" if profile.get("api_key_present") else "missing_key",
                flush=True,
            )
            payload = run_model_on_pack(profile, pack, events)
            if payload.get("input_hash") != pack.get("input_hash"):
                raise RuntimeError(f"input_hash drifted for {ticker} {profile.get('label')}")
            by_label[str(profile.get("label"))] = payload
        overlap = overlap_metrics({label: driver_names(row.get("driver_discovery")) for label, row in by_label.items()})
        for profile in profiles:
            label = str(profile.get("label"))
            payload = by_label[label]
            metrics = dict(payload.get("metrics") or {})
            metrics["driver_overlap"] = overlap.get("overlap") or {}
            metrics["unique_material_drivers"] = (overlap.get("unique_material_drivers") or {}).get(label) or []
            payload["metrics"] = metrics
            results[ticker][label] = payload
            for alias in profile.get("file_aliases") or [label]:
                _write(out_dir / f"{ticker.lower()}_{alias}.json", payload)
            audit_rows.append(
                {
                    "ticker": ticker,
                    "label": profile.get("label"),
                    "model": profile.get("model"),
                    "provider": profile.get("provider"),
                    "base_url": profile.get("base_url"),
                    "api_key_present": profile.get("api_key_present"),
                    "input_hash": pack.get("input_hash"),
                    "llm_calls": payload.get("llm_calls"),
                    "metrics": payload.get("metrics"),
                }
            )
    summary_models: dict[str, Any] = {}
    driver_sets: dict[str, list[str]] = {}
    for ticker, by_label in results.items():
        for label, payload in by_label.items():
            names = [
                compact_text(row.get("driver_name") or "", 80).lower()
                for row in (payload.get("driver_discovery") or {}).get("value_drivers") or []
                if isinstance(row, dict) and row.get("driver_name")
            ]
            driver_sets.setdefault(label, [])
            for name in names:
                if name not in driver_sets[label]:
                    driver_sets[label].append(name)
            summary_models.setdefault(label, [])
            summary_models[label].append(
                {
                    "ticker": ticker,
                    "model": payload.get("model"),
                    "metrics": payload.get("metrics"),
                    "input_hash": payload.get("input_hash"),
                    "core_claim_titles": [row.get("title") for row in payload.get("core_claims") or []],
                }
            )
    hashes = {frozen[ticker]["input_hash"] for ticker in tickers}
    summary = {
        "generated_at": _now(),
        "tickers": list(tickers),
        "models": [
            {
                "label": row.get("label"),
                "role": row.get("role"),
                "model": row.get("model"),
                "provider": row.get("provider"),
                "base_url": row.get("base_url"),
                "file_aliases": row.get("file_aliases"),
            }
            for row in profiles
        ],
        "same_input_per_ticker": {
            ticker: {
                "input_hash": frozen[ticker]["input_hash"],
                "snapshot_id": frozen[ticker].get("snapshot_id"),
                "evidence_set_id": frozen[ticker].get("evidence_set_id"),
                "evidence_count": len(frozen[ticker].get("allowed_evidence_ids") or []),
                "core_claim_count": len(frozen[ticker].get("core_claims") or []),
            }
            for ticker in tickers
        },
        "driver_overlap": overlap_metrics(driver_sets),
        "by_model": summary_models,
        "winner": None,
        "note": "No automatic winner. Human scores remain null.",
    }
    strong_missing = [
        row.get("label") for row in profiles if row.get("role") == "strong" and not row.get("api_key_present")
    ]
    model_audit = {
        "generated_at": _now(),
        "gateway": "stock_pm.llm.complete_json via SettingsCompleter / complete_structured",
        "strong_connect": {
            "protocol": "OpenAI-compatible POST {base_url}/chat/completions",
            "auth": "Authorization: Bearer STRONG_MODEL_API_KEY or DASHSCOPE_API_KEY",
            "base_url_example": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_ids": {
                "qwen3.8-max": "qwen3.8-max",
                "glm-5.3": "glm-5.3",
                "kimi-k3": "kimi-k3",
            },
            "thinking": "glm-5.3 and kimi-k3 keep native thinking; do not send enable_thinking=false.",
        },
        "production_model_unchanged": True,
        "searched": False,
        "missing_strong_key_labels": strong_missing,
        "calls": audit_rows,
        "input_hashes": {ticker: frozen[ticker]["input_hash"] for ticker in tickers},
        "distinct_pack_hashes": len(hashes),
    }
    _write(out_dir / "benchmark_summary.json", summary)
    _write(out_dir / "model_audit.json", model_audit)
    return {"summary": summary, "audit": model_audit, "results": results}
