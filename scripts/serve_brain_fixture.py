from __future__ import annotations

import json
from datetime import datetime, timezone

from stock_pm import api
from stock_pm.brain import api as brain_api
from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource
from tests.test_brain_phase1 import FakeBrainCompleter, _pack, _seed_evidence

STAMP = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc).isoformat()


def attach_fixture() -> None:
    source = DictPackSource.from_mapping("ZZZT", _pack())
    svc = ResearchService(InMemoryResearchStore(), pack_source=source, completer=FakeBrainCompleter())
    svc.store.upsert_pack(_pack())
    svc.ensure_issuer("ZZZT", legal_name="Test Co", sector="半导体")
    _seed_evidence(svc)
    store = BrainStore()
    original = __import__("stock_pm.brain.pipeline", fromlist=["search_recent_news"]).search_recent_news

    def fake_search(*args, **kwargs):
        return [
            {
                "title": "Demand update",
                "url": "https://www.reuters.com/test-demand",
                "snippet": "A high-quality source reported a demand update.",
                "source": "reuters.com",
                "published_at": STAMP,
                "query": "ZZZT demand",
            }
        ]

    import stock_pm.brain.pipeline as pipeline

    pipeline.search_recent_news = fake_search
    result = run_brain(svc, "ZZZT", store=store, completer=svc.completer, fetch_live=False)
    pipeline.search_recent_news = original
    brain_api._override = {"research": svc, "store": store}
    claim_id = result["claims"][0]["claim_id"]
    evidence_id = next(link["evidence_id"] for link in store.list_links(claim_id=claim_id) if link["direction"] == "support")
    Path = __import__("pathlib").Path
    Path("artifacts/brain_phase1/fixture_ids.json").write_text(
        json.dumps({"ticker": "ZZZT", "claim_id": claim_id, "evidence_id": evidence_id, "note": "TEST FIXTURE — not live LLM"}, indent=2),
        encoding="utf-8",
    )
    print("fixture claim", claim_id, "evidence", evidence_id, flush=True)


if __name__ == "__main__":
    attach_fixture()
    import uvicorn

    uvicorn.run(api.app, host="127.0.0.1", port=8003, log_level="warning")
