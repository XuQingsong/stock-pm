#!/usr/bin/env python3
"""Black-box S1–S10 for Phase 6B driver synthesis.

Usage:
  ACCEPT_BASE=http://127.0.0.1:8767 ACCEPT_INJECT=http://127.0.0.1:8768 \\
    python3 scripts/accept_s1_s10.py

Required: S2/S3/S4/S6/S7/S9/S10 and overall >=9/10.
Production-like ACCEPT_BASE must ignore ?macro_inject=. ACCEPT_INJECT is
the test/preview process with ENABLE_DECISION_INJECT=true and APP_ENV=test.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

SECRET_RE = re.compile(r"(api[_-]?key|apikey=|secret|password|authorization|sk-|Bearer )", re.I)
FORECAST_RE = re.compile(r"(目标价|买入|卖出|做多|做空|上涨\s*\d|下跌\s*\d|胜率|概率\s*\d)")
OUT = Path(os.environ.get("ACCEPT_OUT", "/opt/cursor/artifacts/p0-6b"))
BASE = os.environ.get("ACCEPT_BASE", "http://127.0.0.1:8767").rstrip("/")
INJECT = os.environ.get("ACCEPT_INJECT", "http://127.0.0.1:8768").rstrip("/")


def get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode()


def inject(path: str, token: str) -> dict:
    return get(f"{INJECT}{path}?macro_inject={token}")


def secrets(blob: str) -> bool:
    return bool(SECRET_RE.search(blob or ""))


def forecasts(blob: str) -> bool:
    return bool(FORECAST_RE.search(blob or ""))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    center = get(f"{BASE}/api/events")
    nvda = get(f"{BASE}/api/stock/NVDA/events")
    aapl = get(f"{BASE}/api/stock/AAPL/events")
    xom = get(f"{BASE}/api/stock/XOM/events")
    nok = get(f"{BASE}/api/stock/NOK/events")
    jpm = get(f"{BASE}/api/stock/JPM/events")
    events_html = html(f"{BASE}/events")
    verdict: dict[str, bool] = {}

    try:
        s1 = inject("/api/events", "us2y_up")
        s1_m = s1.get("driver_synthesis") or {}
        s1_conf = (s1_m.get("confirmations") or [{}])[0].get("text") or ""
        verdict["S1"] = (
            s1_m.get("can_form_direction") is not True
            and s1_m.get("net_expectation", {}).get("is_fact") is False
            and ("利率" in ((s1_m.get("net_expectation") or {}).get("text") or "") or "折现" in ((s1_m.get("net_expectation") or {}).get("text") or ""))
            and "同向确认" in (s1_conf + str(s1_m.get("net_expectation") or ""))
            and not s1_m.get("contradictions")
            and (s1_m.get("confidence") or {}).get("label") in {"medium", "high"}
        )
    except Exception:
        verdict["S1"] = False

    try:
        s2 = inject("/api/events", "reverse_cpi,us2y_up")
        s2_m = s2.get("driver_synthesis") or {}
        s1_rank = ((inject("/api/events", "us2y_up").get("driver_synthesis") or {}).get("confidence") or {}).get("rank") or 0
        s2_rank = (s2_m.get("confidence") or {}).get("rank") or 99
        s2_text = str(s2_m.get("contradictions") or "") + str(s2_m.get("net_expectation") or "")
        metrics = {row.get("metric") for row in s2_m.get("drivers") or []}
        verdict["S2"] = (
            bool(s2_m.get("contradictions"))
            and "冲突" in s2_text
            and "cpi" in metrics
            and "us2y" in metrics
            and s2_rank < s1_rank
            and s2_m.get("can_form_direction") is not True
        )
    except Exception:
        verdict["S2"] = False

    try:
        s3 = inject("/api/events", "vix_only")
        s3_m = s3.get("driver_synthesis") or {}
        s3_nvda = inject("/api/stock/NVDA/events", "vix_only")
        verdict["S3"] = (
            (s3_m.get("net_expectation") or {}).get("stance") == "risk_confirmation_only"
            and s3_m.get("can_form_direction") is not True
            and (s3_m.get("vix") or {}).get("sets_direction") is False
            and "不形成方向" in ((s3_m.get("net_expectation") or {}).get("text") or "")
            and s3_nvda.get("driver_synthesis") in {None, {}}
        )
    except Exception:
        verdict["S3"] = False

    xom_syn = xom.get("driver_synthesis") or {}
    aapl_syn = aapl.get("driver_synthesis")
    nok_syn = nok.get("driver_synthesis")
    xom_metrics = {row.get("metric") for row in xom_syn.get("drivers") or []}
    verdict["S4"] = (
        "wti" in xom_metrics
        and aapl_syn in {None, {}}
        and nok_syn in {None, {}}
        and "wti" not in {row.get("metric") for row in (aapl.get("macro_chains") or [])}
    )

    jpm_syn = jpm.get("driver_synthesis") or {}
    jpm_themes = {row.get("theme") for row in jpm_syn.get("driver_themes") or []}
    verdict["S5"] = (
        bool(jpm_syn)
        and ("credit" in jpm_themes or any("信用" in ((jpm_syn.get("why_relevant") or "") + str(jpm_syn.get("net_expectation") or ""))))
        and aapl_syn in {None, {}}
    )

    try:
        s6 = inject("/api/events", "source_fail_us2y")
        s6_m = s6.get("driver_synthesis") or {}
        s6_missing = {row.get("metric") for row in s6_m.get("missing") or []}
        s6_drivers = {row.get("metric") for row in s6_m.get("drivers") or []}
        verdict["S6"] = (
            "us2y" in s6_missing
            and "cpi" in s6_drivers
            and "nfp" in s6_drivers
            and s6_m.get("net_expectation", {}).get("stance") not in {None, "withheld"}
        )
    except Exception:
        verdict["S6"] = False

    try:
        base_s = inject("/api/events", "us2y_up")
        dup = inject("/api/events", "us2y_up,duplicate_cpi")
        base_c = (base_s.get("driver_synthesis") or {}).get("confidence") or {}
        dup_c = (dup.get("driver_synthesis") or {}).get("confidence") or {}
        verdict["S7"] = (
            dup_c.get("independent_fact_count") == base_c.get("independent_fact_count")
            and dup_c.get("rank") == base_c.get("rank")
            and int(dup_c.get("duplicate_facts_collapsed") or 0) >= 1
        )
    except Exception:
        verdict["S7"] = False

    try:
        first = inject("/api/events", "us2y_up")
        second = inject("/api/events", "us2y_up,reverse_cpi")
        first_m = first.get("driver_synthesis") or {}
        second_m = second.get("driver_synthesis") or {}
        first_cpi = next((row for row in first_m.get("drivers") or [] if row.get("metric") == "cpi"), {})
        second_cpi = next((row for row in second_m.get("drivers") or [] if row.get("metric") == "cpi"), {})
        ids = [row.get("synthesis_id") for row in (second.get("driver_syntheses") or []) if row.get("scope") == "market"]
        verdict["S8"] = (
            first_m.get("synthesis_id") == second_m.get("synthesis_id") == "synth:market:macro"
            and first_cpi.get("polarity") != second_cpi.get("polarity")
            and ids.count("synth:market:macro") == 1
        )
    except Exception:
        verdict["S8"] = False

    pages = [center, nvda, aapl, xom, nok, jpm]
    blob = json.dumps(pages, ensure_ascii=False) + events_html
    verdict["S9"] = (
        all((row.get("driver_synthesis") or {}).get("can_form_direction") is not True for row in pages if isinstance(row, dict))
        and (center.get("driver_synthesis") or {}).get("percent_forecast") is None
        and not forecasts(blob)
        and "综合判断" in events_html
        and "已观察事实" in events_html
        and "综合条件预期" in events_html
    )

    try:
        s10 = inject("/api/events", "vix_only")
        s10_m = s10.get("driver_synthesis") or {}
        missing = {row.get("metric") for row in s10_m.get("missing") or []}
        text = ((s10_m.get("net_expectation") or {}).get("text") or "") + ((s10_m.get("what_changes") or {}).get("text") or "")
        verdict["S10"] = (
            {"cpi", "nfp", "us2y"} <= missing
            and "缺少" in text
            and not (text.strip() == "数据不足")
            and "笼统" in text or "缺少" in text
        )
    except Exception:
        verdict["S10"] = False

    required = ("S2", "S3", "S4", "S6", "S7", "S9", "S10")
    passed = sum(1 for key, ok in verdict.items() if ok)
    gate = passed >= 9 and all(verdict.get(key) for key in required)
    evidence = {
        "verdict": {key: ("PASS" if verdict.get(key) else "FAIL") for key in (f"S{i}" for i in range(1, 11))},
        "pass_count": passed,
        "gate": gate,
        "synthesis_id": (center.get("driver_synthesis") or {}).get("synthesis_id"),
        "live": center.get("live"),
        "html_has_synthesis": "综合判断" in events_html,
        "secret_scan": secrets(blob),
        "forecast_scan": forecasts(blob),
    }
    (OUT / "s1-s10.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
