#!/usr/bin/env python3
# Full Brain Capability Benchmark. Token-heavy. Mini Benchmark is the default.
# python3 scripts/run_brain_mini_benchmark.py
# This script requires --full to run the original 3-ticker x 4-step suite.
from __future__ import annotations

import os
import sys
from pathlib import Path

from stock_pm.brain.benchmark.runner import run_benchmark
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore


def main() -> None:
    if "--full" not in sys.argv:
        print(
            "Full Brain Capability Benchmark is gated to protect trial token quotas.\n"
            "Use: python3 scripts/run_brain_mini_benchmark.py\n"
            "Or pass --full to run the original suite.",
            flush=True,
        )
        raise SystemExit(2)
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
    run_benchmark(store=store, research=research, settings=settings, out_dir=Path("artifacts/brain_benchmark"))
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    print("done", flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
from pathlib import Path

from stock_pm.brain.benchmark.runner import run_benchmark
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore


def main() -> None:
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
    run_benchmark(store=store, research=research, settings=settings, out_dir=Path("artifacts/brain_benchmark"))
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    print("done", flush=True)


if __name__ == "__main__":
    main()
