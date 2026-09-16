"""Freeze one Research Snapshot per official PM/Judge run.

Valuation and PM reasoning may only read this frozen object. They must not
mix latest_pack + old_market_price + fixture valuation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from .errors import FixtureRejectedError
from .extract import to_number
from .ids import new_id
from .sources import DictPackSource


TEST_TICKERS = {"ZZZT", "TEST", "FIXTURE"}
TEST_TICKER_RE = re.compile(r"^(TEST|ZZZ|FIX|FIXTURE)", re.I)
VALUATION_INPUT_VERSION = "sprint56-pack-market-assumptions-v1"
METHOD_VERSIONS = {
    "complete_bridge": "sprint46-complete-bridge-v1",
    "eps_runway": "eps-runway-trailing-pe-v1",
    "forward_eps_anchor": "forward-eps-anchor-v1",
    "normalized_earnings": "energy-normalized-earnings-v1",
    "fcf": "fcf-yield-v1",
    "operating_only": "operating-only-insufficient-v1",
    "insufficient": "insufficient-inputs-v1",
}
FIXTURE_SOURCES = {"fixture", "test", "demo", "sample", "local_sample"}
MARKET_PROSE_RE = re.compile(
    r"market implied|implied growth|spot vs (?:base|bull)|market disagreement|market appears to price",
    re.I,
)


def fixture_allowed() -> bool:
    env = (os.getenv("APP_ENV") or "").strip().lower()
    if env in {"production", "prod"}:
        return False
    if env == "test":
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


def is_test_ticker(ticker: str | None) -> bool:
    symbol = str(ticker or "").upper().strip()
    return symbol in TEST_TICKERS or bool(TEST_TICKER_RE.match(symbol))


def source_is_fixture(source: Any, pack: dict[str, Any] | None = None, fundamentals: dict[str, Any] | None = None) -> bool:
    if isinstance(source, DictPackSource) or getattr(source, "is_fixture", False):
        return True
    row = pack or {}
    if row.get("is_fixture") is True:
        return True
    tokens = [
        str(row.get("source") or ""),
        str(((row.get("source_refs") or {}) if isinstance(row.get("source_refs"), dict) else {}).get("source") or ""),
        str((fundamentals or {}).get("source") or ""),
        str(((row.get("company_profile") or {}) if isinstance(row.get("company_profile"), dict) else {}).get("source") or ""),
    ]
    if (fundamentals or {}).get("is_fixture") is True:
        return True
    return any(token.strip().lower() in FIXTURE_SOURCES for token in tokens)


def pack_has_production_content(pack: dict[str, Any] | None) -> bool:
    row = pack or {}
    if row.get("is_fixture"):
        return False
    profile = row.get("company_profile") or {}
    return bool(
        row.get("earnings_history")
        or profile.get("revenue_ttm")
        or profile.get("eps_ttm")
        or profile.get("last_close")
    )


def reject_fixture_write(ticker: str, *, is_fixture: bool, existing: dict[str, Any] | None = None) -> None:
    symbol = str(ticker or "").upper()
    if not is_fixture:
        return
    if pack_has_production_content(existing) and existing.get("is_fixture") is False:
        raise FixtureRejectedError(f"fixture cannot overwrite production pack for {symbol}")
    if not fixture_allowed():
        raise FixtureRejectedError(f"fixture source rejected outside test for {symbol}")


def _plain(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _hash_inputs(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_plain(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def pack_spot(pack: dict[str, Any] | None) -> tuple[float | None, str | None]:
    profile = (pack or {}).get("company_profile") or {}
    spot = to_number(profile.get("last_close"))
    closes = profile.get("recent_closes") or []
    timestamp = None
    if isinstance(closes, list) and closes:
        last = closes[-1] if isinstance(closes[-1], dict) else {}
        timestamp = last.get("session_date") or last.get("bar_time") or last.get("timestamp")
    timestamp = timestamp or profile.get("last_close_at") or profile.get("market_data_timestamp")
    refs = (pack or {}).get("source_refs") or {}
    timestamp = timestamp or refs.get("daily_price_bars_as_of")
    return spot, str(timestamp) if timestamp else None


def pack_latest_report_date(pack: dict[str, Any] | None) -> str | None:
    dates = []
    for row in (pack or {}).get("earnings_history") or []:
        if not isinstance(row, dict):
            continue
        value = row.get("report_date") or row.get("period_end")
        if value:
            dates.append(str(value))
    return max(dates) if dates else None


def valuation_method_version(valuation: dict[str, Any] | None) -> str:
    row = valuation or {}
    explicit = row.get("valuation_method_version") or (row.get("calibration_json") or {}).get("valuation_method_version")
    if explicit:
        return str(explicit)
    eps_method = row.get("eps_method") or (row.get("calibration_json") or {}).get("eps_method")
    if not eps_method:
        derivation = str(((row.get("base_case") or {}).get("eps_derivation") or "")).lower()
        if "complete bridge" in derivation:
            eps_method = "complete_bridge"
        elif "ttm eps runway" in derivation or "runway" in derivation:
            eps_method = "eps_runway"
        else:
            eps_method = row.get("method") or (row.get("calibration_json") or {}).get("method") or "unknown"
    return METHOD_VERSIONS.get(str(eps_method), f"{eps_method}-v1")


def market_comparison_for(spot: float | None) -> dict[str, Any]:
    if spot in (None, 0):
        return {
            "market_comparison_status": "unavailable",
            "reason": "spot_price_missing",
            "spot_price": None,
        }
    return {
        "market_comparison_status": "available",
        "reason": None,
        "spot_price": spot,
    }


def apply_missing_spot_guard(reasoning: dict[str, Any] | None, *, spot: float | None) -> dict[str, Any]:
    """If snapshot.spot_price is missing, forbid market implied / disagreement / spot vs cases."""
    reasoning = reasoning if isinstance(reasoning, dict) else {}
    status = market_comparison_for(spot)
    reasoning["market_comparison_status"] = status["market_comparison_status"]
    reasoning["market_comparison_reason"] = status["reason"]
    if status["market_comparison_status"] != "unavailable":
        return reasoning
    reasoning["market_disagreement"] = []
    golden = reasoning.get("golden_answers") if isinstance(reasoning.get("golden_answers"), dict) else {}
    if golden:
        golden = dict(golden)
        golden["market_disagreement"] = []
        if MARKET_PROSE_RE.search(str(golden.get("market_worry") or "")):
            golden["market_worry"] = "market_comparison_status=unavailable; spot_price_missing"
        reasoning["golden_answers"] = golden
    return reasoning


def _row_ticker(row: dict[str, Any] | None) -> str:
    item = row or {}
    return str(item.get("ticker") or item.get("symbol") or "").upper().strip()


def integrity_reasons(live: dict[str, Any], *, is_fixture: bool) -> list[str]:
    reasons: list[str] = []
    symbol = str(live.get("ticker") or "").upper()
    pack = live.get("pack") or {}
    pack_ticker = _row_ticker(pack) or symbol
    if pack_ticker and pack_ticker != symbol:
        reasons.append(f"pack ticker {pack_ticker} != snapshot ticker {symbol}")
    for row in live.get("evidence") or []:
        other = _row_ticker(row)
        if other and other != symbol:
            reasons.append(f"evidence ticker {other} != {symbol}")
            break
    for row in live.get("assumptions") or []:
        other = _row_ticker(row)
        if other and other != symbol:
            reasons.append(f"assumption ticker {other} != {symbol}")
            break
    valuation = live.get("valuation") if isinstance(live.get("valuation"), dict) else None
    if valuation and valuation.get("status") != "missing":
        other = _row_ticker(valuation)
        if other and other != symbol:
            reasons.append(f"valuation ticker {other} != {symbol}")
        prev_snap = str(valuation.get("snapshot_id") or "").strip()
        if prev_snap:
            reasons.append("live latest valuation belongs to another snapshot and cannot be mixed into this freeze")
    thesis = live.get("thesis") if isinstance(live.get("thesis"), dict) else None
    if thesis and thesis.get("status") != "missing":
        other = _row_ticker(thesis)
        if other and other != symbol:
            reasons.append(f"thesis ticker {other} != {symbol}")
    if is_fixture and not fixture_allowed():
        reasons.append("fixture source rejected outside test")
    if is_fixture and not is_test_ticker(symbol) and not fixture_allowed():
        reasons.append("fixture row cannot bind a production ticker")
    return reasons


def classify_target_change(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    prev = previous or {}
    curr = current or {}
    prev_snap = str(prev.get("snapshot_id") or (prev.get("calibration_json") or {}).get("snapshot_id") or "")
    curr_snap = str(curr.get("snapshot_id") or (curr.get("calibration_json") or {}).get("snapshot_id") or "")
    snapshot_changed = bool(prev_snap and curr_snap and prev_snap != curr_snap)
    prev_method = valuation_method_version(prev)
    curr_method = valuation_method_version(curr)
    methodology_change = prev_method != curr_method
    prev_pack = (prev.get("calibration_json") or {}).get("pack_fingerprint") or prev.get("pack_fingerprint")
    curr_pack = (curr.get("calibration_json") or {}).get("pack_fingerprint") or curr.get("pack_fingerprint")
    prev_rev = to_number(((prev.get("base_case") or {}).get("revenue")))
    curr_rev = to_number(((curr.get("base_case") or {}).get("revenue")))
    prev_eps = to_number((prev.get("base_case") or {}).get("eps"))
    curr_eps = to_number((curr.get("base_case") or {}).get("eps"))
    prev_spot = to_number(prev.get("spot_price"))
    curr_spot = to_number(curr.get("spot_price"))
    data_refresh = bool(
        snapshot_changed
        or (prev_pack and curr_pack and prev_pack != curr_pack)
        or (prev_rev is not None and curr_rev is not None and prev_rev != curr_rev)
        or (prev_eps is not None and curr_eps is not None and abs(float(prev_eps) - float(curr_eps)) > 0.2)
        or (prev_spot is not None and curr_spot is not None and abs(float(prev_spot) - float(curr_spot)) > 0.5)
    )
    prev_g = to_number(((prev.get("base_case") or {}).get("growth_assumptions") or {}).get("annual_rate"))
    curr_g = to_number(((curr.get("base_case") or {}).get("growth_assumptions") or {}).get("annual_rate"))
    prev_m = to_number(((prev.get("base_case") or {}).get("margin_assumptions") or {}).get("net_margin_pct"))
    curr_m = to_number(((curr.get("base_case") or {}).get("margin_assumptions") or {}).get("net_margin_pct"))
    assumption_change = bool(
        (prev_g is not None and curr_g is not None and abs(float(prev_g) - float(curr_g)) > 0.005)
        or (prev_m is not None and curr_m is not None and abs(float(prev_m) - float(curr_m)) > 0.2)
    )
    due = []
    if data_refresh:
        due.append("data refresh")
    if assumption_change:
        due.append("assumption change")
    if methodology_change:
        due.append("methodology change")
    return {
        "snapshot_changed": snapshot_changed,
        "previous_snapshot_id": prev_snap or None,
        "current_snapshot_id": curr_snap or None,
        "methodology_change": methodology_change,
        "previous_method_version": prev_method,
        "current_method_version": curr_method,
        "data_refresh": data_refresh,
        "assumption_change": assumption_change,
        "target_change_due_to": due,
    }


def build_snapshot_manifest(
    snapshot: dict[str, Any],
    *,
    valuation: dict[str, Any] | None = None,
    pm_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = snapshot.get("pack") or snapshot.get("pack_payload") or {}
    profile = pack.get("company_profile") or {}
    cases = valuation or {}
    cal = cases.get("calibration_json") if isinstance(cases.get("calibration_json"), dict) else {}
    lineage = cal.get("financial_lineage") or cases.get("financial_lineage") or {}
    shares = lineage.get("diluted_shares") if isinstance(lineage.get("diluted_shares"), dict) else {}
    net = lineage.get("net_margin") if isinstance(lineage.get("net_margin"), dict) else {}
    growth = ((cases.get("base_case") or {}).get("growth_assumptions") or {})
    meta = pm_meta or {}
    return {
        "ticker": snapshot.get("ticker"),
        "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("id"),
        "pack": {
            "id": snapshot.get("pack_id") or pack.get("pack_id"),
            "created_at": snapshot.get("pack_updated_at") or pack.get("updated_at"),
            "revenue_ttm": profile.get("revenue_ttm"),
            "eps_ttm": profile.get("eps_ttm"),
        },
        "market": {
            "spot": snapshot.get("spot_price"),
            "timestamp": snapshot.get("market_data_timestamp"),
        },
        "valuation_inputs": {
            "diluted_shares": shares.get("value") or profile.get("diluted_shares"),
            "margin": net.get("value") or profile.get("net_margin_pct"),
            "growth_origin": growth.get("origin"),
            "multiple": (cases.get("base_case") or {}).get("multiple"),
        },
        "evidence_count": len(snapshot.get("evidence_ids") or snapshot.get("evidence") or []),
        "assumption_count": len(snapshot.get("assumption_ids") or snapshot.get("assumptions") or []),
        "model": meta.get("model") or snapshot.get("model"),
        "prompt_version": meta.get("prompt_version") or snapshot.get("prompt_version"),
        "valuation_method_version": snapshot.get("valuation_method_version") or valuation_method_version(cases),
        "market_comparison_status": market_comparison_for(to_number(snapshot.get("spot_price")))["market_comparison_status"],
    }


def freeze_live_snapshot(
    live: dict[str, Any],
    *,
    pack_source: Any | None = None,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    symbol = str(live.get("ticker") or "").upper()
    pack = dict(live.get("pack") or {})
    is_fixture = source_is_fixture(pack_source, pack)
    pack["is_fixture"] = is_fixture
    pack["source"] = "fixture" if is_fixture else (pack.get("source") or "production")
    evidence = [row for row in (live.get("evidence") or []) if isinstance(row, dict)]
    assumptions = [row for row in (live.get("assumptions") or []) if isinstance(row, dict)]
    findings = [row for row in (live.get("findings") or []) if isinstance(row, dict)]
    spot, spot_ts = pack_spot(pack)
    latest_report = pack_latest_report_date(pack)
    reasons = integrity_reasons(
        {
            "ticker": symbol,
            "pack": pack,
            "evidence": evidence,
            "assumptions": assumptions,
        },
        is_fixture=is_fixture,
    )
    status = "invalid" if reasons else "valid"
    fingerprint = _hash_inputs(
        {
            "ticker": symbol,
            "revenue_ttm": (pack.get("company_profile") or {}).get("revenue_ttm"),
            "eps_ttm": (pack.get("company_profile") or {}).get("eps_ttm"),
            "diluted_shares": (pack.get("company_profile") or {}).get("diluted_shares"),
            "net_margin_pct": (pack.get("company_profile") or {}).get("net_margin_pct"),
            "spot": spot,
            "latest_report": latest_report,
        }
    )
    snapshot_id = new_id("rsnap")
    return {
        "snapshot_id": snapshot_id,
        "id": snapshot_id,
        "ticker": symbol,
        "workflow_run_id": workflow_run_id or live.get("workflow_run_id") or pack.get("workflow_run_id"),
        "pack_id": pack.get("pack_id"),
        "pack_version": pack.get("pack_version"),
        "pack": pack,
        "pack_payload": pack,
        "evidence": evidence,
        "evidence_ids": [str(row.get("id")) for row in evidence if row.get("id")],
        "evidence_payload": evidence,
        "assumptions": assumptions,
        "assumption_ids": [str(row.get("id")) for row in assumptions if row.get("id")],
        "assumption_payload": assumptions,
        "findings": findings,
        "findings_payload": findings,
        "assumption_engine": list(live.get("assumption_engine") or []),
        "competing_hypotheses": list(live.get("competing_hypotheses") or []),
        "economic_drivers": list(live.get("economic_drivers") or []),
        "agent_reasoning": list(live.get("agent_reasoning") or []),
        "market_data_timestamp": spot_ts,
        "spot_price": spot,
        "valuation_input_version": f"{VALUATION_INPUT_VERSION}:{fingerprint}",
        "valuation_method_version": None,
        "valuation_id": None,
        "is_fixture": is_fixture,
        "snapshot_status": status,
        "invalid_reasons": reasons,
        "pack_latest_report_date": latest_report,
        "pack_updated_at": pack.get("updated_at"),
        "source": "fixture" if is_fixture else "production",
        "manifest": {},
        "market_comparison": market_comparison_for(spot),
        "pack_fingerprint": fingerprint,
    }


def hydrate_snapshot_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    stored = dict(row)
    snapshot_id = stored.get("snapshot_id") or stored.get("id")
    pack = stored.get("pack") or stored.get("pack_payload") or {}
    evidence = stored.get("evidence") or stored.get("evidence_payload") or []
    assumptions = stored.get("assumptions") or stored.get("assumption_payload") or []
    findings = stored.get("findings") or stored.get("findings_payload") or []
    stored["snapshot_id"] = snapshot_id
    stored["id"] = snapshot_id
    stored["pack"] = pack
    stored["evidence"] = evidence
    stored["assumptions"] = assumptions
    stored["findings"] = findings
    stored["evidence_ids"] = list(stored.get("evidence_ids") or [str(item.get("id")) for item in evidence if item.get("id")])
    stored["assumption_ids"] = list(stored.get("assumption_ids") or [str(item.get("id")) for item in assumptions if item.get("id")])
    stored["market_comparison"] = market_comparison_for(to_number(stored.get("spot_price")))
    return stored
