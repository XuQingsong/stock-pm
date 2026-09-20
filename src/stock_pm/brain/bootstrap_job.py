"""Explicit production bootstrap of the persisted Brain from existing research.

This is a background command, never a page-read path. It reuses the existing
evidence-gated Brain pipeline and skips tickers with a complete baseline.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from .bootstrap import bootstrap_brain, brain_has_baseline
from .materialize_from_research import parse_tickers
from .store import BrainStore


def run_bootstrap_job(research: Any, store: BrainStore, tickers: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for ticker in parse_tickers(tickers):
        if brain_has_baseline(store, ticker):
            results.append({"ticker": ticker, "status": "already_ready"})
            continue
        try:
            pack = research.get_pack(ticker) if hasattr(research, "get_pack") else None
            if not pack or str(pack.get("status") or "").lower() == "missing":
                results.append({"ticker": ticker, "status": "missing_research_pack"})
                continue
            result = bootstrap_brain(research, ticker, store=store, fetch_live=False)
            results.append({
                "ticker": ticker,
                "status": "ready" if result.get("brain_initialized") else "incomplete",
                "lifecycle": result.get("lifecycle"),
                "inventory": result.get("inventory"),
                "token_usage": result.get("token_usage"),
            })
        except Exception as exc:
            results.append({"ticker": ticker, "status": "failed", "error": str(exc)})
    return {"results": results, "ok": all(row["status"] in {"ready", "already_ready"} for row in results)}


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Bootstrap persisted Brain baselines from existing research packs.")
    parser.add_argument("--tickers", default="AVGO,LITE,AAPL", help="Comma-separated tickers")
    args = parser.parse_args(argv)
    from stock_pm.database import Database
    from stock_pm.research.agents.base import SettingsCompleter
    from stock_pm.research.service import ResearchService
    from stock_pm.research.store import ResearchStore

    database = Database()
    try:
        database.initialize()
        result = run_bootstrap_job(
            ResearchService(ResearchStore(database), completer=SettingsCompleter()),
            BrainStore(database),
            parse_tickers(args.tickers),
        )
    finally:
        database.close()
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(0 if main().get("ok") else 1)
