from __future__ import annotations

from datetime import datetime, timezone

from stock_pm.brain.news import hits_to_evidence_bodies
from stock_pm.external.clients import SearchBudget, parse_published, within_days
from stock_pm.external.dedupe import dedupe_documents
from stock_pm.external.extract import deterministic_facts, facts_to_evidence_bodies
from stock_pm.external.layer import (
    build_report,
    cross_check_alphavantage,
    documents_to_news_hits,
    gather_external_intelligence,
    official_documents_from_pack,
)
from stock_pm.external.quality import source_family, source_tier
from stock_pm.external.queries import allocate_queries, fallback_plan


def _doc(**kwargs):
    from stock_pm.external.clients import _document

    defaults = {
        "provider": "tavily",
        "url": "https://www.reuters.com/example",
        "title": "Example",
        "ticker": "AAPL",
        "query": "AAPL news",
        "query_type": "company_news",
        "published_at": "2026-09-01",
        "raw_text": "x" * 50,
        "clean_text": "x" * 50,
    }
    defaults.update(kwargs)
    return _document(**defaults)


def test_discovery_provider_is_not_the_publisher() -> None:
    url = "https://www.reuters.com/technology/broadcom-custom-silicon"
    assert source_tier(url) == 2
    assert source_family(url) == "high_quality_news"
    row = _doc(provider="tavily", url=url, title="Broadcom custom silicon")
    assert row["provider"] == "tavily"
    assert row["source_family"] == "high_quality_news"
    assert row["source_tier"] == 2


def test_dedupe_keeps_better_publisher_copy() -> None:
    reuters = _doc(
        provider="tavily",
        url="https://www.reuters.com/markets/apple-ai",
        title="Apple sees stronger Mac demand from AI labs",
        clean_text=("Apple " * 80),
        raw_text=("Apple " * 80),
    )
    yahoo = _doc(
        provider="exa",
        url="https://finance.yahoo.com/news/apple-sees-stronger-mac-demand",
        title="Apple sees stronger Mac demand from AI labs",
        clean_text="short copy",
        raw_text="short copy",
    )
    kept, removed = dedupe_documents([yahoo, reuters])
    assert removed == 1
    assert len(kept) == 1
    assert "reuters.com" in kept[0]["url"]
    assert "yahoo.com" in str((kept[0].get("metadata") or {}).get("duplicate_urls") or [])


def test_undated_docs_are_not_recent_news() -> None:
    dated = _doc(published_at="2026-09-10", url="https://www.cnbc.com/a")
    undated = _doc(published_at=None, url="https://www.cnbc.com/b", title="undated background")
    hits = documents_to_news_hits([dated, undated], days=30)
    assert [row["url"] for row in hits] == ["https://www.cnbc.com/a"]
    assert within_days(None, 30) is False


def test_search_snippets_are_not_evidence() -> None:
    snippet_hit = {
        "title": "AAPL news",
        "url": "https://www.reuters.com/aapl",
        "snippet": "Search engine summary that must not become a fact.",
        "published_at": "2026-09-10",
    }
    assert hits_to_evidence_bodies("AAPL", [snippet_hit], retrieved_at="2026-09-16T00:00:00+00:00") == []
    short = _doc(clean_text="too short", raw_text="too short")
    short["is_full_text"] = False
    assert deterministic_facts(short) == []
    bodies = facts_to_evidence_bodies(
        "AAPL",
        [{"fact": "Apple sold more Macs.", "excerpt": "Apple sold more Macs.", "source_url": None, "source_time": "2026-09-10"}],
        retrieved_at="2026-09-16T00:00:00+00:00",
    )
    assert bodies == []


def test_extracted_fact_requires_url_and_date() -> None:
    text = (
        "Hyperscalers increased 800G optical demand in 2026 as datacenter capex rose 20%. "
        "Laser and transceiver orders also accelerated for 1.6T deployments. "
    ) * 8
    doc = _doc(
        url="https://www.lightreading.com/800g",
        title="800G demand",
        query_type="industry_news",
        clean_text=text,
        raw_text=text,
    )
    assert doc["is_full_text"] is True
    facts = deterministic_facts(doc)
    assert facts
    bodies = facts_to_evidence_bodies("LITE", facts, retrieved_at="2026-09-16T00:00:00+00:00")
    assert bodies
    assert bodies[0]["source_url"] == "https://www.lightreading.com/800g"
    assert bodies[0]["source_time"]
    assert bodies[0]["excerpt"]


def test_allocate_queries_respects_budget() -> None:
    plan = {
        "queries": [
            {"query": f"q{i}", "query_type": "claim" if i > 2 else "company_news", "provider_hint": "both"}
            for i in range(20)
        ]
    }
    allocated = allocate_queries(plan, tavily_budget=10, exa_budget=10)
    tavily = sum(1 for row in allocated if "tavily" in row["providers"])
    exa = sum(1 for row in allocated if "exa" in row["providers"])
    assert tavily <= 10
    assert exa <= 10
    assert tavily + exa <= 20
    assert all(len(row["providers"]) == 1 for row in allocated)
    assert all(row["providers"] == ["tavily"] for row in allocated if row["query_type"] == "company_news")
    assert all(row["providers"] == ["exa"] for row in allocated if row["query_type"] == "claim")


def test_fallback_plan_has_claim_and_entity_queries() -> None:
    claims = [{"title": "custom silicon growth duration", "statement": "Custom silicon growth may persist with hyperscaler ASICs."}]
    plan = fallback_plan("AVGO", {"company_profile": {"legal_name": "Broadcom Inc", "sector": "semis"}}, {"ticker": "AVGO"}, claims)
    types = {row["query_type"] for row in plan["queries"]}
    assert "claim" in types
    assert any(row.get("entity") == "Google" for row in plan["queries"])
    names = {row["name"] for row in plan["related_entities"]}
    assert "TSMC" in names


def test_alphavantage_does_not_override_sec() -> None:
    warnings = cross_check_alphavantage(
        {"RevenueTTM": "1000000000", "EPS": "1.00"},
        {"company_profile": {"revenue_ttm": 500_000_000, "eps_ttm": 2.0}},
    )
    assert warnings
    assert all("SEC kept" in row["reason"] for row in warnings)


def test_alpha_vantage_timestamp_parses() -> None:
    assert parse_published("20260916T183000") == "2026-09-16"
    assert parse_published("2026-09-16T18:30:00Z") == "2026-09-16"


def test_gather_uses_pack_official_docs_without_live_keys() -> None:
    pack = {
        "ticker": "AAPL",
        "company_profile": {"legal_name": "Apple Inc", "revenue_ttm": 400_000_000_000, "eps_ttm": 8.7},
        "official_documents": [
            {
                "title": "10-Q",
                "url": "https://www.sec.gov/Archives/aapl-10q",
                "published_at": "2026-09-10",
                "text": "Services revenue increased as Apple Intelligence adoption continued. " * 20,
                "source": "sec.gov",
            }
        ],
    }
    result = gather_external_intelligence("AAPL", pack=pack, header={"ticker": "AAPL"}, fetch_live=False)
    assert result["documents"]
    assert result["documents"][0]["source_tier"] == 1
    assert result["report"]["tier1_count"] >= 1
    assert result["report"]["dated_recent_items"] >= 1


def test_gather_mocked_providers_extract_reuters_not_tavily(monkeypatch) -> None:
    long = (
        "Google TPU capex and Meta custom silicon orders are supporting Broadcom AI networking demand in 2026. "
        "Hyperscaler ASIC deployment remains the binding variable for custom silicon duration."
    ) * 3

    def fake_tavily(query, **kwargs):
        row = _doc(
            provider="tavily",
            url="https://www.reuters.com/technology/broadcom-tpu",
            title="Broadcom custom silicon demand",
            query=query,
            query_type=kwargs.get("query_type") or "company_news",
            clean_text=long,
            raw_text=long,
        )
        return [row], {"provider": "tavily", "status": "ok", "hit_count": 1, "usable_count": 1, "high_quality_count": 1, "full_text_count": 1, "dated_count": 1}

    def fake_exa(query, **kwargs):
        row = _doc(
            provider="exa",
            url="https://finance.yahoo.com/news/broadcom-tpu",
            title="Broadcom custom silicon demand",
            query=query,
            query_type=kwargs.get("query_type") or "claim",
            clean_text="yahoo reprint " + long[:200],
            raw_text="yahoo reprint " + long[:200],
        )
        return [row], {"provider": "exa", "status": "ok", "hit_count": 1, "usable_count": 1, "high_quality_count": 0, "full_text_count": 1, "dated_count": 1}

    monkeypatch.setattr("stock_pm.external.layer.tavily_configured", lambda settings: True)
    monkeypatch.setattr("stock_pm.external.layer.exa_configured", lambda settings: True)
    monkeypatch.setattr("stock_pm.external.layer.tavily_search", fake_tavily)
    monkeypatch.setattr("stock_pm.external.layer.exa_search", fake_exa)
    monkeypatch.setattr("stock_pm.external.layer.alphavantage_news", lambda *a, **k: ([], {"provider": "alpha_vantage", "status": "ok", "hit_count": 0}))
    monkeypatch.setattr("stock_pm.external.layer.alphavantage_overview", lambda *a, **k: (None, {"provider": "alpha_vantage", "status": "ok"}))
    monkeypatch.setattr("stock_pm.external.layer.fred_macro_documents", lambda **k: ([], {"provider": "fred", "status": "ok", "hit_count": 0}))
    monkeypatch.setattr("stock_pm.external.layer.fill_missing_bodies", lambda rows, **k: rows)
    monkeypatch.setattr("stock_pm.external.layer.recover_dates_from_pages", lambda rows, **k: 0)
    monkeypatch.setattr(
        "stock_pm.external.layer.generate_search_plan",
        lambda *a, **k: (
            {
                "related_entities": [{"name": "Google", "relation": "customer"}],
                "queries": [
                    {"query": "Broadcom custom silicon customer demand", "query_type": "claim", "provider_hint": "both", "claim_title": "custom silicon"},
                    {"query": "AVGO news", "query_type": "company_news", "provider_hint": "tavily"},
                ],
                "coverage_gaps": [],
            },
            {"step": "external_search_plan", "llm_called": False, "llm_status": "skipped"},
        ),
    )
    result = gather_external_intelligence(
        "AVGO",
        pack={"company_profile": {"legal_name": "Broadcom Inc"}},
        header={"ticker": "AVGO", "company_name": "Broadcom Inc"},
        claims=[{"title": "custom silicon growth duration", "statement": "Custom silicon growth may persist."}],
        fetch_live=True,
        phase="all",
        budget=SearchBudget(tavily=10, exa=10),
        include_macro=False,
    )
    assert result["duplicates_removed"] >= 1
    assert any("reuters.com" in str(row.get("url")) for row in result["documents"])
    assert result["evidence_bodies"]
    assert all("tavily.com" not in str(row.get("source_url") or "") for row in result["evidence_bodies"])
    assert result["report"]["tier2_count"] >= 1
    assert result["report"]["tavily_vs_exa"]["tavily"]["hit_count"] >= 1


def test_report_counts_tiers() -> None:
    docs = [
        _doc(url="https://www.sec.gov/a", query_type="company_official", clean_text="sec " * 200, raw_text="sec " * 200),
        _doc(url="https://www.bloomberg.com/a", query_type="company_news"),
        _doc(url="https://www.nasdaq.com/a", query_type="industry_news"),
        _doc(url="https://www.fool.com/a", query_type="company_news"),
        _doc(url="https://www.lightreading.com/a", query_type="customer", extra={"relation": "customer"}),
    ]
    report = build_report(
        docs,
        days=30,
        duplicates_removed=2,
        raw_count=7,
        plan={"related_entities": [{"name": "Google", "relation": "customer"}], "coverage_gaps": []},
        allocated=[{"query": "Google TPU capex", "query_type": "claim", "providers": ["exa"], "claim_title": "custom silicon"}],
        query_results=[{"query": "Google TPU capex", "provider": "exa", "hit_count": 3}],
        providers={},
        warnings=[],
        overview=None,
        evidence_count=1,
    )
    assert report["tier1_count"] == 1
    assert report["tier2_count"] == 1
    assert report["tier3_count"] == 2
    assert report["tier4_count"] == 1
    assert report["duplicates_removed"] == 2
    assert report["claim_queries"]


def test_community_and_personal_are_tier5() -> None:
    assert source_tier("https://www.linkedin.com/pulse/apple-ai") == 5
    assert source_tier("https://someone.substack.com/p/notes") == 5
    assert source_tier("https://medium.com/@user/post") == 5
    assert source_tier("https://unknown-blog.example/aapl") == 4
    assert source_tier("https://www.stocktitan.net/sec-filings/FN/10-k.html") == 4


def test_newsroom_and_ir_paths_are_tier1() -> None:
    assert source_tier("https://www.apple.com/newsroom/2026/09/iphone/") == 1
    assert source_tier("https://investors.broadcom.com/news-releases") == 1
    assert source_tier("https://ir.lumentum.com/financials") == 1
    assert source_tier("https://www.sec.gov/Archives/edgar/aapl") == 1


def test_jsonld_date_recovery_does_not_guess() -> None:
    from stock_pm.external.dates import recover_published_at

    html = """
    <html><head>
    <script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-12T08:00:00Z"}</script>
    <meta property="article:published_time" content="2026-09-12T08:00:00Z">
    </head><body>posted 2 days ago</body></html>
    """
    assert recover_published_at(html) == "2026-09-12"
    assert recover_published_at("Updated 3 days ago. Yesterday the company said...") is None
    og = '<meta property="article:published_time" content="2026-08-01T00:00:00Z">'
    assert recover_published_at(og) == "2026-08-01"


def test_select_caps_reasoning_docs_and_skips_tier4_when_primary_enough() -> None:
    from stock_pm.external.select import docs_for_extraction, select_reasoning_documents

    docs = []
    for i in range(8):
        docs.append(_doc(url=f"https://www.sec.gov/a{i}", query_type="company_official", clean_text="sec " * 200, raw_text="sec " * 200))
    for i in range(8):
        docs.append(_doc(url=f"https://www.reuters.com/n{i}", query_type="company_news", clean_text="news " * 200, raw_text="news " * 200))
    for i in range(8):
        docs.append(_doc(url=f"https://www.lightreading.com/o{i}", query_type="industry_news", clean_text="opt " * 200, raw_text="opt " * 200))
    for i in range(40):
        docs.append(_doc(url=f"https://finance.yahoo.com/y{i}", query_type="company_news", clean_text="agg " * 200, raw_text="agg " * 200))
    for i in range(10):
        docs.append(_doc(url=f"https://www.linkedin.com/pulse/{i}", query_type="company_news", published_at=None, clean_text="li " * 200, raw_text="li " * 200))
    retained, archived, stats = select_reasoning_documents(docs)
    assert 20 <= stats["retained_for_reasoning"] <= 40
    assert stats["discovered_docs"] == len(docs)
    assert stats["tier45_filtered_count"] >= 40
    assert len(archived) == stats["archived_docs"]
    extractable = docs_for_extraction(retained)
    assert all(int(row.get("source_tier") or 9) <= 3 for row in extractable)


def test_fallback_plan_uses_business_model_relationships() -> None:
    aapl = fallback_plan("AAPL", {"company_profile": {"legal_name": "Apple Inc"}}, {"ticker": "AAPL"}, [])
    assert "product" in aapl["important_relationship_types"]
    assert "developer ecosystem" in aapl["important_relationship_types"]
    assert not any(row.get("query_type") == "customer" for row in aapl["queries"])
    avgo = fallback_plan("AVGO", {"company_profile": {"legal_name": "Broadcom Inc"}}, {"ticker": "AVGO"}, [])
    assert "hyperscaler/customer" in avgo["important_relationship_types"]
    assert any(row.get("entity") == "Google" for row in avgo["queries"])


def test_official_pack_docs_convert() -> None:
    rows = official_documents_from_pack(
        {
            "official_documents": [
                {
                    "title": "FY26 Q3 10-Q",
                    "url": "https://www.sec.gov/Archives/edgar/aapl",
                    "published_at": "2026-08-01",
                    "text": "iPhone revenue was $46.0 billion. " * 15,
                    "source": "sec.gov",
                }
            ]
        },
        "AAPL",
    )
    assert rows[0]["is_primary_source"] is True
    assert rows[0]["source_tier"] == 1
