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
                    providerHealthGate: (document.querySelector('[data-provider-health-gate]') && document.querySelector('[data-provider-health-gate]').getAttribute('data-provider-health-gate')) || '',
                    liveE1E10Gate: (document.querySelector('[data-live-e1-e10-gate]') && document.querySelector('[data-live-e1-e10-gate]').getAttribute('data-live-e1-e10-gate')) || '',
                    capabilityE1E10Gate: (document.querySelector('[data-capability-e1-e10-gate]') && document.querySelector('[data-capability-e1-e10-gate]').getAttribute('data-capability-e1-e10-gate')) || '',
                    claimExcerpts: [...document.querySelectorAll('[data-claim-excerpt]')].map((n) => n.innerText),
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
              const readyNode = keep && (keep.matches('[data-events-ready]') ? keep : keep.querySelector('[data-events-ready]'));
              const r = keep ? keep.getBoundingClientRect() : {{width: 1280, height: 1100}};
              return {{
                ready: readyNode && readyNode.getAttribute('data-events-ready') === '1',
                loading: Boolean(readyNode && readyNode.classList.contains('loading')),
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
        clip(OUT / "event-center.png", ".event-module")
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
UNOBSERVED = "UNOBSERVED"
UNVERIFIED = "UNVERIFIED"


def _official_href(href: str) -> bool:
    host = (urllib.parse.urlsplit(href).hostname or "").lower()
    return any(host == item or host.endswith("." + item) for item in OFFICIAL_HOSTS)


def accept_host_allowed(url: str) -> bool:
    """Accept-only host check. Does not change production source policy."""
    return _official_href(url)


def _metrics(event: dict) -> dict:
    analysis = event.get("analysis") or {}
    cover = event.get("coverage") or {}
    sources = event.get("sources") or []
    publishers = {
        str(row.get("publisher") or "").strip().lower()
        for row in sources
        if row.get("evidence_role") != "regime_catalog"
    }
    return {
        "document_count": int(analysis.get("document_count") or cover.get("document_count") or len(sources) or 0),
        "publisher_count": int(analysis.get("publisher_count") or cover.get("publisher_count") or len(publishers) or 0),
        "independent_publisher_count": int(
            analysis.get("independent_publisher_count") or cover.get("independent_publisher_count") or len(publishers) or 0
        ),
        "superseded_count": int(analysis.get("superseded_count") or cover.get("superseded_count") or 0),
        "conflict_count": int(analysis.get("conflict_count") or cover.get("conflict_count") or 0),
        "document_roles": sorted({str(row.get("document_role") or "") for row in sources if row.get("document_role")}),
    }


def _claim_evidence_rows(events: list[dict], pack: dict | None) -> list[dict]:
    from stock_pm.events.evidence import excerpt_supports_claim

    docs = {str(row.get("source_url") or ""): row for row in (pack or {}).get("documents") or []}
    rows = []
    for event in events:
        for claim in event.get("claims") or []:
            url = str(claim.get("source_url") or "")
            doc = docs.get(url) or {}
            excerpt = str(doc.get("claim_support_excerpt") or claim.get("excerpt") or doc.get("excerpt") or "")
            required = list(doc.get("required_tokens") or [])
            supports = excerpt_supports_claim(str(claim.get("text") or ""), excerpt, required=required or None)
            rows.append(
                {
                    "claim": claim.get("text"),
                    "source_url": url,
                    "publisher": claim.get("publisher"),
                    "as_of": claim.get("observed_at") or claim.get("valid_from") or doc.get("published_at"),
                    "status": claim.get("status"),
                    "polarity": claim.get("polarity"),
                    "excerpt": excerpt[:320],
                    "claim_support_excerpt": excerpt,
                    "excerpt_start": doc.get("excerpt_start"),
                    "excerpt_end": doc.get("excerpt_end"),
                    "body_hash": doc.get("body_hash"),
                    "supports_claim": supports,
                    "used_title": False,
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                }
            )
    return rows


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
    fomc = next((row for row in events if row.get("event_type") == "central_bank_rates"), {})
    fomc_metrics = _metrics(fomc) if fomc else {}
    hormuz = iran
    hormuz_metrics = _metrics(hormuz) if hormuz else {}
    hormuz_urls = {str(row.get("source_url") or "") for row in (hormuz.get("sources") or [])}
    ofac_catalog = any("sanctions-programs-and-country-information" in url for url in hormuz_urls)
    e2_independent = any(int((_metrics(event).get("independent_publisher_count") or 0) >= 2) and int(_metrics(event).get("document_count") or 0) >= 3 for event in events)
    e2_fomc_docs = (
        int(fomc_metrics.get("document_count") or 0) >= 3
        and int(fomc_metrics.get("publisher_count") or 0) == 1
        and int(fomc_metrics.get("independent_publisher_count") or 0) == 1
        and {"statement", "projections", "minutes"}.issubset(set(fomc_metrics.get("document_roles") or []))
    )
    e3_observed = any(
        int((_metrics(event).get("conflict_count") or 0) >= 1)
        and int((_metrics(event).get("independent_publisher_count") or 0) >= 2)
        for event in events
    )
    nvda_types = {row.get("event_type") for row in (stocks["NVDA"].get("events") or [])}
    jpm_types = {row.get("event_type") for row in (stocks["JPM"].get("events") or [])}
    hormuz_eia_only = bool(hormuz_urls) and all("eia.gov" in url for url in hormuz_urls) and not ofac_catalog
    e4_observed = (
        "war_sanctions" in xom_types
        and "war_sanctions" not in aapl_types
        and "war_sanctions" in nvda_types
        and "war_sanctions" in jpm_types
        and bool(xom_why)
        and bool(nvda_why)
        and bool(jpm_why)
        and xom_why != nvda_why
        and (not replay_mode or hormuz_eia_only)
    )
    hormuz_what = (hormuz.get("analysis") or {}).get("what_changes")
    hormuz_what_text = hormuz_what.get("text") if isinstance(hormuz_what, dict) else str(hormuz_what or "")
    e9_text = " ".join(
        [
            hormuz_what_text,
            " ".join(str(item.get("what_changes") or "") for item in (hormuz.get("timeline") or [])),
            " ".join((hormuz.get("analysis") or {}).get("evolution_path") or []),
        ]
    )
    e9_observed = (
        hormuz.get("status") in {"updated", "revoked"}
        and len(hormuz.get("timeline") or []) >= 3
        and "中断" in e9_text
        and "需求缓冲" in e9_text
        and ("重开" in e9_text or "供应恢复" in e9_text)
        and int(hormuz_metrics.get("superseded_count") or 0) >= 2
        and int(hormuz_metrics.get("conflict_count") or 0) == 0
    )
    e6_dom = (shot_center.get("google") == "not_configured") and shot_center.get("ready") is True
    e8_dom = all(str(href).startswith("http") for href in shot_center.get("analysisHrefs") or []) and bool(shot_center.get("analysisHrefs"))
    e10_dom = {"what", "credibility", "why", "duration", "invalidation"}.issubset(set(shot_center.get("answers") or []))
    official_feeds_ok = sum(1 for row in live_providers.values() if row.get("status") == "ok" and int(row.get("event_count") or 0) > 0)
    provider_health_gate = official_feeds_ok == 3 and all(
        row.get("status") == "ok" and int(row.get("event_count") or 0) > 0 for row in live_providers.values()
    )
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
    pack = {}
    if replay_mode:
        try:
            from stock_pm.events.replay import load_recorded_pack

            pack = load_recorded_pack()
        except Exception:
            pack = {}
    claim_evidence = _claim_evidence_rows([row for row in (fomc, hormuz) if row], pack)
    current_evidence = [row for row in claim_evidence if row.get("status") != "superseded"]
    e8_semantic = bool(current_evidence) and all(
        row.get("supports_claim")
        and row.get("publisher")
        and row.get("as_of")
        and row.get("source_url")
        and row.get("claim_support_excerpt")
        for row in current_evidence
    )
    if not replay_mode:
        live_excerpts = [
            row
            for row in (lead.get("claims") or [])
            if row.get("excerpt") and row.get("status") != "superseded"
        ]
        from stock_pm.events.evidence import excerpt_supports_claim as _excerpt_ok

        live_excerpt_ok = all(
            _excerpt_ok(str(row.get("text") or ""), str(row.get("excerpt") or "")) for row in live_excerpts
        ) if live_excerpts else True
        e8_semantic = (
            bool(refs)
            and all(str(row.get("source_url") or "").startswith("http") and row.get("publisher") for row in refs)
            and live_excerpt_ok
        )
    framework = {
        "E1": ("official_fact" in fact_types and (e1_fixture_dom if fixture_mode else e1_live_dom)),
        "E2": e2_independent or (replay_mode and e2_fomc_docs),
        "E3": e3_observed,
        "E4": e4_observed,
        "E5": (vix.get("analysis") or {}).get("vix_role") == "risk_confirmation_only" or not vix,
        "E6": google_honest and fixture_honest and e6_dom,
        "E7": cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and ev_cover.get("does_not_affect") == ["price", "earnings", "macro_rates"]
        and overall.get("level") != "L0",
        "E8": bool(refs) and e8_dom and e8_semantic,
        "E9": e9_observed,
        "E10": e10_dom and shot_center.get("ready") is True,
    }
    live = {
        "E1": production and e1_live_dom and live_originals and official_feeds_ok >= 1,
        "E2": production and e2_independent and live_originals,
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
            "E2": e2_independent,
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
        "E2": e2_fomc_docs and live_originals,
        "E3": e3_observed,
        "E4": e4_observed and live_originals and hormuz_eia_only,
        "E5": framework["E5"],
        "E6": google_honest and e6_dom and replay_honest,
        "E7": framework["E7"],
        "E8": framework["E8"] and live_originals and e8_semantic,
        "E9": e9_observed and bool(shot_center.get("timeline") or hormuz.get("timeline")),
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
        if not e3_observed:
            verdict["E3"] = UNVERIFIED
        must = MUST_CAPABILITY
        capability_e1_e10_gate = (
            all(verdict[key] == "PASS" for key in must)
            and sum(1 for value in verdict.values() if value == "PASS") >= 8
            and replay_honest
        )
        live_e1_e10_gate = None
        gate = capability_e1_e10_gate
        note = (
            "capability_e1_e10_gate only. RECORDED REPLAY may use the production pipeline. "
            "E3 is UNVERIFIED without a same-window multi-publisher conflict and is not PASS. "
            "provider_health_gate and live_e1_e10_gate are separate fields."
        )
    else:
        verdict = live_verdict
        must = MUST_LIVE
        live_pass = sum(1 for value in verdict.values() if value == "PASS")
        live_e1_e10_gate = live_pass == 10 and fixture_honest
        capability_e1_e10_gate = None
        gate = live_e1_e10_gate
        note = (
            "live_e1_e10_gate only. UNOBSERVED is not PASS. "
            "provider_health_gate is independent and must not be written as E1–E10 PASS."
        )
    return {
        "lane": lane,
        "data_mode": cover.get("data_mode"),
        "live": cover.get("live"),
        "recorded_replay": replay_mode,
        "provider_health_gate": provider_health_gate,
        "live_e1_e10_gate": live_e1_e10_gate,
        "capability_e1_e10_gate": capability_e1_e10_gate,
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
        "ui_gates": {
            "provider_health_gate": shot_center.get("providerHealthGate"),
            "live_e1_e10_gate": shot_center.get("liveE1E10Gate"),
            "capability_e1_e10_gate": shot_center.get("capabilityE1E10Gate"),
        },
        "claim_excerpts_dom": shot_center.get("claimExcerpts") or [],
        "fomc_metrics": fomc_metrics,
        "hormuz_metrics": hormuz_metrics,
        "claim_evidence": claim_evidence,
        "e8_semantic": e8_semantic,
        "ofac_bound_to_hormuz": ofac_catalog,
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
