from datetime import datetime, timezone

import pytest

from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore
from stock_pm.research.types import ACTOR_PM


STAMP = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)


def postgres_service() -> ResearchService:
    db = Database()
    if not db.ping():
        db.close()
        pytest.skip("PostgreSQL is not reachable")
    db.initialize()
    return ResearchService(ResearchStore(db))


def test_postgres_research_roundtrip_and_issuer_seed() -> None:
    svc = postgres_service()
    try:
        seeded = svc.get_issuer("AAPL")
        if seeded:
            assert seeded.get("cik") == "0000320193"
        created = svc.ensure_issuer("COHR", legal_name="Coherent Corp", sector="半导体", source="test")
        assert created["ticker"] == "COHR"
        evidence = svc.create_evidence(
            "COHR",
            {
                "evidence_type": "filing",
                "fact": "company reported a quarter",
                "source": "8-K",
                "source_url": "https://example.com/8k",
                "source_time": STAMP,
                "retrieved_at": STAMP,
            },
        )
        assumption = svc.create_assumption("COHR", {"statement": "the print is clean"})
        svc.link_assumption_evidence(
            "COHR",
            assumption_id=assumption["id"],
            evidence_id=evidence["id"],
            direction="support",
        )
        svc.update_assumption_status("COHR", assumption["id"], actor=ACTOR_PM, status="unchanged", thesis_role="core")
        thesis = svc.create_thesis("COHR", {"core_thesis": "observe execution", "key_assumption_ids": [assumption["id"]]}, actor=ACTOR_PM)
        assert thesis["version"] >= 1
        runs = svc.store.list_agent_runs("COHR")
        assert runs
    finally:
        svc.store.database.close()
