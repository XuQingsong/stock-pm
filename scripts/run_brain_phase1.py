from __future__ import annotations

import json
from pathlib import Path

from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.database import Database
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore


def main() -> None:
    db = Database()
    research = ResearchService(ResearchStore(db), completer=SettingsCompleter())
    store = BrainStore(db)
    out_dir = Path("artifacts/brain_phase1")
    out_dir.mkdir(parents=True, exist_ok=True)
    for ticker in ("AVGO", "AAPL", "LITE"):
        print("running", ticker, flush=True)
        result = run_brain(research, ticker, store=store, fetch_live=True)
        slim = {
            "ticker": ticker,
            "run_id": (result.get("run") or {}).get("run_id"),
            "snapshot_id": result.get("snapshot_id"),
            "status": (result.get("run") or {}).get("status"),
            "header": result.get("header"),
            "quality": result.get("quality"),
            "company_understanding": result.get("company_understanding"),
            "pm_synthesis": result.get("pm_synthesis"),
            "core_claims": [
                {
                    "claim_id": row.get("claim_id"),
                    "title": row.get("title"),
                    "statement": row.get("statement"),
                    "status": row.get("status"),
                    "confidence": row.get("confidence"),
                    "why_it_matters": row.get("why_it_matters"),
                    "reasoning": row.get("reasoning"),
                }
                for row in (result.get("claims") or [])
            ],
            "news": result.get("news"),
            "states": result.get("states"),
            "questions": result.get("questions"),
            "audit": result.get("audit"),
        }
        path = out_dir / f"{ticker.lower()}_brain.json"
        path.write_text(json.dumps(slim, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("wrote", path, "status", slim["status"], "claims", len(slim["core_claims"]), "news", len(slim["news"] or []), flush=True)


if __name__ == "__main__":
    main()
