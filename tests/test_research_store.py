from datetime import datetime, timezone

import pytest

from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore
from stock_pm.research.types import ACTOR_PM


STAMP = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
# Isolated from golden-case tickers (AVGO / COHR / XOM).
TEST_TICKER = "ZZZT"


def postgres_service() -> ResearchService:
    db = Database()
    if not db.ping():
        db.close()
        pytest.skip("PostgreSQL is not reachable")
    db.initialize()
    return ResearchService(ResearchStore(db))


def _purge_ticker(store: ResearchStore, ticker: str) -> None:
    params = {"ticker": ticker}
    store._execute("DELETE FROM research_pm_rulings WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM research_valuations WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM investment_theses WHERE ticker = %(ticker)s", params)
    store._execute(
        "DELETE FROM assumption_evidence_links WHERE assumption_id IN (SELECT id FROM research_assumptions WHERE ticker = %(ticker)s)",
        params,
    )
    store._execute("DELETE FROM research_assumptions WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM research_evidence WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM research_tasks WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM research_agent_runs WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM research_packs WHERE ticker = %(ticker)s", params)
    store._execute("DELETE FROM issuer_profiles WHERE ticker = %(ticker)s", params)


def test_postgres_research_roundtrip_and_issuer_seed() -> None:
    svc = postgres_service()
    try:
        seeded = svc.get_issuer("AAPL")
        if seeded:
            assert seeded.get("cik") == "0000320193"
        created = svc.ensure_issuer(TEST_TICKER, legal_name="Roundtrip Fixture Corp", sector="半导体", source="test")
        assert created["ticker"] == TEST_TICKER
        evidence = svc.create_evidence(
            TEST_TICKER,
            {
                "evidence_type": "filing",
                "fact": "company reported a quarter",
                "source": "8-K",
                "source_url": "https://example.com/8k",
                "source_time": STAMP,
                "retrieved_at": STAMP,
            },
        )
        assumption = svc.create_assumption(TEST_TICKER, {"statement": "the print is clean"})
        link = svc.link_assumption_evidence(
            TEST_TICKER,
            assumption_id=assumption["id"],
            evidence_id=evidence["id"],
            direction="contextual",
            strength="strong",
            reason="sets the print in context",
        )
        assert link["direction"] == "contextual"
        assert link["strength"] == "strong"
        assert link["reason"] == "sets the print in context"
        svc.update_assumption_status(TEST_TICKER, assumption["id"], actor=ACTOR_PM, status="unchanged", thesis_role="core")
        thesis = svc.create_thesis(TEST_TICKER, {"core_thesis": "observe execution", "key_assumption_ids": [assumption["id"]]}, actor=ACTOR_PM)
        assert thesis["version"] == 1
        valuation = svc.create_valuation(
            TEST_TICKER,
            {"bear_case": {}, "base_case": {"target_value": 80}, "bull_case": {}},
            actor=ACTOR_PM,
        )
        assert valuation["base_case"]["target_value"] == 80
        tables = svc.store._execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('valuations', 'research_valuations')
            ORDER BY table_name
            """
        )
        assert [row["table_name"] for row in tables] == ["research_valuations"]
        columns = svc.store._execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'assumption_evidence_links'
              AND column_name IN ('strength', 'reason', 'direction', 'relevance')
            ORDER BY column_name
            """
        )
        assert {row["column_name"] for row in columns} == {"direction", "reason", "relevance", "strength"}
        again = svc.ensure_issuer(TEST_TICKER)
        assert again["legal_name"] == "Roundtrip Fixture Corp"
        assert again["sector"] == "半导体"
        runs = svc.store.list_agent_runs(TEST_TICKER)
        assert runs
    finally:
        try:
            _purge_ticker(svc.store, TEST_TICKER)
        except Exception:
            pass
        svc.store.database.close()
