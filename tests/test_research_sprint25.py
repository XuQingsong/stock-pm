from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from stock_pm.research.agents.fundamental import FundamentalAgent
from stock_pm.research.backfill import ResearchDataBackfill, pack_needs_research_data
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.pack_builder import PackBuilder
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import StorePackSource
from stock_pm.research.types import AgentInput
from stock_pm.research.workflow import run_new_ticker_research


def _stamp(days: int = 0) -> str:
    return (datetime(2026, 3, 12, tzinfo=timezone.utc) - timedelta(days=days)).isoformat()


class FakeFetchers:
    def __init__(self, *, fail_transcripts: bool = False, timeout: bool = False) -> None:
        self.fail_transcripts = fail_transcripts
        self.calls: list[str] = []

    def issuer_profile(self, symbol: str) -> dict:
        self.calls.append(f"profile:{symbol}")
        return {"source": "fmp.profile", "profile": {"companyName": f"{symbol} Corp", "cik": "0000000001"}}

    def sec_identity(self, symbol: str) -> dict:
        self.calls.append(f"sec:{symbol}")
        return {"source": "sec.company_tickers", "cik": "0001730168", "legal_name": f"{symbol} Inc", "fiscal_year_end_month": 10}

    def earnings_bundle(self, symbol: str) -> dict:
        self.calls.append(f"earnings:{symbol}")
        earnings = []
        for idx in range(6):
            day = date(2025, 12, 11) - timedelta(days=90 * idx)
            earnings.append(
                {
                    "symbol": symbol,
                    "report_date": day.isoformat(),
                    "report_timing": "after_market",
                    "fiscal_period": f"{2025 - idx // 4}Q{(4 - idx % 4)}",
                    "fiscal_year": 2025 - idx // 4,
                    "period_end": (day - timedelta(days=20)).isoformat(),
                    "currency": "USD",
                    "eps_actual": 1.2 + idx * 0.1,
                    "eps_estimate": 1.1,
                    "eps_surprise_pct": 9.0,
                    "revenue_actual": 10_000_000_000 + idx * 1000,
                    "revenue_estimate": 9_800_000_000,
                    "revenue_surprise_pct": 2.0,
                    "net_income_actual": 3_000_000_000,
                    "source": "fmp",
                    "provider_fields": {"fcf": 2_000_000_000},
                }
            )
        return {
            "source": "fmp",
            "earnings": earnings,
            "fundamentals": {
                "symbol": symbol,
                "captured_at": _stamp(),
                "revenue_ttm": 40_000_000_000,
                "eps_ttm": 4.5,
                "gross_margin_pct": 55.0,
                "operating_margin_pct": 30.0,
                "net_margin_pct": 22.0,
                "revenue_growth_yoy_pct": 18.0,
                "source": "fmp",
            },
            "news": [
                {
                    "symbol": symbol,
                    "headline": f"{symbol} announced a capacity expansion",
                    "summary": "Company discussed demand and capex.",
                    "source": "nasdaq",
                    "published_at": _stamp(10),
                    "url": f"https://example.com/{symbol.lower()}-news",
                }
            ],
            "income": [],
            "cashflow": [],
            "segments": None,
            "error": None,
        }

    def press_releases(self, symbol: str) -> list[dict]:
        self.calls.append(f"press:{symbol}")
        return [
            {
                "title": f"{symbol} Reports Quarterly Results and Raises Outlook",
                "url": f"https://example.com/{symbol.lower()}-pr",
                "published_at": _stamp(5),
                "text": "Management raised full-year revenue guidance and restated a multi-year capacity target.",
                "source_provider": "fmp",
            }
        ]

    def filings(self, symbol: str, *, cik: str | None = None) -> dict:
        self.calls.append(f"filings:{symbol}")
        return {
            "source": "sec.submissions",
            "filings": [
                {
                    "form": "10-K",
                    "filing_date": "2025-12-20",
                    "url": f"https://www.sec.gov/{symbol.lower()}-10k",
                    "title": "10-K",
                    "source_provider": "sec",
                },
                {
                    "form": "10-Q",
                    "filing_date": "2026-03-01",
                    "url": f"https://www.sec.gov/{symbol.lower()}-10q",
                    "title": "10-Q",
                    "source_provider": "sec",
                },
            ],
            "error": None,
        }

    def official_documents(self, symbol: str, filings: list[dict] | None = None) -> list[dict]:
        self.calls.append(f"official:{symbol}")
        del filings
        text = (
            "The company expects next quarter revenue of $12.0 billion to $12.2 billion. "
            "We expect AI semiconductor revenue of approximately $4.0 billion in the next quarter. "
            "Adjusted EBITDA margin is expected to be approximately 64 percent. "
            "Over the next two years customer deployments are expected to increase substantially. "
            "We remain committed to this revenue and capacity plan."
        )
        if symbol.upper() == "XOM":
            text = (
                "The company expects next quarter production of 3.8 million oil-equivalent barrels per day. "
                "Adjusted operating margin is expected to remain in the guided range. "
                "Over the next two years we remain committed to the long-term production and capex plan."
            )
        return [
            {
                "form": "EX-99.1",
                "title": "Exhibit 99.1",
                "url": f"https://www.sec.gov/{symbol.lower()}-ex991",
                "published_at": _stamp(3),
                "text": text,
                "doc_type": "earnings_release",
                "source_provider": "sec.exhibit",
            }
        ]

    def web_search(self, query: str) -> list[dict]:
        self.calls.append(f"search:{query}")
        return []

    def fetch_url(self, url: str) -> dict:
        self.calls.append(f"fetch:{url}")
        return {"url": url, "html": "", "text": "", "error": "not_used_in_unit_test"}

    def transcripts(self, symbol: str, quarters: list[str]) -> dict:
        self.calls.append(f"transcripts:{symbol}")
        if self.fail_transcripts:
            raise RuntimeError("transcript provider down")
        text = (
            "Over the next three years our long-term target is to expand capacity "
            "to support customer demand in data center and custom silicon. "
            "We remain committed to this revenue and capacity plan. "
            "Full-year revenue guidance was raised."
        )
        if symbol.upper() == "XOM":
            text = (
                "Our multi-year production and capex plan targets increased oil and gas output. "
                "We remain committed to the long-term production target and capital plan. "
                "Next quarter oil volume guidance is unchanged."
            )
        items = []
        for quarter in quarters[:5]:
            items.append(
                {
                    "quarter": quarter,
                    "fiscal_period": quarter,
                    "published_at": _stamp(20),
                    "source": "fmp",
                    "source_url": f"https://example.com/{symbol.lower()}-{quarter}",
                    "text": text,
                    "excerpts": [{"text": text[:180]}],
                    "title": f"Earnings call {quarter}",
                }
            )
        return {"transcripts": items, "source": "fmp", "error": None, "records_attempted": len(quarters)}

    def daily_bars(self, symbol: str, *, days: int = 430) -> dict:
        self.calls.append(f"bars:{symbol}")
        bars = []
        start = date(2024, 1, 2)
        price = 80.0 if symbol in {"SPY", "QQQ"} else 100.0
        for idx in range(800):
            day = start + timedelta(days=idx)
            if day.weekday() >= 5:
                continue
            price *= 1.0008
            bars.append(
                {
                    "bar_time": datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat(),
                    "close_price": round(price, 2),
                    "session_date": day.isoformat(),
                }
            )
        return {"bars": list(reversed(bars)), "source": "alpaca", "error": None, "record": {"status": "ok"}}


def test_backfill_steps_are_independent_when_transcripts_fail() -> None:
    svc = ResearchService(InMemoryResearchStore())
    fetchers = FakeFetchers(fail_transcripts=True)
    result = ResearchDataBackfill(svc, fetchers=fetchers, timeout_seconds=30, max_retries=0).run("ZZYX")
    steps = result["steps"]
    assert result["status"] in {"partial", "failed"}
    assert steps["earnings"]["status"] == "success"
    assert steps["earnings"]["records_found"] >= 4
    assert steps["transcripts"]["status"] == "failed"
    assert steps["filings"]["status"] == "success"
    assert steps["fundamentals"]["status"] == "success"


def test_backfill_status_shape_and_pack_rebuild() -> None:
    svc = ResearchService(InMemoryResearchStore())
    result = ResearchDataBackfill(svc, fetchers=FakeFetchers(), timeout_seconds=30, max_retries=0).run("AVGO")
    assert result["status"] in {"success", "partial"}
    for name in ("issuer", "earnings", "filings", "transcripts", "fundamentals", "prices", "major_events", "rebuild_pack"):
        step = result["steps"][name]
        assert set(step) >= {"status", "records_found", "source", "last_attempt_at", "error"}
    pack = svc.get_pack("AVGO")
    assert len(pack["earnings_history"]) >= 4
    assert pack["company_profile"]["transcripts"]
    assert pack["guidance_history"]
    assert "fundamentals_snapshot" not in pack.get("missing_fields", [])
    assert pack["company_profile"].get("revenue_ttm")


def test_same_backfill_path_for_three_tickers() -> None:
    svc = ResearchService(InMemoryResearchStore())
    runner = ResearchDataBackfill(svc, fetchers=FakeFetchers(), timeout_seconds=30, max_retries=0)
    for ticker in ("AVGO", "COHR", "XOM"):
        row = runner.run(ticker)
        assert row["steps"]["earnings"]["records_found"] >= 4
        assert row["steps"]["transcripts"]["records_found"] >= 1
        pack = svc.get_pack(ticker)
        result = run_new_ticker_research(svc, ticker, execute=True, backfill=False, max_depth=2, max_tasks=12)
        facts = " ".join(item["fact"].lower() for item in result["snapshot"]["evidence"])
        assert "long-term" in facts or "production" in facts or "capacity" in facts
        assert result["snapshot"]["assumptions"]
        assert any(int(task.get("depth") or 0) > 0 for task in result["snapshot"]["tasks"])
        assert pack["ticker"] == ticker


def test_fundamental_agent_skips_commitments_without_transcript() -> None:
    agent = FundamentalAgent(completer=None)
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "discover_fundamentals"},
            research_pack={
                "template_id": "generic_company",
                "company_profile": {},
                "earnings_history": [
                    {
                        "fiscal_period": "2025Q4",
                        "report_date": "2026-01-01",
                        "revenue": 10,
                        "eps": 1,
                        "source": "earnings_reports",
                    }
                ],
                "guidance_history": [],
                "major_events": [{"title": "CEO hinted at a huge secret target", "event_time": "2026-01-02", "source": "news"}],
                "missing_fields": ["transcripts"],
            },
        )
    )
    assert all(item.get("evidence_type") != "transcript" for item in output.new_evidence)
    assert all("secret target" not in str(item.get("fact") or "").lower() for item in output.new_evidence)
    assert "transcripts" in output.missing_data


def test_guidance_and_commitments_from_official_document_without_transcript() -> None:
    svc = ResearchService(InMemoryResearchStore())
    fetchers = FakeFetchers(fail_transcripts=True)
    result = ResearchDataBackfill(svc, fetchers=fetchers, timeout_seconds=30, max_retries=0).run("ZZYX")
    pack = svc.get_pack("ZZYX")
    assert result["steps"]["transcripts"]["status"] == "failed"
    assert pack["guidance_history"]
    assert pack["official_documents"]
    agent = FundamentalAgent(completer=None)
    output = agent.run(AgentInput(ticker="ZZYX", task={"task_type": "discover_fundamentals"}, research_pack=pack))
    facts = " ".join(item["fact"].lower() for item in output.new_evidence)
    assert "expect" in facts or "guidance" in facts
    assert any((item.get("raw_reference") or {}).get("kind") == "management_commitment" for item in output.new_evidence)
    assert any(item.source_type == "evidence_discovered" for item in output.follow_up_tasks)
    assert any(item.source_type == "template_seed" for item in output.follow_up_tasks)
    assert all(item.get("excerpt") for item in output.new_evidence if (item.get("raw_reference") or {}).get("kind"))
    assert any(row.get("source_type") == "evidence_discovered" for row in output.new_assumptions)


def test_search_agent_does_not_mint_headline_evidence() -> None:
    from stock_pm.research.agents.search_data import SearchDataAgent

    output = SearchDataAgent(completer=None).run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "fetch_missing", "depth": 1},
            research_pack={
                "missing_fields": [],
                "company_profile": {},
                "major_events": [
                    {
                        "title": "Company sees strong AI demand",
                        "event_time": "2026-01-01T00:00:00+00:00",
                        "source": "nasdaq",
                        "url": "https://example.com/headline",
                    }
                ],
            },
        )
    )
    assert output.new_evidence == []


def test_search_agent_uses_tools_instead_of_stopping() -> None:
    from stock_pm.research.agents.search_data import SearchDataAgent

    class Tools:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def official_documents(self, symbol: str, filings=None):
            self.calls.append(f"official:{symbol}")
            return [
                {
                    "text": "The company expects next quarter revenue of $1.0 billion to $1.1 billion.",
                    "url": "https://www.sec.gov/ex991",
                    "published_at": "2026-01-01T00:00:00+00:00",
                    "doc_type": "earnings_release",
                    "source_provider": "sec.exhibit",
                }
            ]

        def web_search(self, query: str):
            self.calls.append(f"search:{query}")
            return [{"title": "Earnings call", "url": "https://example.com/transcript", "snippet": "transcript"}]

        def fetch_url(self, url: str):
            self.calls.append(f"fetch:{url}")
            return {
                "url": url,
                "text": "Operator: Welcome. Over the next two years customer deployments are expected to increase substantially.",
                "error": None,
            }

    tools = Tools()
    output = SearchDataAgent(completer=None, tools=tools).run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "fetch_missing", "required_data": ["guidance_history", "transcripts"], "depth": 0},
            research_pack={
                "missing_fields": ["guidance_history", "transcripts"],
                "company_profile": {},
                "earnings_history": [{"report_date": "2026-01-01T00:00:00+00:00"}],
                "major_events": [],
            },
        )
    )
    assert any(item.startswith("official:") for item in tools.calls)
    assert any(item.startswith("search:") for item in tools.calls)
    assert output.new_evidence
    assert all(item.get("excerpt") and item.get("source_type") for item in output.new_evidence)
    assert all(item.get("evidence_type") != "news" for item in output.new_evidence)


def test_yahoo_and_stooq_parsers() -> None:
    from stock_pm.research.official import parse_stooq_csv, parse_yahoo_chart

    bars = parse_yahoo_chart(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200, 1704153600],
                        "indicators": {"quote": [{"close": [10.0, 11.0], "open": [9.5, 10.5], "high": [10.2, 11.2], "low": [9.4, 10.4], "volume": [1, 2]}]},
                    }
                ]
            }
        }
    )
    assert len(bars) == 2
    assert bars[0]["close_price"] == 11.0
    csv_bars = parse_stooq_csv("Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,100\n2024-01-03,10.5,12,10,11,110\n")
    assert csv_bars[0]["close_price"] == 11.0


def test_empty_pack_workflow_quality_is_not_success() -> None:
    svc = ResearchService(InMemoryResearchStore())
    result = run_new_ticker_research(svc, "ZZZZ", execute=True, max_depth=1, max_tasks=4)
    assert result["research_quality"] == "insufficient"
    assert result["workflow_run"]["status"] in {"partial", "failed"}


def test_execute_true_does_not_hit_live_http_without_database() -> None:
    svc = ResearchService(InMemoryResearchStore())
    result = run_new_ticker_research(svc, "ZZZZ", execute=True, max_depth=1, max_tasks=4)
    assert result.get("backfill") is None
    assert "earnings_history" in result["pack"]["missing_fields"]


def test_pack_needs_research_data_detects_empty() -> None:
    assert pack_needs_research_data({"missing_fields": ["transcripts"]})
    assert not pack_needs_research_data({"missing_fields": ["fcf"]})


def test_store_pack_source_reads_backfill_overlays() -> None:
    store = InMemoryResearchStore()
    store.raw_earnings["AAA"] = [{"report_date": "2026-01-01", "fiscal_period": "2025Q4", "revenue_actual": 1, "eps_actual": 1}]
    source = StorePackSource(store)
    assert source.earnings("AAA")
    pack = PackBuilder(source).build("AAA")
    assert pack["earnings_history"]
