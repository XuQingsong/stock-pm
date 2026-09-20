"""V1 Step 2: market overview page reads only persisted GET /api/market/overview."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.product_read import EMPTY_DOMINANT, build_market_overview
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]
MARKET_HTML = ROOT / "src/stock_pm/static/market.html"
MARKET_JS = ROOT / "src/stock_pm/static/market.js"

PAGE_JARGON = (
    "MarketDominantDriver",
    "TickerMarketSensitivity",
    "product_read",
    "run_brain",
    "GLM",
    "persisted_brain",
)


def _seed_global_ai_driver(store: BrainStore) -> None:
    store.upsert_hypothesis(
        {
            "ticker": "AVGO",
            "canonical_key": "ai_demand",
            "kind": "ai_demand",
            "hypothesis": "AI capex expectations are the live market variable.",
            "name": "AI capex expectations",
            "status": "supported",
            "confidence": "medium",
            "supporting_observations": ["att_ai_tape"],
            "why_it_matters": "半导与云链条定价高度依赖开支路径。",
        }
    )
    store.upsert_hypothesis(
        {
            "ticker": "LITE",
            "canonical_key": "ai_demand",
            "kind": "ai_demand",
            "hypothesis": "Optical names are trading AI capex expectations, not one print.",
            "name": "AI capex expectations",
            "status": "active",
            "confidence": "medium",
        }
    )
    store.upsert_market_attention(
        {
            "ticker": "AVGO",
            "attention_id": "att_ai_tape",
            "name": "云厂商开支指引上修",
            "statement": "Tape is trading AI infrastructure spend expectations.",
        }
    )
    store.insert_state(
        {
            "ticker": "AVGO",
            "state_type": "macro",
            "name": "AI capex expectations",
            "statement": "Hyperscaler AI spend remains the cross-asset variable.",
            "state_key": "ai_capex_expectations",
        }
    )
    store.insert_event(
        {
            "ticker": "AVGO",
            "event_id": "bev_meta_capex",
            "event_type": "capex",
            "title": "Meta 资本开支指引上修",
            "subject": "Meta AI capex",
            "event_date": "2026-09-10",
            "materiality": "material",
        }
    )


def _client(store: BrainStore) -> TestClient:
    research = ResearchService(store=InMemoryResearchStore())
    brain_api._override = {"research": research, "store": store}
    return TestClient(api.app)


def test_market_page_is_wired_to_overview_only() -> None:
    html = MARKET_HTML.read_text(encoding="utf-8")
    js = MARKET_JS.read_text(encoding="utf-8")
    assert "市场现在在交易什么" in html
    assert "/static/market.js" in html
    assert 'const OVERVIEW_PATH = "/api/market/overview"' in js
    assert js.count("fetch(") == 1
    assert js.count("OVERVIEW_PATH") >= 2
    assert "/api/brain" not in js
    assert "run_brain" not in js
    assert "主导程度" in js
    assert "待跨资产验证" in js
    assert "axis-lines" in js
    assert "正在增强" in js
    assert "高位持续" in js
    assert "影响减弱" in js
    assert "基本消退" in js
    assert EMPTY_DOMINANT in js
    for token in PAGE_JARGON:
        assert token not in html
        assert token not in js


def test_market_page_route_and_empty_state(monkeypatch) -> None:
    store = BrainStore()

    def boom(*args, **kwargs):
        raise AssertionError("page path must not call GLM or re-run Brain")

    monkeypatch.setattr("stock_pm.brain.pipeline.run_brain", boom)
    monkeypatch.setattr("stock_pm.brain.runtime.run_brain_update", boom)
    try:
        client = _client(store)
        page = client.get("/market")
        overview = client.get("/api/market/overview")
    finally:
        brain_api._override = None
    assert page.status_code == 200
    assert "市场现在在交易什么" in page.text
    assert overview.status_code == 200
    body = overview.json()
    assert body["llm_invoked"] is False
    assert body["empty_state"] == EMPTY_DOMINANT
    assert body["dominant_drivers"] == []
    assert body["pricing_axis"] == []
    assert body.get("trigger_events") == []


def test_overview_display_keeps_trigger_layered_and_no_fake_top3(monkeypatch) -> None:
    store = BrainStore()
    _seed_global_ai_driver(store)

    def boom(*args, **kwargs):
        raise AssertionError("page path must not call GLM or re-run Brain")

    monkeypatch.setattr("stock_pm.brain.pipeline.run_brain", boom)
    monkeypatch.setattr("stock_pm.brain.runtime.run_brain_update", boom)
    try:
        client = _client(store)
        body = client.get("/api/market/overview").json()
    finally:
        brain_api._override = None
    assert body["llm_invoked"] is False
    drivers = body["dominant_drivers"]
    assert drivers
    assert len(drivers) <= 3
    assert body["market_state"] == "provisional"
    assert body["pricing_axis"] == []
    assert all(row.get("display_name") == "AI 资本开支" for row in drivers)
    assert all("meta" not in str(row.get("display_name") or "").lower() for row in drivers)
    assert all("meta" not in str(row.get("name") or "").lower() for row in drivers)
    triggers = body["trigger_events"]
    assert triggers
    assert triggers[0]["title"] == "Meta 资本开支指引上修"
    assert triggers[0]["lands_on"] == "AI 资本开支"
    assert "bev_meta_capex" not in triggers[0]["title"]
    assert drivers[0]["supporting_signals"]
    assert drivers[0]["supporting_signals"][0]["label"] == "云厂商开支指引上修"
    assert "att_ai_tape" not in drivers[0]["supporting_signals"][0]["label"]


def test_empty_overview_payload_matches_page_copy() -> None:
    overview = build_market_overview(BrainStore())
    js = MARKET_JS.read_text(encoding="utf-8")
    assert overview["empty_state"] == EMPTY_DOMINANT
    assert EMPTY_DOMINANT in js
    assert overview["llm_invoked"] is False
    assert "Top 1" not in str(overview)
    assert overview["pricing_axis"] == []
