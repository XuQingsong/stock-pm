#!/usr/bin/env python3
"""Black-box U1–U10 + rendered decision screenshots for phase 5A P0.

Usage:
  ACCEPT_BASE=http://127.0.0.1:8767 ACCEPT_INJECT=http://127.0.0.1:8768 \\
    python3 scripts/accept_u1_u10.py

Production-like ACCEPT_BASE must ignore ?inject=. ACCEPT_INJECT is the
test/preview process with ENABLE_DECISION_INJECT=true and APP_ENV=test.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

SECRET_RE = re.compile(r"(api[_-]?key|apikey|secret|password|authorization|sk-|Bearer )", re.I)
OUT = Path(os.environ.get("ACCEPT_OUT", "/opt/cursor/artifacts/p0-5a"))
BASE = os.environ.get("ACCEPT_BASE", "http://127.0.0.1:8767").rstrip("/")
INJECT = os.environ.get("ACCEPT_INJECT", "http://127.0.0.1:8768").rstrip("/")
CDP = os.environ.get("ACCEPT_CDP", "http://127.0.0.1:9333")


def get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode()


def ds(health: dict, *names: str) -> dict:
    for row in health.get("datasets") or []:
        if row.get("dataset") in names or row.get("metric") in names:
            return row
    return {}


def codes(view: dict) -> set[str]:
    return {row.get("code") for row in view.get("gaps") or []}


def facts(view: dict, *, background: bool = False) -> set[str]:
    rows = view.get("market_background") if background else view.get("facts")
    return {row.get("metric") for row in rows or []}


def nfp_row(view: dict) -> dict:
    for row in view.get("market_background") or []:
        if row.get("metric") == "nfp":
            return row
    for row in view.get("facts") or []:
        if row.get("metric") == "nfp":
            return row
    return {}


def api_fact(view: dict, metric: str) -> dict:
    for row in list(view.get("facts") or []) + list(view.get("market_background") or []):
        if row.get("metric") == metric:
            return row
    risk = view.get("risk_state") or {}
    if metric == "vix" and risk:
        return risk
    return {}


def href_matches(href: str, expected: str) -> bool:
    if not href.startswith("http"):
        return False
    if not expected:
        return True
    return expected.split("?")[0] in href or href.split("?")[0] in expected


def drawer_matches(row: dict, metric: str, expected: dict) -> bool:
    heading = str(row.get("heading") or "").lower()
    text = str(row.get("text") or "").lower()
    return (
        row.get("metric") == metric
        and bool(row.get("source"))
        and bool(row.get("as_of"))
        and bool(row.get("unit"))
        and bool(row.get("status"))
        and href_matches(str(row.get("href") or ""), str(expected.get("http_source") or ""))
        and metric in (heading + " " + text)
        and (metric == "close" or "事实详情 · close" not in heading)
    )


def score(nvda, aapl, nok, h_nvda, pub, gold, nfp, prior, news, options, pred, js, page, dom=None) -> dict:
    ok_h = {
        "cpi": ds(h_nvda, "macro_cpi", "cpi").get("status"),
        "us2y": ds(h_nvda, "macro_rates_confirm", "us2y").get("status"),
        "vix": ds(h_nvda, "macro_vix", "vix").get("status"),
        "nfp": ds(h_nvda, "macro_nfp", "nfp").get("status"),
        "close": ds(h_nvda, "daily_price_bars", "close").get("status"),
        "eps": ds(h_nvda, "earnings_reports", "eps").get("status"),
    }
    nfp_fact = nfp_row(nvda)
    path = nvda.get("rates_path") or {}
    risk = nvda.get("risk_state") or {}
    layer_change = next((row for row in nvda.get("layers") or [] if row.get("id") == "change"), {})
    dxy = ds(h_nvda, "macro_dxy", "dxy")
    pred_blob = json.dumps(pred, ensure_ascii=False)
    pages = (dom or {}).get("pages") or {}
    drawers = (dom or {}).get("drawers") or {}

    def snap(symbol: str) -> dict:
        return pages.get(symbol) or {}

    def main(symbol: str) -> str:
        return snap(symbol).get("mainText") or ""

    cpi_copied = re.compile(r"CPIAUCSL|CPI-U|CPI‑U", re.I)
    u3_dom = (
        snap("NVDA").get("ready") is True
        and snap("NVDA").get("loading") is False
        and snap("NVDA").get("whatChangesVisible") is True
        and snap("NVDA").get("layers") == ["fact", "change", "expectation", "impact", "what_changes"]
        and "Fact → Change → Expectation → Impact → What changes" in main("NVDA")
        and "改变了哪个判断" in main("NVDA")
    )
    u4_dom = (
        bool(cpi_copied.search(main("NVDA")))
        and not cpi_copied.search(main("AAPL"))
        and not cpi_copied.search(main("NOK"))
        and "没有高估值久期暴露" in main("AAPL")
        and "没有高估值久期暴露" in main("NOK")
        and snap("AAPL").get("visibleChainGroups") == 0
        and snap("NOK").get("visibleChainGroups") == 0
        and snap("NVDA").get("visibleChainGroups") == 0
    )
    u9_dom = all(
        drawer_matches(drawers.get(metric) or {}, metric, api_fact(nvda, metric))
        for metric in ("cpi", "us2y", "vix")
    )
    u10_impact = (
        bool(path.get("direction"))
        and bool(path.get("horizon"))
        and snap("NVDA").get("impactDirection") == path.get("direction")
        and snap("NVDA").get("impactHorizon") == path.get("horizon")
        and "影响方向" in main("NVDA")
        and "期限" in main("NVDA")
    )
    results = {
        "U1": h_nvda.get("runtime") == "real"
        and h_nvda.get("synthetic") is False
        and all(ok_h[key] == "ok" for key in ("cpi", "vix", "nfp", "close", "eps")),
        "U2": nfp_fact.get("value") is not None
        and nfp_fact.get("previous") is not None
        and abs(float(nfp_fact["previous"])) < 10000
        and nfp_fact.get("series") == "PAYEMS"
        and nfp_fact.get("unit") == "thousands"
        and "存量" in (nfp_fact.get("formula") or ""),
        "U3": path.get("status") == "visible"
        and [node.get("id") for node in path.get("nodes") or []]
        == ["cpi", "us2y", "discount", "industry", "exposure", "price_pressure"]
        and len(path.get("edges") or []) >= 5
        and "Fact → Change → Expectation → Impact → What changes" in js
        and "data-decision-ready" in js
        and u3_dom,
        "U4": "cpi" in facts(nvda)
        and "us2y" in facts(nvda)
        and "cpi" not in facts(aapl)
        and "cpi" not in facts(nok)
        and (aapl.get("rates_path") or {}).get("status") == "not_applicable"
        and (nok.get("rates_path") or {}).get("status") == "not_applicable"
        and "gold" in facts(nvda, background=True)
        and u4_dom,
        "U5": risk.get("affects") == "risk_state"
        and risk.get("does_not_imply") == "个股涨跌方向"
        and "missing_vix" not in codes(nvda)
        and all(item.get("metric") != "vix" for item in layer_change.get("items") or []),
        "U6": not pub.get("inject")
        and gold.get("inject") == ["missing_gold"]
        and nfp.get("inject") == ["missing_nfp"]
        and any(row.get("code") == "missing_gold" and row.get("affects_chain") == "commodity" for row in gold.get("gaps") or [])
        and any(row.get("code") == "missing_nfp" and row.get("affects_chain") == "labor" for row in nfp.get("gaps") or [])
        and any(row.get("code") == "missing_prior_consensus" and row.get("affects_chain") == "earnings" for row in prior.get("gaps") or [])
        and any(row.get("code") == "missing_news" and row.get("affects_chain") == "news" for row in news.get("gaps") or [])
        and any(row.get("code") == "missing_options" and row.get("affects_chain") == "options" for row in options.get("gaps") or [])
        and "missing_cpi" not in codes(gold)
        and "missing_cpi" not in codes(nfp)
        and (gold.get("overall") or {}).get("level") != "L0"
        and (nfp.get("overall") or {}).get("level") != "L0",
        "U7": nvda.get("can_form_direction") is False
        and pred.get("direction_withheld") is True
        and pred.get("upside_bound_pct") is None
        and pred.get("upside_price") is None
        and "当天补涨约" not in pred_blob
        and "期间跌幅不超过1%" not in pred_blob
        and "决策未形成方向" in (pred.get("therefore") or ""),
        "U8": dxy.get("status") in {"not_configured", "unavailable"}
        and "google news" not in js.lower()
        and "short_mid_long" not in js,
        "U9": str(api_fact(nvda, "cpi").get("http_source") or "").startswith("http")
        and "sourceLink" in js
        and "fact-drawer" in page
        and "extraQuery" in js
        and u9_dom,
        "U10": "missing_cpi" not in codes(nvda)
        and "missing_rates_confirmation" not in codes(nvda)
        and "missing_vix" not in codes(nvda)
        and ok_h["cpi"] == "ok"
        and ok_h["vix"] == "ok"
        and u10_impact,
    }
    verdict = {key: ("PASS" if value else "FAIL") for key, value in results.items()}
    must = ["U2", "U3", "U4", "U6", "U7", "U9", "U10"]
    return {
        "verdict": verdict,
        "pass_count": sum(1 for value in results.values() if value),
        "must_fail": [key for key in must if not results[key]],
        "gate": all(results[key] for key in must) and sum(1 for value in results.values() if value) >= 8,
        "health_status": ok_h,
        "nfp": {
            "value": nfp_fact.get("value"),
            "previous": nfp_fact.get("previous"),
            "series": nfp_fact.get("series"),
            "unit": nfp_fact.get("unit"),
        },
        "inject": {
            "public": pub.get("inject"),
            "gold_chain": [row.get("affects_chain") for row in gold.get("gaps") or [] if row.get("code") == "missing_gold"],
            "nfp_chain": [row.get("affects_chain") for row in nfp.get("gaps") or [] if row.get("code") == "missing_nfp"],
        },
    }


def start_cdp() -> subprocess.Popen | None:
    try:
        urllib.request.urlopen(f"{CDP}/json", timeout=1)
        return None
    except Exception:
        profile = Path("/tmp/chrome-accept-p0")
        profile.mkdir(exist_ok=True)
        return subprocess.Popen(
            [
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-sandbox",
                f"--user-data-dir={profile}",
                "--remote-debugging-port=9333",
                "--remote-allow-origins=*",
                "--window-size=1400,1100",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def capture_pages() -> dict[str, str]:
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
    call("DOM.enable")

    def wait_ready(url: str, wait: float = 45) -> str:
        call("Page.navigate", {"url": url})
        deadline = time.time() + wait
        text = ""
        while time.time() < deadline:
            time.sleep(0.8)
            ev = call(
                "Runtime.evaluate",
                {
                    "expression": """(() => {
                      const body = document.getElementById('decision-body') || document.getElementById('decision-module');
                      const ready = body && body.getAttribute('data-decision-ready') === '1';
                      const loading = document.body.innerText.includes('正在加载动态判断');
                      return JSON.stringify({
                        ready,
                        loading,
                        text: document.body.innerText.slice(0, 20000),
                        hasLayers: Boolean(document.querySelector('.causal-flow'))
                      });
                    })()""",
                    "returnByValue": True,
                },
            )
            payload = json.loads(((ev.get("result") or {}).get("result") or {}).get("value") or "{}")
            text = payload.get("text") or ""
            if payload.get("ready") and payload.get("hasLayers") and not payload.get("loading"):
                return text
        raise RuntimeError(f"decision module did not finish rendering: {url}")

    def isolate_module(*, keep_banner: bool = False, open_drawer: bool = False) -> dict:
        ev = call(
            "Runtime.evaluate",
            {
                "expression": f"""(() => {{
                  document.querySelectorAll('.stock-header, .tabs, #stock-pm-shell, #tab-content').forEach((n) => {{
                    n.style.setProperty('display', 'none', 'important');
                    n.style.setProperty('position', 'static', 'important');
                  }});
                  const keep = document.getElementById('decision-module');
                  document.querySelectorAll('main.page-shell > *').forEach((n) => {{
                    if (keep && n !== keep && !keep.contains(n)) n.style.setProperty('display', 'none', 'important');
                  }});
                  const flow = document.querySelector('.causal-flow');
                  const body = document.getElementById('decision-body');
                  const banner = document.querySelector('.decision-banner');
                  const gaps = document.querySelector('.decision-gaps');
                  if (body) {{
                    [...body.children].forEach((n) => {{
                      const keepChild = n === flow || ({str(keep_banner).lower()} && (n === banner || n === gaps));
                      if (!keepChild) n.style.setProperty('display', 'none', 'important');
                    }});
                  }}
                  const bg = document.querySelector('.market-background');
                  if (bg) bg.open = true;
                  if ({str(open_drawer).lower()}) {{
                    const btn = document.querySelector('.causal-layer[data-layer="fact"] .fact-link[data-fact-id="cpi"]')
                      || document.querySelector('.causal-layer[data-layer="fact"] .fact-link');
                    if (btn) btn.click();
                  }}
                  window.scrollTo(0, 0);
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                  const node = flow || body;
                  const r = node ? node.getBoundingClientRect() : {{width: 1280, height: 1100}};
                  const heading = (flow && flow.querySelector('h3') && flow.querySelector('h3').innerText) || '';
                  const layerTitles = [...document.querySelectorAll('.causal-layer .chain-kicker')].map((n) => n.innerText);
                  return {{
                    ready: Boolean(document.querySelector('[data-decision-ready="1"]')),
                    heading,
                    layerTitles,
                    loading: document.body.innerText.includes('正在加载动态判断'),
                    width: Math.max(1280, Math.ceil(r.width + 24)),
                    height: Math.min(4800, Math.max(1100, Math.ceil(r.height + 48)))
                  }};
                }})()""",
                "returnByValue": True,
            },
        )
        return ((ev.get("result") or {}).get("result") or {}).get("value") or {}

    def clip(dest: Path, *, keep_banner: bool = False, open_drawer: bool = False) -> dict:
        info = isolate_module(keep_banner=keep_banner, open_drawer=open_drawer)
        if info.get("loading"):
            raise RuntimeError(f"still loading when capturing {dest.name}")
        if not info.get("ready"):
            raise RuntimeError(f"decision module not ready when capturing {dest.name}")
        call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": int(info.get("width") or 1280),
                "height": int(info.get("height") or 1400),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        time.sleep(0.25)
        info = isolate_module(keep_banner=keep_banner, open_drawer=open_drawer)
        png = call("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": True})
        dest.write_bytes(base64.b64decode(png["result"]["data"]))
        return info

    def page_snapshot() -> dict:
        ev = call(
            "Runtime.evaluate",
            {
                "expression": """(() => {
                  const body = document.getElementById('decision-body') || document.body;
                  const clone = body.cloneNode(true);
                  clone.querySelectorAll('.market-background, .decision-chain-fold, .decision-facts, dialog').forEach((n) => n.remove());
                  const path = document.querySelector('.rates-path');
                  const what = document.querySelector('.causal-layer[data-layer="what_changes"]');
                  return {
                    ready: Boolean(document.querySelector('[data-decision-ready="1"]')),
                    loading: document.body.innerText.includes('正在加载动态判断'),
                    heading: (document.querySelector('.causal-flow > h3') || {}).innerText || '',
                    layers: [...document.querySelectorAll('.causal-layer')].map((n) => n.getAttribute('data-layer')),
                    whatChangesVisible: Boolean(what) && ((what.innerText || '').includes('改变了哪个判断')),
                    mainText: clone.innerText || '',
                    visibleChainGroups: document.querySelectorAll('.causal-flow .chain-group, main.page-shell > .chain-groups, #decision-body > .chain-groups').length,
                    impactDirection: path ? path.getAttribute('data-direction') : null,
                    impactHorizon: path ? path.getAttribute('data-horizon') : null,
                    sourceHrefs: [...document.querySelectorAll('.causal-flow a.source-link')].map((a) => a.href)
                  };
                })()""",
                "returnByValue": True,
            },
        )
        return ((ev.get("result") or {}).get("result") or {}).get("value") or {}

    def open_drawer(metric: str) -> dict:
        ev = call(
            "Runtime.evaluate",
            {
                "expression": f"""(() => {{
                  const drawer = document.getElementById('fact-drawer');
                  if (drawer && drawer.open) drawer.close();
                  const btn = document.querySelector('.fact-link[data-fact-id="{metric}"]')
                    || document.querySelector('.fact-link[data-metric="{metric}"]');
                  if (!btn) return {{metric: null, error: 'missing-button-{metric}'}};
                  btn.click();
                  const root = document.getElementById('fact-drawer-body');
                  const heading = root && root.querySelector('h3');
                  const meta = root && root.querySelector('[data-drawer-source]');
                  const link = root && root.querySelector('a.source-link');
                  return {{
                    metric: heading ? heading.getAttribute('data-drawer-metric') : null,
                    heading: heading ? heading.innerText : '',
                    source: meta ? meta.getAttribute('data-drawer-source') : '',
                    as_of: meta ? meta.getAttribute('data-drawer-as-of') : '',
                    unit: meta ? meta.getAttribute('data-drawer-unit') : '',
                    status: meta ? meta.getAttribute('data-drawer-status') : '',
                    href: link ? link.href : '',
                    text: root ? root.innerText : '',
                    open: Boolean(drawer && drawer.open)
                  }};
                }})()""",
                "returnByValue": True,
            },
        )
        return ((ev.get("result") or {}).get("result") or {}).get("value") or {}

    OUT.mkdir(parents=True, exist_ok=True)
    texts = {}
    pages = {}
    texts["NVDA"] = wait_ready(f"{BASE}/stock/NVDA")
    pages["NVDA"] = page_snapshot()
    drawers = {
        "cpi": open_drawer("cpi"),
    }
    clip(OUT / "nvda-drawer-cpi.png", open_drawer=False)
    drawers["us2y"] = open_drawer("us2y")
    clip(OUT / "nvda-drawer-us2y.png", open_drawer=False)
    drawers["vix"] = open_drawer("vix")
    clip(OUT / "nvda-drawer-vix.png", open_drawer=False)
    call("Runtime.evaluate", {"expression": "(() => { const d=document.getElementById('fact-drawer'); if (d && d.open) d.close(); return true; })()", "returnByValue": True})
    nvda_info = clip(OUT / "nvda-causal.png")
    clip(OUT / "nvda-facts.png")
    texts["AAPL"] = wait_ready(f"{BASE}/stock/AAPL")
    pages["AAPL"] = page_snapshot()
    aapl_info = clip(OUT / "aapl-causal.png")
    texts["NOK"] = wait_ready(f"{BASE}/stock/NOK")
    pages["NOK"] = page_snapshot()
    nok_info = clip(OUT / "nok-causal.png")
    texts["_capture_meta"] = {
        "NVDA": nvda_info,
        "AAPL": aapl_info,
        "NOK": nok_info,
    }

    for token, name in (
        ("missing_gold", "inject-gold.png"),
        ("missing_nfp", "inject-nfp.png"),
        ("missing_prior_consensus", "inject-prior.png"),
        ("missing_news", "inject-news.png"),
        ("missing_options", "inject-options.png"),
    ):
        texts[token] = wait_ready(f"{INJECT}/stock/NVDA?inject={token}")
        clip(OUT / name, keep_banner=True)

    texts["public_inject"] = wait_ready(f"{BASE}/stock/NVDA?inject=missing_gold,missing_nfp")
    clip(OUT / "inject-public-ignored.png", keep_banner=True)
    ws.close()
    if proc:
        proc.terminate()
    return {"texts": texts, "pages": pages, "drawers": drawers, "capture_meta": texts["_capture_meta"]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    nvda = get(f"{BASE}/api/stock/NVDA/decision")
    aapl = get(f"{BASE}/api/stock/AAPL/decision")
    nok = get(f"{BASE}/api/stock/NOK/decision")
    h_nvda = get(f"{BASE}/api/stock/NVDA/data-health")
    pub = get(f"{BASE}/api/stock/NVDA/decision?inject=missing_gold,missing_nfp")
    gold = get(f"{INJECT}/api/stock/NVDA/decision?inject=missing_gold")
    nfp = get(f"{INJECT}/api/stock/NVDA/decision?inject=missing_nfp")
    prior = get(f"{INJECT}/api/stock/NVDA/decision?inject=missing_prior_consensus")
    news = get(f"{INJECT}/api/stock/NVDA/decision?inject=missing_news")
    options = get(f"{INJECT}/api/stock/NVDA/decision?inject=missing_options")
    try:
        pred = get(f"{BASE}/api/stock/NVDA/prediction")
    except urllib.error.HTTPError:
        pred = get(f"{BASE}/api/shell?symbol=NVDA").get("prediction") or {}
    js = html(f"{BASE}/static/stock.js")
    page = html(f"{BASE}/stock/NVDA")
    page_texts = {}
    screenshot_error = None
    captured = {}
    try:
        captured = capture_pages()
        page_texts = captured.get("texts") or {}
    except Exception as exc:
        screenshot_error = str(exc)
        captured = {"pages": {}, "drawers": {}, "capture_meta": {}, "texts": {}}
    report = score(
        nvda, aapl, nok, h_nvda, pub, gold, nfp, prior, news, options, pred, js, page,
        dom={"pages": captured.get("pages") or {}, "drawers": captured.get("drawers") or {}},
    )
    report["drawers"] = captured.get("drawers") or {}
    report["capture_meta"] = captured.get("capture_meta")
    evidence = {
        "public_inject": {"inject": pub.get("inject"), "overall": pub.get("overall")},
        "missing_gold": {
            "inject": gold.get("inject"),
            "gaps": [row for row in gold.get("gaps") or [] if row.get("code") == "missing_gold"],
            "overall": gold.get("overall"),
            "has_missing_cpi": "missing_cpi" in codes(gold),
        },
        "missing_nfp": {
            "inject": nfp.get("inject"),
            "gaps": [row for row in nfp.get("gaps") or [] if row.get("code") == "missing_nfp"],
            "overall": nfp.get("overall"),
            "has_missing_cpi": "missing_cpi" in codes(nfp),
        },
        "missing_prior_consensus": {
            "inject": prior.get("inject"),
            "gaps": [row for row in prior.get("gaps") or [] if row.get("code") == "missing_prior_consensus"],
        },
        "missing_news": {
            "inject": news.get("inject"),
            "gaps": [row for row in news.get("gaps") or [] if row.get("code") == "missing_news"],
        },
        "missing_options": {
            "inject": options.get("inject"),
            "gaps": [row for row in options.get("gaps") or [] if row.get("code") == "missing_options"],
        },
        "nfp": report["nfp"],
        "rates_path": {
            "NVDA": (nvda.get("rates_path") or {}).get("status"),
            "AAPL": (aapl.get("rates_path") or {}).get("status"),
            "NOK": (nok.get("rates_path") or {}).get("status"),
        },
    }
    evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2)
    if SECRET_RE.search(evidence_text):
        evidence_text = SECRET_RE.sub("REDACTED", evidence_text)
    (OUT / "api-evidence.json").write_text(evidence_text)
    report["page"] = {
        symbol: {
            "layers": "Fact → Change → Expectation → Impact → What changes" in text,
            "nfp_stock_bug": "158913" in text,
            "pct_forecast": "当天补涨约" in text or "期间跌幅不超过1%" in text,
            "loading": "正在加载动态判断" in text,
        }
        for symbol, text in page_texts.items()
        if symbol in {"NVDA", "AAPL", "NOK"}
    }
    if screenshot_error:
        report["screenshot_error"] = screenshot_error
    if any(row.get("loading") for row in report["page"].values()):
        report["verdict"]["U3"] = "FAIL"
        report["must_fail"] = sorted(set(report["must_fail"] + ["U3"]))
        report["gate"] = False
        screenshot_error = screenshot_error or "captured a still-loading decision module"
    report["screenshots"] = sorted(path.name for path in OUT.glob("*.png"))
    dumped = json.dumps(report, ensure_ascii=False, indent=2)
    if SECRET_RE.search(dumped):
        dumped = SECRET_RE.sub("REDACTED", dumped)
    (OUT / "u1-u10.json").write_text(dumped)
    print(dumped)
    if screenshot_error:
        print("screenshot_error:", screenshot_error)
    return 0 if report["gate"] and not screenshot_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
