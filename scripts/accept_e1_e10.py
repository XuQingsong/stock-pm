#!/usr/bin/env python3
"""Black-box E1–E10 for trusted events (phase 5B).

Usage:
  ACCEPT_BASE=http://127.0.0.1:8767 python3 scripts/accept_e1_e10.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRET_RE = re.compile(r"(api[_-]?key|apikey|secret|password|authorization|sk-|Bearer )", re.I)
REAL_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|password)\s*[:=]\s*['\"]?(?!your_|stock_pm_dev|<|os\.getenv|getenv)[A-Za-z0-9_\-]{12,}",
    re.I,
)
OUT = Path(os.environ.get("ACCEPT_OUT", "/opt/cursor/artifacts/p0-5b"))
BASE = os.environ.get("ACCEPT_BASE", "http://127.0.0.1:8767").rstrip("/")
CDP = os.environ.get("ACCEPT_CDP", "http://127.0.0.1:9335")
MUST = ["E1", "E2", "E4", "E6", "E7", "E8", "E10"]


def get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode()


def start_cdp() -> subprocess.Popen | None:
    profile = Path("/tmp/chrome-accept-5b")
    if profile.exists():
        subprocess.run(["rm", "-rf", str(profile)], check=False)
    profile.mkdir(exist_ok=True)
    return subprocess.Popen(
            [
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-sandbox",
                f"--user-data-dir={profile}",
                "--remote-debugging-port=9335",
                "--remote-allow-origins=*",
                "--window-size=1400,1200",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def capture_pages() -> dict:
    import websocket

    proc = start_cdp()
    time.sleep(1.2)
    pages = json.load(urllib.request.urlopen(f"{CDP}/json"))
    page = next(item for item in pages if item.get("type") == "page")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
    mid = 0

    def call(method, params=None, timeout=40):
        nonlocal mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        wanted = mid
        start = time.time()
        while time.time() - start < timeout:
            msg = json.loads(ws.recv())
            if msg.get("id") == wanted:
                return msg
        raise TimeoutError(method)

    call("Page.enable")
    call("Runtime.enable")

    def evaluate(expression: str):
        ev = call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return ((ev.get("result") or {}).get("result") or {}).get("value")

    def wait_ready(url: str, selector: str, wait: float = 45) -> dict:
        call("Page.navigate", {"url": url})
        deadline = time.time() + wait
        last = {}
        while time.time() < deadline:
            time.sleep(0.7)
            last = evaluate(
                f"""(() => {{
                  const root = document.querySelector('{selector}');
                  const ready = root && root.getAttribute('data-events-ready') === '1';
                  const loading = Boolean(root && root.classList.contains('loading'));
                  return {{
                    ready,
                    loading,
                    text: document.body.innerText.slice(0, 24000),
                    google: (document.querySelector('[data-google-status]') && document.querySelector('[data-google-status]').getAttribute('data-google-status')) || '',
                    facts: [...document.querySelectorAll('[data-lane="facts"] [data-content-type]')].map((n) => n.getAttribute('data-content-type')),
                    opinions: [...document.querySelectorAll('[data-lane="opinion"] [data-content-type]')].map((n) => n.getAttribute('data-content-type')),
                    factHrefs: [...document.querySelectorAll('[data-lane="facts"] a.source-link')].map((a) => a.href),
                    opinionHrefs: [...document.querySelectorAll('[data-lane="opinion"] a.source-link')].map((a) => a.href),
                    mediaHrefs: [...document.querySelectorAll('[data-lane="media"] a.source-link')].map((a) => a.href),
                    answers: [...document.querySelectorAll('[data-answer]')].map((n) => n.getAttribute('data-answer')),
                    types: [...document.querySelectorAll('[data-event-type]')].map((n) => n.getAttribute('data-event-type')),
                    why: [...document.querySelectorAll('[data-why-relevant]')].map((n) => n.innerText),
                    conflicts: [...document.querySelectorAll('[data-polarity="contradicts"]')].map((n) => n.innerText),
                    what: [...document.querySelectorAll('[data-what-changes]')].map((n) => n.innerText),
                    analysisHrefs: [...document.querySelectorAll('.causal-block a.source-link')].map((a) => a.href),
                    vixRole: (document.querySelector('[data-vix-role]') && document.querySelector('[data-vix-role]').getAttribute('data-vix-role')) || ''
                  }};
                }})()"""
            ) or {}
            if last.get("ready") and not last.get("loading"):
                return last
        raise RuntimeError(f"events UI did not finish rendering: {url} last={last!r}")

    def isolate(selector: str) -> dict:
        return evaluate(
            f"""(() => {{
              document.querySelectorAll('.stock-header, .tabs, #stock-pm-shell, #tab-content, #decision-module').forEach((n) => {{
                n.style.setProperty('display', 'none', 'important');
              }});
              const keep = document.querySelector('{selector}');
              if (keep) keep.scrollIntoView();
              const r = keep ? keep.getBoundingClientRect() : {{width: 1280, height: 1100}};
              return {{
                ready: keep && keep.getAttribute('data-events-ready') === '1',
                loading: Boolean(keep && keep.classList.contains('loading')),
                width: Math.max(1280, Math.ceil(r.width + 24)),
                height: Math.min(5000, Math.max(1100, Math.ceil(r.height + 80)))
              }};
            }})()"""
        ) or {}

    def clip(dest: Path, selector: str) -> dict:
        info = isolate(selector)
        if info.get("loading") or not info.get("ready"):
            raise RuntimeError(f"still loading when capturing {dest.name}")
        call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": int(info.get("width") or 1280),
                "height": int(info.get("height") or 1400),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        time.sleep(0.2)
        png = call("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": True})
        dest.write_bytes(base64.b64decode(png["result"]["data"]))
        return info

    OUT.mkdir(parents=True, exist_ok=True)
    shots = {}
    shots["center"] = wait_ready(f"{BASE}/events", "#event-center")
    clip(OUT / "event-center.png", "#event-center")
    for symbol in ("NVDA", "XOM", "JPM", "AAPL"):
        shots[symbol] = wait_ready(f"{BASE}/stock/{symbol}", "#event-body")
        clip(OUT / f"{symbol.lower()}-events.png", "#event-module")
    ws.close()
    if proc:
        proc.terminate()
    return shots


def scan_incremental_secrets() -> dict:
    try:
        names = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/cursor/causal-p0-2984...HEAD"],
            text=True,
        ).splitlines()
    except Exception:
        names = []
    hits = []
    for name in names:
        path = Path(name)
        if not path.is_file() or path.suffix in {".png", ".jpg"}:
            continue
        if path.name in {".env", ".env.server"}:
            hits.append(name)
            continue
        if path.name.endswith(".example"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if REAL_SECRET_RE.search(text) and "your_" not in text and "fake" not in text.lower():
            hits.append(name)
    return {"files": names, "hits": hits}


def probe_url(url: str) -> dict:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    blocked = host in {"example.com", "example.invalid", "localhost", "127.0.0.1"} or host.endswith(".invalid")
    if parsed.scheme not in {"http", "https"} or blocked:
        return {"url": url, "ok": False, "status": "blocked", "live": False}
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "stock-pm-accept-5b"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            code = getattr(resp, "status", 200)
            return {"url": url, "ok": 200 <= code < 400, "status": code, "live": 200 <= code < 400}
    except urllib.error.HTTPError as exc:
        return {"url": url, "ok": False, "status": exc.code, "live": False}
    except Exception as exc:
        return {"url": url, "ok": False, "status": type(exc).__name__, "live": False}


def score(center, cover, health, stocks, js, page, shots, probes) -> dict:
    iran = next((row for row in center.get("events") or [] if row.get("event_type") == "war_sanctions"), {})
    vix = next((row for row in center.get("events") or [] if row.get("event_type") == "vix_risk"), {})
    sources = iran.get("sources") or []
    analysis = iran.get("analysis") or {}
    fact_types = {row.get("content_type") for row in sources if row.get("fact_or_opinion") == "fact"}
    opinion = [row for row in sources if row.get("content_type") == "research_opinion"]
    publishers = {row.get("publisher") for row in sources}
    nvda_types = {row.get("event_type") for row in (stocks["NVDA"].get("events") or [])}
    xom_types = {row.get("event_type") for row in (stocks["XOM"].get("events") or [])}
    jpm_types = {row.get("event_type") for row in (stocks["JPM"].get("events") or [])}
    aapl_types = {row.get("event_type") for row in (stocks["AAPL"].get("events") or [])}
    xom_why = next((row.get("why_relevant") or "" for row in stocks["XOM"].get("events") or [] if row.get("event_type") == "war_sanctions"), "")
    nvda_why = next((row.get("why_relevant") or "" for row in stocks["NVDA"].get("events") or [] if row.get("event_type") == "war_sanctions"), "")
    jpm_why = next((row.get("why_relevant") or "" for row in stocks["JPM"].get("events") or [] if row.get("event_type") == "war_sanctions"), "")
    google = ((cover.get("providers") or {}).get("google_cse") or {})
    official = ((cover.get("providers") or {}).get("official_feed") or {})
    live_hits = [row for row in probes if row.get("live")]
    fixture_mode = (cover.get("data_mode") or "") in {"demo", "fixture"}
    production_empty = cover.get("data_mode") == "empty" and not cover.get("live")
    ev_cover = health.get("events_coverage") or {}
    overall = (health.get("overall") or {})
    shot_center = shots.get("center") or {}
    shot_aapl = shots.get("AAPL") or {}
    shot_xom = shots.get("XOM") or {}
    refs = []
    for block in list(analysis.get("confirmed_facts") or []) + [
        analysis.get("change_vs_baseline"),
        analysis.get("mechanism"),
        analysis.get("what_changes"),
        analysis.get("confidence"),
    ]:
        if isinstance(block, dict):
            refs.extend(block.get("evidence_refs") or [])
    answers = analysis.get("answers") or {}
    e1_dom = (
        "official_fact" in (shot_center.get("facts") or [])
        and "research_opinion" in (shot_center.get("opinions") or [])
        and "research_opinion" not in (shot_center.get("facts") or [])
        and any("treasury.gov" in href for href in shot_center.get("factHrefs") or [])
        and any("goldman" in href for href in shot_center.get("opinionHrefs") or [])
    )
    e2_dom = len(shot_center.get("mediaHrefs") or []) >= 2 and len(sources) >= 3
    e4_dom = (
        "war_sanctions" not in (shot_aapl.get("types") or [])
        and "war_sanctions" in (shot_xom.get("types") or [])
        and bool(shot_xom.get("why"))
    )
    e6_dom = (shot_center.get("google") == "not_configured") and shot_center.get("ready") is True
    e8_dom = all(str(href).startswith("http") for href in shot_center.get("analysisHrefs") or []) and bool(shot_center.get("analysisHrefs"))
    e10_dom = {"what", "credibility", "why", "duration", "invalidation"}.issubset(set(shot_center.get("answers") or []))
    mode_ok = (cover.get("data_mode") in {"empty", "demo", "fixture"}) and cover.get("live") is False
    official_honest = official.get("status") in {"not_implemented", "demo_fixture"} and official.get("live") is False
    live_e1_e8 = bool(live_hits) and all(row.get("live") for row in probes) if probes else False
    framework = {
        "E1": "official_fact" in fact_types and opinion and e1_dom,
        "E2": len(sources) >= 3 and e2_dom,
        "E3": int(analysis.get("conflict_count") or 0) >= 1 and bool(shot_center.get("conflicts")),
        "E4": "war_sanctions" not in aapl_types and "war_sanctions" in xom_types and e4_dom,
        "E5": (vix.get("analysis") or {}).get("vix_role") == "risk_confirmation_only" or production_empty,
        "E6": google.get("status") == "not_configured" and official_honest and "google.com/search" not in js and e6_dom,
        "E7": cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and ev_cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and overall.get("level") != "L0",
        "E8": bool(refs) and e8_dom,
        "E9": iran.get("status") == "updated" or production_empty,
        "E10": (e10_dom and shot_center.get("ready") is True) or (production_empty and shot_center.get("ready") is True),
    }
    live = {
        "E1": framework["E1"] and live_e1_e8,
        "E2": framework["E2"] and live_e1_e8,
        "E3": framework["E3"] and live_e1_e8,
        "E4": framework["E4"] and live_e1_e8,
        "E5": bool(vix) and framework["E5"] and live_e1_e8,
        "E6": framework["E6"],
        "E7": framework["E7"],
        "E8": framework["E8"] and live_e1_e8,
        "E9": iran.get("status") == "updated" and live_e1_e8,
        "E10": bool(e10_dom) and live_e1_e8,
    }
    live_verdict = {key: ("PASS" if value else "FAIL") for key, value in live.items()}
    framework_verdict = {
        key: ("PASS" if value else "FAIL") + (" (fixture/demo only)" if fixture_mode and value else "")
        for key, value in framework.items()
    }
    return {
        "lane": "production_live" if not fixture_mode else "fixture_demo",
        "data_mode": cover.get("data_mode"),
        "live_coverage_ratio": cover.get("live_coverage_ratio"),
        "verdict": live_verdict,
        "framework_verdict": framework_verdict,
        "pass_count": sum(1 for value in live.values() if value),
        "framework_pass_count": sum(1 for value in framework.values() if value),
        "must_fail": [key for key in MUST if not live[key]],
        "gate": live["E6"] and live["E7"] and mode_ok and official_honest and official.get("status") != "ok",
        "note": "Fixture/demo cases are not production live passes. E1/E8 require reachable non-example originals.",
        "probes": probes,
        "live_hits": len(live_hits),
        "page": page[:80],
        "xom_why": xom_why,
        "nvda_why": nvda_why,
        "jpm_why": jpm_why,
        "publishers": sorted(publishers),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    center = get(f"{BASE}/api/events")
    cover = get(f"{BASE}/api/events/coverage")
    health = get(f"{BASE}/api/stock/NVDA/data-health")
    stocks = {
        symbol: get(f"{BASE}/api/stock/{symbol}/events")
        for symbol in ("NVDA", "XOM", "JPM", "AAPL")
    }
    js = html(f"{BASE}/static/events_ui.js") + html(f"{BASE}/static/events.js") + html(f"{BASE}/static/stock.js")
    page = html(f"{BASE}/events")
    urls = []
    for event in center.get("events") or []:
        for source in event.get("sources") or []:
            urls.append(source.get("source_url"))
        for ref in (event.get("analysis") or {}).get("evidence_refs") or []:
            urls.append(ref.get("source_url"))
    probes = [probe_url(url) for url in dict.fromkeys(item for item in urls if item)]
    screenshot_error = None
    shots = {}
    try:
        shots = capture_pages()
    except Exception as exc:
        screenshot_error = str(exc)
        shots = {}
    report = score(center, cover, health, stocks, js.lower(), page, shots, probes)
    secrets = scan_incremental_secrets()
    report["incremental_scan"] = {"file_count": len(secrets["files"]), "hits": secrets["hits"]}
    if secrets["hits"]:
        report["verdict"]["keys"] = "FAIL"
        report["gate"] = False
    if screenshot_error:
        report["screenshot_error"] = screenshot_error
        report["gate"] = False
    report["screenshots"] = sorted(path.name for path in OUT.glob("*.png"))
    dumped = json.dumps(report, ensure_ascii=False, indent=2)
    (OUT / "e1-e10.json").write_text(dumped)
    print(dumped)
    if screenshot_error:
        print("screenshot_error:", screenshot_error)
    return 0 if report["gate"] and not screenshot_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
