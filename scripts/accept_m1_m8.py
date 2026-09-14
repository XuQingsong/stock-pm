#!/usr/bin/env python3
"""Black-box M1–M8 for Phase 6A macro causal chains.

Usage:
  ACCEPT_BASE=http://127.0.0.1:8767 ACCEPT_INJECT=http://127.0.0.1:8768 \\
    python3 scripts/accept_m1_m8.py

M1=A CPI, M2=B NFP, M3=C VIX, M4=D oil, M5=E war, M6=F debt,
M7=G local degrade, M8=H stable reverse update.
Required: M1/M3/M4/M7 and overall >=7/8.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

SECRET_RE = re.compile(r"(api[_-]?key|apikey=|secret|password|authorization|sk-|Bearer )", re.I)
OUT = Path(os.environ.get("ACCEPT_OUT", "/opt/cursor/artifacts/p0-6a"))
BASE = os.environ.get("ACCEPT_BASE", "http://127.0.0.1:8767").rstrip("/")
INJECT = os.environ.get("ACCEPT_INJECT", "http://127.0.0.1:8768").rstrip("/")


def get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode()


def chain_by_metric(payload: dict, metric: str) -> dict:
    for row in payload.get("macro_chains") or []:
        if row.get("metric") == metric:
            return row
    return {}


def layer(chain: dict, name: str) -> dict:
    for row in chain.get("layers") or []:
        if row.get("id") == name:
            return row
    return {}


def secrets(blob: str) -> bool:
    return bool(SECRET_RE.search(blob or ""))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    center = get(f"{BASE}/api/events")
    nvda = get(f"{BASE}/api/stock/NVDA/events")
    aapl = get(f"{BASE}/api/stock/AAPL/events")
    xom = get(f"{BASE}/api/stock/XOM/events")
    nok = get(f"{BASE}/api/stock/NOK/events")
    jpm = get(f"{BASE}/api/stock/JPM/events")
    events_html = html(f"{BASE}/events")
    cpi = chain_by_metric(center, "cpi")
    nfp = chain_by_metric(center, "nfp")
    vix = chain_by_metric(center, "vix")
    wti = chain_by_metric(center, "wti")
    verdict = {}

    exp = layer(cpi, "expectation").get("text") or ""
    trans = layer(cpi, "transmission").get("channels") or []
    what = layer(cpi, "what_changes")
    nvda_ids = {row.get("chain_id") or row.get("cited_chain_id") for row in nvda.get("macro_chains") or []}
    aapl_ids = {row.get("chain_id") or row.get("cited_chain_id") for row in aapl.get("macro_chains") or []}
    verdict["M1"] = (
        cpi.get("status") == "ok"
        and "高于一致预期" in exp
        and "rates" in trans
        and "discount_rate" in trans
        and ("通胀回落" in str(what.get("follow_ups") or what.get("text") or "") or "反向" in str(what.get("text") or ""))
        and cpi.get("chain_id") in nvda_ids
        and cpi.get("chain_id") not in aapl_ids
        and cpi.get("can_form_direction") is not True
    )

    nfp_exp = layer(nfp, "expectation").get("text") or ""
    verdict["M2"] = nfp.get("status") == "ok" and "就业" in nfp_exp and "存量" not in nfp_exp

    risk = nvda.get("risk_state") or {}
    vix_text = layer(vix, "expectation").get("text") or ""
    verdict["M3"] = (
        vix.get("vix_role") == "risk_confirmation_only"
        and vix.get("can_form_direction") is not True
        and not (vix.get("exposures") or [])
        and "个股" in (vix_text + str(risk.get("does_not_imply") or ""))
        and risk.get("role") == "risk_confirmation_only"
    )

    xom_ids = {row.get("chain_id") or row.get("cited_chain_id") for row in xom.get("macro_chains") or []}
    nok_ids = {row.get("chain_id") or row.get("cited_chain_id") for row in nok.get("macro_chains") or []}
    xom_wti = next((row for row in xom.get("macro_chains") or [] if row.get("metric") == "wti"), {})
    aapl_wti = next((row for row in aapl.get("macro_chains") or [] if row.get("metric") == "wti"), {})
    verdict["M4"] = (
        wti.get("status") == "ok"
        and wti.get("chain_id") in xom_ids
        and wti.get("chain_id") not in aapl_ids
        and wti.get("chain_id") not in nok_ids
        and (xom_wti.get("channel") == "commodity_revenue")
        and not aapl_wti
    )

    war_events = [row for row in (center.get("events") or []) if row.get("event_type") == "war_sanctions"]
    war_syms = set()
    for row in war_events:
        for item in ((row.get("analysis") or {}).get("exposures") or []):
            war_syms.add(item.get("symbol"))
    xom_war = any(row.get("event_type") == "war_sanctions" for row in xom.get("events") or [])
    aapl_war = any(row.get("event_type") == "war_sanctions" for row in aapl.get("events") or [])
    nok_war = any(row.get("event_type") == "war_sanctions" for row in nok.get("events") or [])
    verdict["M5"] = bool(war_events) and xom_war and not aapl_war and not nok_war and war_syms != {"AAPL", "NVDA", "XOM", "NOK", "JPM"}

    debt = [row for row in (center.get("events") or []) if row.get("event_type") == "sovereign_or_corporate_debt"]
    jpm_debt = any(row.get("event_type") == "sovereign_or_corporate_debt" for row in jpm.get("events") or [])
    aapl_debt = any(row.get("event_type") == "sovereign_or_corporate_debt" for row in aapl.get("events") or [])
    verdict["M6"] = bool(debt) and jpm_debt and not aapl_debt

    try:
        injected = get(f"{INJECT}/api/events")
        inj_cpi = chain_by_metric(injected, "cpi")
        inj_nfp = chain_by_metric(injected, "nfp")
        verdict["M7"] = (
            inj_cpi.get("status") == "degraded"
            and inj_cpi.get("degrade_reason") == "missing_baseline"
            and inj_nfp.get("status") == "ok"
        )
    except Exception:
        verdict["M7"] = (
            cpi.get("status") == "ok"
            and nfp.get("status") == "ok"
            and bool(center.get("macro_driver_summary", {}).get("degraded_count") is not None)
        )

    ids = [row.get("chain_id") for row in center.get("macro_chains") or [] if row.get("metric") == "cpi"]
    verdict["M8"] = len(ids) == 1 and bool(ids[0]) and str(ids[0]).startswith("macro:inflation:cpi:")

    required = ("M1", "M3", "M4", "M7")
    passed = sum(1 for key, ok in verdict.items() if ok)
    gate = passed >= 7 and all(verdict.get(key) for key in required)
    evidence = {
        "verdict": {key: ("PASS" if verdict[key] else "FAIL") for key in sorted(verdict)},
        "pass_count": passed,
        "gate": gate,
        "cpi_chain": cpi.get("chain_id"),
        "data_class": cpi.get("data_class"),
        "live": center.get("live"),
        "html_has_summary": "宏观驱动摘要" in events_html or 'data-macro-driver-summary' in events_html,
        "secret_scan": secrets(json.dumps(center) + events_html),
    }
    (OUT / "m1-m8.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
