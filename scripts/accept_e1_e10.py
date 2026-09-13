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
MUST_LIVE = ["E1", "E6", "E7", "E8", "E10"]
MUST_CAPABILITY = ["E1", "E2", "E4", "E6", "E7", "E8", "E10"]
ACCEPT_HOSTS = (
    "sec.gov",
    "federalreserve.gov",
    "eia.gov",
    "treasury.gov",
    "ofac.treasury.gov",
    "home.treasury.gov",
)


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
                    vixRole: (document.querySelector('[data-vix-role]') && document.querySelector('[data-vix-role]').getAttribute('data-vix-role')) || '',
                    banner: (document.querySelector('.event-mode-banner') && document.querySelector('.event-mode-banner').innerText) || '',
                    replay: (document.querySelector('[data-replay]') && document.querySelector('[data-replay]').getAttribute('data-replay')) || '',
                    timeline: [...document.querySelectorAll('[data-timeline-item]')].map((n) => ({{
                      status: n.getAttribute('data-timeline-status') || '',
                      polarity: n.getAttribute('data-polarity') || '',
                      what: n.getAttribute('data-what-changes') || n.innerText
                    }}))
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
              if (keep) {{
                keep.style.maxHeight = '2400px';
                keep.style.overflow = 'hidden';
              }}
              const r = keep ? keep.getBoundingClientRect() : {{width: 1280, height: 1100}};
              return {{
                ready: keep && keep.getAttribute('data-events-ready') === '1',
                loading: Boolean(keep && keep.classList.contains('loading')),
                width: Math.max(1280, Math.ceil(r.width + 24)),
                height: Math.min(2400, Math.max(1100, Math.ceil(Math.min(r.height + 80, 2400))))
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
        time.sleep(0.3)
        png = call(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        )
        payload = png.get("result") or {}
        if "data" not in payload:
            raise RuntimeError(f"screenshot missing result: {png}")
        dest.write_bytes(base64.b64decode(payload["data"]))
        return info

    OUT.mkdir(parents=True, exist_ok=True)
    shots = {}
    try:
        shots["center"] = wait_ready(f"{BASE}/events", "#event-center")
        clip(OUT / "event-center.png", "#event-center")
        for symbol in ("NVDA", "XOM", "JPM", "AAPL"):
            shots[symbol] = wait_ready(f"{BASE}/stock/{symbol}", "#event-body")
            clip(OUT / f"{symbol.lower()}-events.png", "#event-module")
        return shots
    finally:
        try:
            ws.close()
        except Exception:
            pass
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


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
    headers = {
        "User-Agent": "stock-pm research AdminContact@example.com",
        "Accept": "text/html,*/*",
        "Accept-Encoding": "gzip, deflate",
    }
    methods = ("GET",) if "sec.gov" in host else ("HEAD", "GET")
    last_status: object = None
    for method in methods:
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                code = getattr(resp, "status", 200)
                return {"url": url, "ok": 200 <= code < 400, "status": code, "live": 200 <= code < 400}
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            if method == "HEAD":
                continue
            if 200 <= exc.code < 400:
                return {"url": url, "ok": True, "status": exc.code, "live": True}
            return {"url": url, "ok": False, "status": exc.code, "live": False}
        except Exception as exc:
            last_status = type(exc).__name__
            if method == "HEAD":
                continue
            return {"url": url, "ok": False, "status": last_status, "live": False}
    return {"url": url, "ok": False, "status": last_status, "live": False}


OFFICIAL_HOSTS = ACCEPT_HOSTS
UNOBSERVED = "算法 fixture PASS / 实盘未观测"


def _official_href(href: str) -> bool:
    host = (urllib.parse.urlsplit(href).hostname or "").lower()
    return any(host == item or host.endswith("." + item) for item in OFFICIAL_HOSTS)


def accept_host_allowed(url: str) -> bool:
    """Accept-only host check. Does not change production source policy."""
    return _official_href(url)


def _collect_refs(event: dict) -> list[dict]:
    analysis = event.get("analysis") or {}
    refs = []
    for block in list(analysis.get("confirmed_facts") or []) + [
        analysis.get("change_vs_baseline"),
        analysis.get("mechanism"),
        analysis.get("what_changes"),
        analysis.get("confidence"),
    ]:
        if isinstance(block, dict):
            refs.extend(block.get("evidence_refs") or [])
    return refs


def score(center, cover, health, stocks, js, page, shots, probes, *, lane: str) -> dict:
    events = list(center.get("events") or [])
    iran = next((row for row in events if row.get("event_type") == "war_sanctions"), {})
    vix = next((row for row in events if row.get("event_type") == "vix_risk"), {})
    sample = next((row for row in events if row.get("event_type") in {"company_filing", "central_bank_rates", "energy_supply", "other"}), {})
    lead = iran or sample
    sources = lead.get("sources") or []
    analysis = lead.get("analysis") or {}
    fact_types = {row.get("content_type") for row in sources if row.get("fact_or_opinion") == "fact"}
    opinion = [row for row in sources if row.get("content_type") == "research_opinion"]
    publishers = {row.get("publisher") for event in events for row in event.get("sources") or []}
    aapl_types = {row.get("event_type") for row in (stocks["AAPL"].get("events") or [])}
    xom_types = {row.get("event_type") for row in (stocks["XOM"].get("events") or [])}
    xom_why = next((row.get("why_relevant") or "" for row in stocks["XOM"].get("events") or [] if row.get("event_type") in {"war_sanctions", "energy_supply"}), "")
    nvda_why = next((row.get("why_relevant") or "" for row in stocks["NVDA"].get("events") or [] if row.get("event_type") == "war_sanctions"), "")
    jpm_why = next((row.get("why_relevant") or "" for row in stocks["JPM"].get("events") or [] if row.get("event_type") == "war_sanctions"), "")
    google = ((cover.get("providers") or {}).get("google_cse") or {})
    official = ((cover.get("providers") or {}).get("official_feed") or {})
    live_providers = {
        name: ((cover.get("providers") or {}).get(name) or {})
        for name in ("sec_edgar", "federal_reserve", "eia_press")
    }
    live_hits = [row for row in probes if row.get("live")]
    fixture_mode = (cover.get("data_mode") or "") in {"demo", "fixture"}
    replay_mode = (cover.get("data_mode") or "") == "recorded_replay" or cover.get("recorded_replay") is True
    production = not fixture_mode and not replay_mode
    ev_cover = health.get("events_coverage") or {}
    overall = (health.get("overall") or {})
    shot_center = shots.get("center") or {}
    shot_aapl = shots.get("AAPL") or {}
    shot_xom = shots.get("XOM") or {}
    refs = _collect_refs(lead)
    official_dom = any(_official_href(href) for href in shot_center.get("factHrefs") or [])
    e1_live_dom = "official_fact" in (shot_center.get("facts") or []) and official_dom and "research_opinion" not in (shot_center.get("facts") or [])
    e1_fixture_dom = e1_live_dom and any("goldman" in href for href in shot_center.get("opinionHrefs") or [])
    e2_observed = any(len(event.get("sources") or []) >= 3 for event in events)
    e3_observed = any(int((event.get("analysis") or {}).get("conflict_count") or 0) >= 1 for event in events)
    nvda_types = {row.get("event_type") for row in (stocks["NVDA"].get("events") or [])}
    jpm_types = {row.get("event_type") for row in (stocks["JPM"].get("events") or [])}
    e4_observed = (
        "war_sanctions" in xom_types
        and "war_sanctions" not in aapl_types
        and "war_sanctions" in nvda_types
        and "war_sanctions" in jpm_types
        and bool(xom_why)
        and bool(nvda_why)
        and bool(jpm_why)
        and xom_why != nvda_why
    )
    e9_observed = any(
        event.get("status") in {"updated", "revoked"} and len(event.get("timeline") or []) >= 2
        for event in events
    )
    e6_dom = (shot_center.get("google") == "not_configured") and shot_center.get("ready") is True
    e8_dom = all(str(href).startswith("http") for href in shot_center.get("analysisHrefs") or []) and bool(shot_center.get("analysisHrefs"))
    e10_dom = {"what", "credibility", "why", "duration", "invalidation"}.issubset(set(shot_center.get("answers") or []))
    official_feeds_ok = sum(1 for row in live_providers.values() if row.get("status") == "ok" and int(row.get("event_count") or 0) > 0)
    fixture_honest = official.get("status") in {"idle", "demo_fixture", "not_implemented"} and official.get("live") is False
    google_honest = google.get("status") == "not_configured" and "google.com/search" not in js
    replay_honest = (not replay_mode) or (
        cover.get("live") is False and ((cover.get("providers") or {}).get("recorded_replay") or {}).get("live") is False
    )
    lead_urls = {
        str(row.get("source_url") or "")
        for row in list(lead.get("sources") or []) + refs
        if str(row.get("source_url") or "").startswith("http")
    }
    lead_probes = [row for row in probes if row.get("url") in lead_urls]

    def _recorded_original_ok(url: str) -> bool:
        try:
            from stock_pm.events.replay import load_recorded_pack

            pack = load_recorded_pack()
        except Exception:
            return False
        for row in pack.get("documents") or []:
            if str(row.get("source_url") or "") == url and int(row.get("http_status") or 0) == 200 and row.get("content_sha256"):
                return True
        return False

    live_originals = bool(lead_probes) and all(row.get("live") for row in lead_probes) and any(
        _official_href(row.get("url") or "") for row in lead_probes
    )
    if replay_mode:
        live_originals = bool(lead_urls) and all(
            _official_href(url)
            and (
                any(row.get("url") == url and row.get("live") for row in probes)
                or _recorded_original_ok(url)
            )
            for url in lead_urls
        )
    framework = {
        "E1": ("official_fact" in fact_types and (e1_fixture_dom if fixture_mode else e1_live_dom)),
        "E2": e2_observed,
        "E3": e3_observed,
        "E4": e4_observed,
        "E5": (vix.get("analysis") or {}).get("vix_role") == "risk_confirmation_only" or not vix,
        "E6": google_honest and fixture_honest and e6_dom,
        "E7": cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and ev_cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and overall.get("level") != "L0",
        "E8": bool(refs) and e8_dom,
        "E9": e9_observed,
        "E10": e10_dom and shot_center.get("ready") is True,
    }
    live = {
        "E1": production and e1_live_dom and live_originals and official_feeds_ok >= 1,
        "E2": production and e2_observed and live_originals,
        "E3": production and e3_observed and live_originals,
        "E4": production and e4_observed and live_originals,
        "E5": framework["E5"],
        "E6": framework["E6"],
        "E7": framework["E7"],
        "E8": production and framework["E8"] and live_originals,
        "E9": production and e9_observed and live_originals,
        "E10": production and e10_dom and live_originals and shot_center.get("ready") is True,
    }

    def live_label(key: str) -> str:
        if live[key]:
            return "PASS"
        if key in {"E2", "E3", "E4", "E9"} and not {
            "E2": e2_observed,
            "E3": e3_observed,
            "E4": e4_observed,
            "E9": e9_observed,
        }[key]:
            return UNOBSERVED
        return "FAIL"

    live_verdict = {key: live_label(key) for key in live}
    framework_verdict = {
        key: ("PASS" if value else "FAIL") + (" (fixture/demo only)" if fixture_mode and value else "")
        for key, value in framework.items()
    }
    capability = {
        "E1": (e1_live_dom or ("official_fact" in fact_types and official_dom)) and live_originals,
        "E2": e2_observed and live_originals,
        "E3": e3_observed and bool(shot_center.get("conflicts") or analysis.get("conflict_count")),
        "E4": e4_observed and live_originals,
        "E5": framework["E5"],
        "E6": google_honest and e6_dom and replay_honest,
        "E7": framework["E7"],
        "E8": framework["E8"] and live_originals,
        "E9": e9_observed
        and (
            "不重复" in str((analysis.get("what_changes") or {}).get("text") or "")
            or any("不重复" in str(item.get("what") or "") for item in (shot_center.get("timeline") or []))
            or bool(shot_center.get("what"))
        )
        and bool(shot_center.get("timeline") or lead.get("timeline")),
        "E10": e10_dom and shot_center.get("ready") is True,
    }
    accept_host_violations = [
        str(row.get("source_url") or "")
        for event in events
        for row in event.get("sources") or []
        if str(row.get("source_url") or "").startswith("http") and not accept_host_allowed(str(row.get("source_url") or ""))
    ]
    if lane == "capability-black-box":
        if accept_host_violations:
            capability = {key: False for key in capability}
        banner_ok = "RECORDED REPLAY" in str(shot_center.get("banner") or "") or "LIVE" in str(shot_center.get("banner") or "")
        if not banner_ok:
            capability["E1"] = False
            capability["E6"] = False
        verdict = {key: ("PASS" if capability[key] else "FAIL") for key in capability}
        must = MUST_CAPABILITY
        gate = all(verdict[key] == "PASS" for key in must) and sum(1 for value in capability.values() if value) >= 8
        note = (
            "Capability black-box: LIVE or RECORDED REPLAY through the production pipeline and browser. "
            "Unit tests are not counted as black-box PASS."
        )
    else:
        verdict = live_verdict
        must = MUST_LIVE
        gate = all(verdict[key] == "PASS" for key in must) and fixture_honest
        note = (
            "live-current counts only the current online book. "
            f"E2/E3/E4/E9 without a natural live sample are '{UNOBSERVED}'."
        )
    return {
        "lane": lane,
        "data_mode": cover.get("data_mode"),
        "live": cover.get("live"),
        "recorded_replay": replay_mode,
        "live_coverage_ratio": cover.get("live_coverage_ratio"),
        "real_source_count": cover.get("real_source_count"),
        "event_count": cover.get("event_count"),
        "live_event_count": cover.get("live_event_count"),
        "last_success": cover.get("last_success"),
        "implemented_live_providers": cover.get("implemented_live_providers"),
        "live_ok_providers": cover.get("live_ok_providers"),
        "provider_health": live_providers,
        "verdict": verdict,
        "framework_verdict": framework_verdict,
        "pass_count": sum(1 for value in verdict.values() if value == "PASS"),
        "framework_pass_count": sum(1 for value in framework.values() if value),
        "must_fail": [key for key in must if verdict[key] != "PASS"],
        "gate": gate and replay_honest,
        "note": note,
        "probes": probes,
        "live_hits": len(live_hits),
        "page": page[:80],
        "xom_why": xom_why,
        "nvda_why": nvda_why,
        "jpm_why": jpm_why,
        "publishers": sorted(item for item in publishers if item),
        "opinion_present": bool(opinion),
        "lead_event_type": lead.get("event_type"),
        "accept_host_violations": accept_host_violations,
        "banner": shot_center.get("banner"),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Black-box E1-E10 accept")
    parser.add_argument("--lane", choices=("live-current", "capability-black-box"), default=os.environ.get("ACCEPT_LANE", "live-current"))
    parser.add_argument("--out-name", default="")
    args = parser.parse_args()
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
    for event in (center.get("events") or [])[:24]:
        for source in event.get("sources") or []:
            urls.append(source.get("source_url"))
        for ref in (event.get("analysis") or {}).get("evidence_refs") or []:
            urls.append(ref.get("source_url"))
    unique = list(dict.fromkeys(item for item in urls if item))
    lead_first = []
    for event in (center.get("events") or [])[:3]:
        for source in event.get("sources") or []:
            lead_first.append(source.get("source_url"))
        for ref in (event.get("analysis") or {}).get("evidence_refs") or []:
            lead_first.append(ref.get("source_url"))
    preferred = [url for url in dict.fromkeys(lead_first) if url]
    rest = [url for url in unique if url not in preferred]
    probes = [probe_url(url) for url in (preferred + rest)[:12]]
    screenshot_error = None
    shots = {}
    try:
        shots = capture_pages()
    except Exception as exc:
        screenshot_error = str(exc)
    report = score(center, cover, health, stocks, js.lower(), page, shots, probes, lane=args.lane)
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
    out_name = args.out_name or ("capability-black-box.json" if args.lane == "capability-black-box" else "live-current.json")
    (OUT / out_name).write_text(dumped)
    (OUT / "e1-e10.json").write_text(dumped)
    print(dumped)
    if screenshot_error:
        print("screenshot_error:", screenshot_error)
    return 0 if report["gate"] and not screenshot_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
