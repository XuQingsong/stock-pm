from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stock_pm.brain.pipeline import run_brain
from stock_pm.brain.store import BrainStore
from stock_pm.brain.types import EXA_SEARCH_BUDGET, NEWS_WINDOW_DAYS, TAVILY_SEARCH_BUDGET
from stock_pm.config import Settings
from stock_pm.database import Database
from stock_pm.external.clients import SearchBudget, exa_configured, tavily_configured
from stock_pm.external.layer import gather_external_intelligence, merge_intelligence
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.service import ResearchService
from stock_pm.research.store import ResearchStore

OUT = Path("artifacts/brain_phase12")
TICKERS = ("AAPL", "AVGO", "LITE")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path, flush=True)
    return path


def _key_status(settings: Settings) -> dict[str, bool]:
    return {
        "tavily": bool((settings.tavily_api_key or "").strip()),
        "exa": bool((settings.exa_api_key or "").strip()),
        "fred": bool((settings.fred_api_key or "").strip()),
        "alpha_vantage": bool((settings.alpha_vantage_api_key or "").strip()),
        "llm": bool((settings.llm_api_key or "").strip()),
        "benzinga": False,
    }


def _slim_doc(row: dict) -> dict:
    return {
        "provider": row.get("provider"),
        "source_type": row.get("source_type"),
        "source_family": row.get("source_family"),
        "source_tier": row.get("source_tier"),
        "title": row.get("title"),
        "url": row.get("url"),
        "source_domain": row.get("source_domain"),
        "published_at": row.get("published_at"),
        "is_dated": row.get("is_dated"),
        "is_full_text": row.get("is_full_text"),
        "query": row.get("query"),
        "query_type": row.get("query_type"),
        "text_chars": len(str(row.get("clean_text") or "")),
    }


def _provider_summary(providers: dict) -> dict:
    out = {}
    for name, row in (providers or {}).items():
        out[name] = {
            "status": row.get("status"),
            "hit_count": row.get("hit_count") or 0,
            "usable_count": row.get("usable_count") or 0,
            "high_quality_count": row.get("high_quality_count") or 0,
            "full_text_count": row.get("full_text_count") or 0,
            "dated_count": row.get("dated_count") or 0,
            "error": row.get("error"),
            "query_count": len(row.get("queries") or []),
        }
    return out


def main() -> None:
    settings = Settings()
    keys = _key_status(settings)
    print("keys_present", {name: present for name, present in keys.items()}, flush=True)
    db = Database(settings)
    research = ResearchService(ResearchStore(db), completer=SettingsCompleter(settings))
    store = BrainStore(db)
    completer = SettingsCompleter(settings)

    results = {}
    for ticker in TICKERS:
        print("external intelligence", ticker, flush=True)
        pack = research.get_pack(ticker) or research.build_pack(ticker) or {}
        header = {"ticker": ticker, "company_name": (pack.get("company_profile") or {}).get("legal_name")}
        latest = store.latest_run(ticker) if hasattr(store, "latest_run") else None
        claims = []
        if latest and latest.get("run_id"):
            claims = store.list_claims(ticker, run_id=latest.get("run_id"), core_only=True) or []
        if not claims:
            claims = store.list_claims(ticker, core_only=True) or []
        budget = SearchBudget(
            tavily=TAVILY_SEARCH_BUDGET if tavily_configured(settings) else 0,
            exa=EXA_SEARCH_BUDGET if exa_configured(settings) else 0,
        )
        base = gather_external_intelligence(
            ticker,
            pack=pack,
            header=header,
            claims=[],
            understanding=None,
            completer=completer,
            settings=settings,
            days=NEWS_WINDOW_DAYS,
            fetch_live=True,
            phase="base",
            budget=budget,
        )
        claim_pass = gather_external_intelligence(
            ticker,
            pack=pack,
            header=header,
            claims=claims,
            understanding=(latest or {}).get("company_understanding") if isinstance(latest, dict) else None,
            completer=completer,
            settings=settings,
            days=NEWS_WINDOW_DAYS,
            fetch_live=True,
            phase="claims",
            budget=budget,
            prior_urls={str(row.get("canonical_url") or row.get("url") or "") for row in (base.get("documents") or [])},
            include_macro=False,
            include_alphavantage=False,
        )
        intel = merge_intelligence(base, claim_pass)
        slim = {
            "ticker": ticker,
            "keys_present": keys,
            "claim_count_used": len(claims),
            "claim_titles": [row.get("title") for row in claims[:5]],
            "claim_queries": intel.get("claim_queries") or [],
            "related_entities": intel.get("related_entities") or [],
            "providers": _provider_summary(intel.get("providers") or {}),
            "report": intel.get("report") or {},
            "duplicates_removed": intel.get("duplicates_removed"),
            "raw_count": intel.get("raw_count"),
            "evidence_extracted": len(intel.get("evidence_bodies") or []),
            "news_hits": len(intel.get("news_hits") or []),
            "sample_documents": [_slim_doc(row) for row in (intel.get("recent_documents") or [])[:12]],
            "sample_facts": [
                {
                    "fact": row.get("fact"),
                    "source_url": row.get("source_url"),
                    "source_time": row.get("source_time"),
                    "source_tier": row.get("source_tier"),
                }
                for row in (intel.get("facts") or [])[:8]
            ],
            "warnings": intel.get("warnings") or [],
            "budget_remaining": intel.get("budget_remaining"),
        }
        results[ticker] = slim
        _write(f"{ticker.lower()}_external.json", slim)

    comparison = {
        ticker: (row.get("report") or {}).get("tavily_vs_exa") or {}
        for ticker, row in results.items()
    }
    _write("tavily_vs_exa.json", comparison)

    brains = {}
    if keys["llm"] and os.getenv("PHASE12_SKIP_BRAIN") not in {"1", "true", "yes"}:
        for ticker in TICKERS:
            print("brain live", ticker, flush=True)
            result = run_brain(research, ticker, store=store, fetch_live=True)
            report = ((result.get("audit") or {}).get("external_intelligence_report") or {})
            brains[ticker] = {
                "run_id": (result.get("run") or {}).get("run_id"),
                "status": (result.get("run") or {}).get("status"),
                "core_claim_count": len(result.get("claims") or []),
                "news_count": len(result.get("news") or []),
                "evidence_created": ((result.get("audit") or {}).get("evidence_created")),
                "external_intelligence_report": report,
                "tavily_vs_exa": ((result.get("audit") or {}).get("tavily_vs_exa") or {}),
                "claim_queries": ((result.get("audit") or {}).get("claim_queries") or [])[:12],
                "related_entities": ((result.get("audit") or {}).get("related_entities") or []),
            }
            _write(f"{ticker.lower()}_brain.json", brains[ticker])
    else:
        print("skipping Brain runs", flush=True)

    delivery = {
        "phase": "1.2",
        "generated_at": _now(),
        "news_window_days": NEWS_WINDOW_DAYS,
        "keys_present": keys,
        "benzinga": "not_wired",
        "provider_call_success": {
            ticker: {name: row.get("status") for name, row in (item.get("providers") or {}).items()}
            for ticker, item in results.items()
        },
        "provider_hit_counts": {
            ticker: {name: row.get("hit_count") for name, row in (item.get("providers") or {}).items()}
            for ticker, item in results.items()
        },
        "coverage_30d": {
            ticker: {
                "dated_recent_items": (item.get("report") or {}).get("dated_recent_items"),
                "full_text_items": (item.get("report") or {}).get("full_text_items"),
                "tier1_count": (item.get("report") or {}).get("tier1_count"),
                "tier2_count": (item.get("report") or {}).get("tier2_count"),
                "tier3_count": (item.get("report") or {}).get("tier3_count"),
                "tier4_count": (item.get("report") or {}).get("tier4_count"),
                "customer_sources": (item.get("report") or {}).get("customer_sources"),
                "supplier_sources": (item.get("report") or {}).get("supplier_sources"),
                "industry_sources": (item.get("report") or {}).get("industry_sources"),
                "duplicates_removed": item.get("duplicates_removed"),
                "raw_count": item.get("raw_count"),
                "evidence_extracted": item.get("evidence_extracted"),
                "coverage_gaps": (item.get("report") or {}).get("coverage_gaps"),
                "valuable_domains": (item.get("report") or {}).get("valuable_domains"),
                "claim_query_examples": [row.get("query") for row in (item.get("claim_queries") or [])][:8],
            }
            for ticker, item in results.items()
        },
        "tavily_vs_exa": comparison,
        "brains": brains,
        "still_missing": {
            "tavily_key": not keys["tavily"],
            "exa_key": not keys["exa"],
            "fred_key": not keys["fred"],
            "note": "FRED can use keyless CSV. Paste TAVILY_API_KEY and EXA_API_KEY into .env to enable those discovery providers. Benzinga is intentionally not wired.",
        },
    }
    _write("phase12_delivery.json", delivery)


if __name__ == "__main__":
    os.environ.setdefault("RESEARCH_BACKFILL_TIMEOUT_SECONDS", "300")
    main()
