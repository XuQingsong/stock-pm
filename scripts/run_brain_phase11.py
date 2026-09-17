from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stock_pm.brain.header import company_header
from stock_pm.brain.integrity import assess_financial_integrity
from stock_pm.brain.llm_steps import company_understanding
from stock_pm.brain.news import classify_news_hits, search_recent_news
from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.backfill import ResearchDataBackfill
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore

OUT = Path("artifacts/brain_phase1")
TICKERS = ("AAPL", "AVGO", "LITE")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)
    return path


def _slim(result: dict) -> dict:
    return {
        "ticker": (result.get("header") or {}).get("ticker"),
        "run_id": (result.get("run") or {}).get("run_id"),
        "snapshot_id": result.get("snapshot_id"),
        "status": (result.get("run") or {}).get("status"),
        "header": result.get("header"),
        "integrity": result.get("integrity"),
        "quality": result.get("quality"),
        "company_understanding": result.get("company_understanding"),
        "pm_synthesis": result.get("pm_synthesis"),
        "candidates": result.get("candidates"),
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


def _integrity_for(research: ResearchService, ticker: str) -> dict:
    pack = research.get_pack(ticker) or research.build_pack(ticker) or {}
    header = company_header(pack, issuer=research.get_issuer(ticker))
    integrity = assess_financial_integrity(pack, header)
    guidance = (header.get("forward") or {}).get("management_guidance") or {}
    return {
        "ticker": ticker,
        "period_end": integrity.get("period_end"),
        "fiscal_year": integrity.get("fiscal_year"),
        "fiscal_period": integrity.get("fiscal_period"),
        "block_core_claims": integrity.get("block_core_claims"),
        "data_poor": integrity.get("data_poor"),
        "reason": integrity.get("reason"),
        "warnings": integrity.get("warnings"),
        "management_guidance": {
            "value": guidance.get("text"),
            "source": guidance.get("source"),
            "source_date": None,
            "cross_checked": False,
            "status": "ok" if guidance.get("origin") == "reported" else "unavailable",
            "reason": "operating guidance only; risk-factor language is excluded",
        },
        "fields": integrity.get("fields") or {},
        "header_latest_quarter": header.get("latest_quarter"),
        "header_growth": header.get("growth"),
        "header_price": header.get("price"),
        "header_valuation": header.get("valuation"),
        "missing_fields": pack.get("missing_fields") or [],
    }


def main() -> None:
    settings = Settings()
    db = Database(settings)
    research = ResearchService(ResearchStore(db), completer=SettingsCompleter(settings))
    store = BrainStore(db)
    OUT.mkdir(parents=True, exist_ok=True)

    backfills = {}
    for ticker in TICKERS:
        print("backfill", ticker, flush=True)
        try:
            backfills[ticker] = ResearchDataBackfill(research, settings).run(ticker)
        except Exception as exc:
            backfills[ticker] = {"status": "failed", "error": str(exc)[:400]}
            print("backfill failed", ticker, exc, flush=True)
        try:
            research.build_pack(ticker)
        except Exception as exc:
            print("pack rebuild failed", ticker, exc, flush=True)

    report = {
        "generated_at": _now(),
        "tickers": {ticker: _integrity_for(research, ticker) for ticker in TICKERS},
        "backfills": {
            ticker: {
                "id": (row or {}).get("id") if isinstance(row, dict) else None,
                "status": (row or {}).get("status") if isinstance(row, dict) else None,
                "error": (row or {}).get("error") if isinstance(row, dict) else None,
            }
            for ticker, row in backfills.items()
        },
    }
    _write("input_integrity_report.json", report)

    completer = SettingsCompleter(settings)
    aapl_pack = research.get_pack("AAPL") or {}
    smoke_user = {
        "ticker": "AAPL",
        "reported_financials": company_header(aapl_pack, issuer=research.get_issuer("AAPL")),
        "research_pack": {"company_profile": aapl_pack.get("company_profile"), "earnings_history": (aapl_pack.get("earnings_history") or [])[:4]},
        "evidence": [],
        "rules": ["Do not invent numbers.", "Cite evidence_id only.", "Mark unavailable when missing."],
    }
    print("llm smoke AAPL company_understanding", "key_present=", bool(settings.llm_api_key), "model=", settings.llm_model, "base=", settings.llm_base_url, flush=True)
    smoke_payload, smoke_audit = company_understanding(completer, smoke_user, allowed_ids=set())
    smoke = {
        "llm_called": bool(smoke_audit.get("llm_called")),
        "model": smoke_audit.get("model") or settings.llm_model,
        "status": smoke_audit.get("llm_status") or smoke_audit.get("status"),
        "latency": smoke_audit.get("latency_ms"),
        "tokens": {
            "input": smoke_audit.get("input_tokens"),
            "output": smoke_audit.get("output_tokens"),
            "total": smoke_audit.get("total_tokens"),
        },
        "error": smoke_audit.get("error"),
        "base_url": settings.llm_base_url,
        "payload_present": isinstance(smoke_payload, dict),
        "stopped_live_validation": not (smoke_audit.get("llm_called") and smoke_audit.get("llm_status") == "ok"),
    }
    _write("llm_smoke_aapl.json", smoke)
    if smoke["stopped_live_validation"]:
        print("LLM smoke failed; stopping Brain live validation", smoke.get("error"), flush=True)
        _write(
            "phase11_delivery.json",
            {
                "phase": "1.1",
                "llm_live": False,
                "reason": smoke.get("error") or "LLM smoke test did not return ok",
                "input_integrity_report": "artifacts/brain_phase1/input_integrity_report.json",
            },
        )
        return

    results = {}
    for ticker in TICKERS:
        print("brain live", ticker, flush=True)
        result = run_brain(research, ticker, store=store, fetch_live=True)
        slim = _slim(result)
        results[ticker] = slim
        _write(f"{ticker.lower()}_brain.json", slim)
        if ticker == "AAPL":
            aapl_ok = any(
                row.get("llm_called") and row.get("llm_status") == "ok"
                for row in ((slim.get("audit") or {}).get("llm_calls") or [])
            )
            if not aapl_ok:
                print("AAPL live LLM failed; stopping remaining Brain runs", flush=True)
                break

    news_coverage = {}
    for ticker in TICKERS:
        pack = research.get_pack(ticker) or {}
        hits = search_recent_news(ticker, pack=pack, days=7)
        news_coverage[ticker] = classify_news_hits(hits, days=7)
        news_coverage[ticker]["sample"] = [
            {"title": row.get("title"), "url": row.get("url"), "published_at": row.get("published_at"), "source": row.get("source")}
            for row in hits[:8]
        ]
    _write("news_coverage_7d.json", news_coverage)

    delivery = {
        "phase": "1.1",
        "generated_at": _now(),
        "llm_live": True,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "smoke": smoke,
        "input_integrity_report": report,
        "news_coverage_7d": news_coverage,
        "brains": {ticker: results.get(ticker) for ticker in TICKERS},
    }
    _write("phase11_delivery.json", delivery)


if __name__ == "__main__":
    os.environ.setdefault("RESEARCH_BACKFILL_TIMEOUT_SECONDS", "300")
    main()
