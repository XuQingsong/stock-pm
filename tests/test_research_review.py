from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.research import api as research_api
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.review_view import build_research_review
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from stock_pm.research.workflow import run_new_ticker_research


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "research"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def service_with_fixture(ticker: str, filename: str) -> ResearchService:
    source = DictPackSource.from_mapping(ticker, load_fixture(filename))
    return ResearchService(InMemoryResearchStore(), pack_source=source)


def test_research_review_pages_render() -> None:
    client = TestClient(api.app)
    page = client.get("/research/AVGO")
    assert page.status_code == 200
    assert "research_review.js" in page.text
    assert "Assumption tree" not in page.text  # filled after fetch; shell is empty
    assert client.get("/research/COHR").status_code == 200
    assert client.get("/research/XOM").status_code == 200
    redirect = client.get("/research", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("/research/AVGO")


def test_research_review_payload_from_fixtures(monkeypatch) -> None:
    for ticker, filename in (("AVGO", "avgo.json"), ("COHR", "cohr.json"), ("XOM", "xom.json")):
        svc = service_with_fixture(ticker, filename)
        run_new_ticker_research(svc, ticker, max_depth=3, max_tasks=24, adjudicate=True)
        monkeypatch.setattr(research_api, "_service_override", svc)
        client = TestClient(api.app)
        response = client.get(f"/api/research/{ticker}/review")
        assert response.status_code == 200, ticker
        body = response.json()
        assert body["ticker"] == ticker
        hero = body["hero"]
        for key in (
            "core_thesis",
            "confidence",
            "short_term_view",
            "mid_term_view",
            "long_term_view",
            "valuation_status",
            "strongest_assumption",
            "weakest_assumption",
            "weakest_layer",
            "biggest_unresolved_gap",
        ):
            assert key in hero, key
        assert set(body["cases"]) == {"bear", "market_implied", "base", "bull"}
        assert body["assumption_tree"]["branches"]
        assert "history" in body["delivery_history"]
        assert "direct_issuer_cross_check" in body["customer_side"]
        assert "industry_demand_confirmation" in body["customer_side"]
        assert body["market_implied"]["title"] == "当前股价隐含的增长预期"
        assert "Market implies 10% growth" not in json.dumps(body)
        assert body["ui"]["headline"]
        assert len(body["ui"]["key_assumptions"]) == 3
        assert "customer_capex" not in body["ui"]["headline"]
        assert "management_guidance" not in json.dumps(body["ui"])
        blob = json.dumps(body, default=str).lower()
        assert "30gw" not in blob
        assert "if ticker ==" not in blob
        for section in (
            "assumption_tree",
            "commitment_ledger",
            "delivery_history",
            "customer_side",
            "revenue_bridge",
            "causal_chain",
            "market_implied",
            "market_reaction",
            "valuation",
            "monitoring",
            "thesis_history",
        ):
            assert section in body, section


def test_research_review_sparse_ticker_does_not_500(monkeypatch) -> None:
    svc = ResearchService(InMemoryResearchStore())
    monkeypatch.setattr(research_api, "_service_override", svc)
    client = TestClient(api.app)
    response = client.get("/api/research/ZZZZ/review")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ZZZZ"
    assert body["missing"]
    assert body["hero"]["core_thesis"]


def test_build_research_review_is_generic() -> None:
    for rel in ("src/stock_pm/research/review_view.py", "src/stock_pm/research/review_copy.py"):
        src = Path(rel).read_text(encoding="utf-8")
        assert "30GW" not in src
        assert "broadcom" not in src.lower()
        assert "if ticker ==" not in src
    svc = service_with_fixture("AVGO", "avgo.json")
    run_new_ticker_research(svc, "AVGO", max_depth=2, max_tasks=16, adjudicate=True)
    payload = build_research_review(svc, "AVGO")
    assert payload["causal_chain"]["layers"]
    assert payload["delivery_history"]["history"] is not None
    assert isinstance(payload["customer_side"]["direct_issuer_cross_check"], int)
    assert payload["ui"]["key_assumptions"]


def test_review_static_has_no_hardcoded_thesis() -> None:
    static = Path("src/stock_pm/static")
    for name in ("research_review.js", "research_review.html", "research_review.css"):
        text = (static / name).read_text(encoding="utf-8")
        assert "30GW" not in text
        assert "Broadcom" not in text
        assert "Market implies 10% growth" not in text
    js = (static / "research_review.js").read_text(encoding="utf-8")
    assert "查看详细研究" in js
    assert "三个关键假设" in js
    assert "客户侧独立验证" in js
    html = (static / "research_review.html").read_text(encoding="utf-8")
    assert "research_review.js" in html
    assert "lang=\"zh-CN\"" in html
    assert "Core Thesis" not in html
