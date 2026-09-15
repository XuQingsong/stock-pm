from stock_pm.research.agents.fundamental import FundamentalAgent
from stock_pm.research.agents.search_data import SearchDataAgent
from stock_pm.research.schema import validate_agent_output
from stock_pm.research.types import AgentInput, AgentOutput


def test_schema_drops_evidence_without_source_and_conclusions() -> None:
    output = validate_agent_output(
        AgentOutput(
            findings=["buy this name", "revenue grew"],
            new_evidence=[
                {"evidence_type": "news", "fact": "x", "source": "", "source_time": "2026-01-01"},
                {
                    "evidence_type": "filing",
                    "fact": "Revenue was 10",
                    "source": "10-Q",
                    "source_time": "2026-01-01T00:00:00+00:00",
                },
                {
                    "evidence_type": "note",
                    "fact": "stock is undervalued",
                    "source": "blog",
                    "source_time": "2026-01-01T00:00:00+00:00",
                },
            ],
            new_assumptions=[{"statement": "buy now", "category": "other"}],
            follow_up_tasks=[{"title": "check demand"}],
            confidence=1.4,
            agent_name="search_data",
        ),
        agent_name="search_data",
    )
    assert output.findings == ["revenue grew"]
    assert len(output.new_evidence) == 1
    assert output.new_evidence[0]["fact"] == "Revenue was 10"
    assert output.new_evidence[0]["excerpt"]
    assert output.new_assumptions == []
    assert output.confidence == 1.0


def test_search_agent_does_not_write_assumptions(monkeypatch) -> None:
    del monkeypatch
    agent = SearchDataAgent(completer=None)
    output = agent.run(
        AgentInput(
            ticker="ZZZZ",
            task={"task_type": "fetch_missing", "required_data": ["transcripts"], "depth": 1},
            research_pack={"missing_fields": ["transcripts"], "company_profile": {}, "major_events": []},
        )
    )
    assert output.agent_name == "search_data"
    assert output.new_assumptions == []
    assert "transcripts" in output.missing_data


def test_fundamental_agent_emits_schema_valid_output() -> None:
    agent = FundamentalAgent(completer=None)
    output = agent.run(
        AgentInput(
            ticker="TEST",
            task={"task_type": "discover_fundamentals"},
            research_pack={
                "template_id": "generic_company",
                "company_profile": {},
                "earnings_history": [],
                "guidance_history": [],
                "missing_fields": ["earnings_history"],
            },
        )
    )
    assert output.confidence is not None
    assert 0 <= output.confidence <= 1
    assert "earnings_history" in output.missing_data
