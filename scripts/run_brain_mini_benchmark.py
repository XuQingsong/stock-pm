#!/usr/bin/env python3
"""Brain Mini Benchmark. Frozen AVGO Round 1 by default. Does not replace production LLM."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from stock_pm.brain.benchmark.mini import run_round1, run_round2
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Brain Mini Benchmark")
    parser.add_argument("--round", dest="round_id", type=int, default=1, choices=(1, 2))
    parser.add_argument("--models", default="glm53,kimik3", help="Round 2 file labels, default glm53,kimik3")
    parser.add_argument("--only", default="", help="Round 1: rerun a single file_label, keep other JSON")
    args = parser.parse_args()
    os.environ.setdefault("RESEARCH_BACKFILL_TIMEOUT_SECONDS", "60")
    settings = Settings()
    db = None
    store = BrainStore()
    research = None
    try:
        db = Database(settings)
        if db.ping():
            store = BrainStore(db)
            research = ResearchService(ResearchStore(db))
    except Exception as exc:
        print("database unavailable, using artifact freeze:", exc, flush=True)
    out = Path("artifacts/brain_mini_benchmark")
    if args.round_id == 1:
        run_round1(store=store, research=research, settings=settings, out_dir=out, only=(args.only.strip() or None))
    else:
        names = [item.strip() for item in args.models.split(",") if item.strip()]
        run_round2(
            models=names,
            store=store,
            research=research,
            settings=settings,
            out_dir=Path("artifacts/brain_mini_benchmark_round2"),
        )
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    print("done", flush=True)


if __name__ == "__main__":
    main()
