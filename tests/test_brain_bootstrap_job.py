"""The production bootstrap command must not repeatedly run a ready Brain."""

from stock_pm.brain.bootstrap_job import run_bootstrap_job
from stock_pm.brain.store import BrainStore

from test_brain_phase1 import _seed_evidence, _service


def test_bootstrap_job_skips_ready_and_reports_missing_pack(monkeypatch) -> None:
    svc = _service()
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    monkeypatch.setattr("stock_pm.brain.pipeline.search_recent_news", lambda *args, **kwargs: [])
    store = BrainStore()
    first = run_bootstrap_job(svc, store, ["ZZZT"])
    assert first["ok"] is True
    assert first["results"][0]["status"] == "ready"

    second = run_bootstrap_job(svc, store, ["ZZZT", "MISSING"])
    assert [row["status"] for row in second["results"]] == ["already_ready", "missing_research_pack"]
    assert second["ok"] is False
