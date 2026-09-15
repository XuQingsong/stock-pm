from datetime import datetime, timezone

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.research import api as research_api
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService


STAMP = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc).isoformat()


def _client(monkeypatch) -> tuple[TestClient, ResearchService]:
    svc = ResearchService(InMemoryResearchStore())
    monkeypatch.setattr(research_api, "_service_override", svc)
    return TestClient(api.app), svc


def test_research_api_happy_path_and_pm_gate(monkeypatch) -> None:
    client, _svc = _client(monkeypatch)
    issuer = client.put("/api/research/ZZZZ/issuer", json={"legal_name": "Test Co", "sector": "半导体"})
    assert issuer.status_code == 200
    assert issuer.json()["cik"] is None
    run = client.post("/api/research/ZZZZ/workflow/runs", json={"max_depth": 3})
    assert run.status_code == 201
    task = client.post(
        "/api/research/ZZZZ/tasks",
        json={"task_type": "discover_fundamentals", "title": "read filings", "workflow_run_id": run.json()["id"]},
    )
    assert task.status_code == 201
    evidence = client.post(
        "/api/research/ZZZZ/evidence",
        json={
            "evidence_type": "filing",
            "fact": "management described a long-term capacity plan",
            "source": "10-K",
            "source_time": STAMP,
            "retrieved_at": STAMP,
        },
    )
    assert evidence.status_code == 201
    assumption = client.post("/api/research/ZZZZ/assumptions", json={"statement": "capacity plan is credible"})
    assert assumption.json()["status"] == "unverified"
    forbidden = client.post(
        "/api/research/ZZZZ/thesis",
        json={"actor": "fundamental", "core_thesis": "should not write"},
    )
    assert forbidden.status_code == 403
    link = client.post(
        f"/api/research/ZZZZ/assumptions/{assumption.json()['id']}/links",
        json={"evidence_id": evidence.json()["id"], "direction": "support"},
    )
    assert link.status_code == 201
    status = client.post(
        f"/api/research/ZZZZ/assumptions/{assumption.json()['id']}/status",
        json={"actor": "pm_judge", "status": "strengthened", "thesis_role": "core"},
    )
    assert status.json()["thesis_role"] == "core"
    thesis = client.post(
        "/api/research/ZZZZ/thesis",
        json={
            "actor": "pm_judge",
            "core_thesis": "own the capacity cycle",
            "key_assumption_ids": [assumption.json()["id"]],
        },
    )
    assert thesis.status_code == 201
    again = client.post("/api/research/ZZZZ/thesis", json={"actor": "pm_judge", "core_thesis": "updated risks"})
    assert again.json()["version"] == 2
    history = client.get("/api/research/ZZZZ/thesis/history")
    assert len(history.json()) == 2
    missing = client.get("/api/research/YYYY/thesis")
    assert missing.json()["status"] == "missing"
    audits = client.get(f"/api/research/ZZZZ/workflow/runs/{run.json()['id']}/agent-runs")
    assert audits.status_code == 200
