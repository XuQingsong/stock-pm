from __future__ import annotations

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.brain import api as brain_api


def test_brain_run_requires_token_before_expensive_work(monkeypatch) -> None:
    monkeypatch.setenv("BRAIN_RUN_TOKEN", "test-run-token")
    calls = []
    monkeypatch.setattr(brain_api, "get_brain_deps", lambda: (object(), object()))
    monkeypatch.setattr(brain_api, "run_brain", lambda *args, **kwargs: calls.append("run") or {"run": {}})
    monkeypatch.setattr(brain_api, "build_brain_view", lambda *args, **kwargs: {"status": "ok"})
    client = TestClient(api.app)

    assert client.post("/api/brain/AVGO/runs", json={}).status_code == 403
    assert client.post("/api/brain/AVGO/runs", json={}, headers={"X-Brain-Run-Token": "wrong"}).status_code == 403
    assert calls == []
    allowed = client.post("/api/brain/AVGO/runs", json={}, headers={"X-Brain-Run-Token": "test-run-token"})
    assert allowed.status_code == 201
    assert calls == ["run"]
