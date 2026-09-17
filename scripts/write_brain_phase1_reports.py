from __future__ import annotations

import json
from pathlib import Path

from stock_pm.brain.audit import AUDIT
from stock_pm.database import Database

OUT = Path("artifacts/brain_phase1")


def _load(ticker: str) -> dict:
    return json.loads((OUT / f"{ticker.lower()}_brain.json").read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Database()
    tickers = ("AVGO", "AAPL", "LITE")
    live = {t: _load(t) for t in tickers}

    news_by_ticker: dict[str, list] = {}
    with db.pool.connection() as conn:
        for ticker in tickers:
            rows = conn.execute(
                """
                SELECT news_id, ticker, evidence_id, layer, title, source, url, published_at,
                       new_fact, affected_claim_id, impact, reason, financial_impact,
                       quantifiable, claim_version_changed
                FROM brain_news_items
                WHERE ticker = %(ticker)s
                ORDER BY created_at
                """,
                {"ticker": ticker},
            ).fetchall()
            news_by_ticker[ticker] = [dict(row) for row in rows]

    news_processing = {}
    for ticker in tickers:
        items = []
        for row in news_by_ticker[ticker]:
            items.append(
                {
                    "News": row.get("title"),
                    "Source": row.get("source"),
                    "URL": row.get("url"),
                    "evidence_id": row.get("evidence_id"),
                    "New Fact": row.get("new_fact") or "unavailable (LLM interpretation skipped: missing LLM_API_KEY)",
                    "Affected Claim": row.get("affected_claim_id") or "none",
                    "Impact": row.get("impact") or "uninterpreted",
                    "Reason": row.get("reason") or "News stored but not interpreted because LLM was not invoked.",
                    "Financial Impact": row.get("financial_impact") or "unavailable",
                    "Quantifiable": bool(row.get("quantifiable")),
                    "Claim Version Changed": "yes" if row.get("claim_version_changed") else "no",
                    "layer": row.get("layer"),
                }
            )
        news_processing[ticker] = {
            "count": len(items),
            "interpreted": sum(1 for item in items if item["layer"] != "uninterpreted"),
            "material": sum(1 for item in items if item["layer"] == "material"),
            "items": items,
        }

    quality = {
        ticker: {
            "run_id": live[ticker]["run_id"],
            "snapshot_id": live[ticker]["snapshot_id"],
            "status": live[ticker]["status"],
            "axes": live[ticker]["quality"]["axes"],
            "warnings": live[ticker]["quality"]["warnings"],
            "view_recompute_note": (
                "API /brain pages re-score News Coverage on read. SEC-index-only hits "
                "without Reuters/Bloomberg/IR are Partial, not Good."
            ),
        }
        for ticker in tickers
    }

    llm_audit = {
        ticker: {
            "llm_invoked": live[ticker]["audit"]["llm_invoked"],
            "model": live[ticker]["audit"]["model"],
            "prompt_version": live[ticker]["audit"]["prompt_version"],
            "llm_calls": live[ticker]["audit"]["llm_calls"],
            "input_tokens": live[ticker]["audit"]["input_tokens"],
            "output_tokens": live[ticker]["audit"]["output_tokens"],
            "latency_ms": live[ticker]["audit"]["latency_ms"],
            "fallbacks": live[ticker]["audit"]["fallbacks"],
            "core_claim_count": live[ticker]["audit"]["core_claim_count"],
            "candidate_claim_count": live[ticker]["audit"]["candidate_claim_count"],
            "claim_versions_changed": live[ticker]["audit"]["claim_versions_changed"],
            "news_searched": live[ticker]["audit"]["news_searched"],
            "evidence_created": live[ticker]["audit"]["evidence_created"],
            "errors": live[ticker]["audit"]["errors"],
        }
        for ticker in tickers
    }

    coverage = {
        ticker: {
            "header": live[ticker]["header"],
            "missing_fields": live[ticker]["header"].get("missing_fields"),
            "price": live[ticker]["header"].get("price"),
            "price_timestamp": live[ticker]["header"].get("price_timestamp"),
            "pe_ttm": (live[ticker]["header"].get("valuation") or {}).get("pe_ttm"),
            "forward_pe": (live[ticker]["header"].get("valuation") or {}).get("pe_forward"),
            "consensus": (live[ticker]["header"].get("forward") or {}).get("consensus"),
            "guidance": (live[ticker]["header"].get("forward") or {}).get("management_guidance"),
            "news_sources": sorted({item.get("Source") for item in news_processing[ticker]["items"]}),
        }
        for ticker in tickers
    }

    (OUT / "architecture.json").write_text(json.dumps(AUDIT, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "quality_report.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "llm_audit.json").write_text(json.dumps(llm_audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "news_processing.json").write_text(json.dumps(news_processing, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "data_coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "core_claims.json").write_text(
        json.dumps({ticker: live[ticker]["core_claims"] for ticker in tickers}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "news_claim_update_demo.json").write_text(
        json.dumps(
            {
                "live_llm": False,
                "reason": "LLM_API_KEY is not set in this environment. Live runs stored news as uninterpreted and created zero Core Claims. No live News → Claim Version update exists.",
                "tests": "tests/test_brain_phase1.py::test_brain_run_calls_llm_and_grounds_claims creates a Reuters hit, persists evidence_id, LLM marks it material, and inserts BrainClaimVersion 2.",
                "required_to_complete_live_demo": [
                    "Set LLM_API_KEY (DeepSeek: LLM_BASE_URL=https://api.deepseek.com/v1, LLM_MODEL=deepseek-chat)",
                    "Re-run scripts/run_brain_phase1.py",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (OUT / "limiters.json").write_text(
        json.dumps(
            {
                "blockers": AUDIT["blockers"],
                "severe": [
                    {
                        "issue": "LLM_API_KEY missing",
                        "affects": "Steps A–E, Core Claims, news interpretation, PM view, claim versions, claim/evidence analysis UI",
                        "fix": "Configure DeepSeek key and re-run Brain. Do not template-fill claims.",
                    },
                    {
                        "issue": "No Reuters/Bloomberg/IR feed; DuckDuckGo often returns SEC index titles (8-K/10-Q) and Nasdaq/Zacks aggregators without published dates or article bodies",
                        "affects": "Last-7-day material news, News Coverage honesty, customer/supplier/industry events",
                        "fix": "Paid news API or IR crawl with full text + timestamps; keep fail-loud if still missing",
                    },
                    {
                        "issue": "LITE TTM revenue / quarter revenue / margins unavailable from current SEC/Nasdaq merge",
                        "affects": "LITE financial header completeness; Core Claims would be under-grounded even with LLM",
                        "fix": "Parse LITE 10-K/10-Q companyfacts more completely or add a trusted fundamentals vendor",
                    },
                    {
                        "issue": "Consensus / forward PE / FCF / segment mix unavailable",
                        "affects": "Valuation header, growth vs PE tension, segment claims",
                        "fix": "Wire one trusted consensus source; parse cash flow statements for FCF; keep origin labels",
                    },
                    {
                        "issue": "DDG after: filter is weak; undated SEC filings leak into the 7-day list",
                        "affects": "Freshness of news processing",
                        "fix": "Require published_at or EDGAR filing date before counting as last-7-day",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote reports under", OUT)


if __name__ == "__main__":
    main()
