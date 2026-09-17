"""Current system audit + Phase 1 Brain reuse map."""

from __future__ import annotations

AUDIT = {
    "reuse_as_is": [
        "Research Pack / PackBuilder / DatabasePackSource",
        "SEC companyfacts + submissions (live_fetch)",
        "earnings_reports + fundamentals_snapshots + price_bars",
        "Evidence Store + provenance (source, url, source_time, excerpt)",
        "Research Snapshot freeze (0013)",
        "LLM gateway stock_pm.llm.complete_json + SettingsCompleter + complete_structured",
        "research_agent_runs / llm audit columns",
        "web_search (DuckDuckGo html) + news_articles",
        "valuation engine numbers remain Python-owned",
        "fixture isolation + snapshot consistency guards",
        "Assumption / commitment ledger / management delivery (not Brain primary chain)",
        "PM/Judge research pipeline (kept; Brain PM synthesis is parallel)",
    ],
    "extend": [
        "BrainState / BrainClaim / BrainClaimVersion / ClaimEvidenceLink / BrainResearchQuestion / BrainRun (0014)",
        "7-day news interpretation and MATERIAL/CONTEXTUAL/NOISE layering",
        "LLM steps A–E dedicated to claims (not regex/template claims)",
        "/brain UI",
        "Brain quality FAIL-loud axes",
    ],
    "keep_but_not_brain_main_chain": [
        "run_new_ticker_research follow-up task loop",
        "desk / prediction / tape / options / review pages",
        "macro engine",
        "assumption engine proposals",
        "research_review homepage IA",
    ],
    "news_sources": [
        "news_articles table (Alpaca/news ingest when keys exist)",
        "pack.major_events",
        "DuckDuckGo html.duckduckgo.com/html (keyless web_search)",
        "Google CSE if GOOGLE_CSE_API_KEY set (events discovery, not Brain-primary)",
        "SEC filings via sec.gov",
        "Tier-2 hosts recognized: reuters.com, bloomberg.com, ft.com, wsj.com, apnews.com — fetch is best-effort, not a paid feed",
    ],
    "sec_earnings": [
        "sec.company_tickers, submissions, companyfacts",
        "Nasdaq earnings + companyfacts merge",
        "transcripts via web_search (often partial)",
        "guidance extracted from transcripts/exhibits",
        "FMP / Alpha Vantage only if keys exist (this environment: missing)",
    ],
    "price_valuation": [
        "Alpaca bars if keys exist (this environment: missing)",
        "Yahoo / Stooq daily bars as keyless fallback",
        "PE/margins/shares from fundamentals_snapshots + pack company_profile",
        "Research valuation engine (complete_bridge) not re-run as Brain's primary output in Phase 1",
        "Forward PE / consensus: unavailable unless already on pack",
    ],
    "llm_provider": {
        "code_default_provider": "openai-compatible",
        "code_default_model_if_unset": "gpt-4o-mini",
        "production_intended": "LLM_BASE_URL=https://api.deepseek.com/v1 LLM_MODEL=deepseek-chat",
        "this_environment_llm_api_key": False,
        "research_api_calls_llm": "Yes when SettingsCompleter + LLM_API_KEY; production last AVGO PM had llm_called=false",
        "brain_calls_llm": "Yes: steps A–E via complete_structured. Missing key => skipped, no template claims.",
    },
    "golden_data_now": {
        "AVGO": "Live Brain run brun_8a0144e78c854e4a83bbd92bac3527f0; snapshot rsnap_fcc7820e9a9942358006d12fd21a258b; price 344.82 2026-09-15; TTM rev 87.041B EPS 8.57 PE 40.24; FCF/segments/consensus unavailable; news searched 20 (SEC index + Nasdaq/Zacks); 0 core claims because LLM_API_KEY missing",
        "AAPL": "Live Brain run brun_d9d002caf13d4a5dab71a9b72b412b3a; snapshot rsnap_7dae1bd27a3f457f8ea2aa3b6283588b; price 332.41 2026-09-16; TTM rev 458.393B EPS 8.61 PE 38.61; FCF/segments/consensus unavailable; 0 core claims, LLM skipped",
        "LITE": "Live Brain run brun_c6298fd5b05d4074bc88b03208504bdc; snapshot rsnap_52d6dc6568f949aaa6fded65b00e969e; price 919.40 2026-09-16; TTM revenue unavailable; EPS 6.36 PE 144.56; Q1 FY27 guidance excerpt present; data coverage Partial; 0 core claims, LLM skipped",
    },
    "blockers": [
        {
            "missing": "LLM_API_KEY",
            "affects": "Core Claims, news interpretation, PM view, LLM Reasoning quality",
            "fix": "Set LLM_API_KEY + LLM_BASE_URL=https://api.deepseek.com/v1 + LLM_MODEL=deepseek-chat in .env.server",
        },
        {
            "missing": "ALPACA / FMP / Alpha Vantage / Google CSE",
            "affects": "live prices, consensus, paid news, CSE discovery",
            "fix": "Optional; Yahoo/SEC/DuckDuckGo still run keyless",
        },
        {
            "missing": "Reuters/Bloomberg API",
            "affects": "reliable last-7-day high-quality news body text",
            "fix": "DuckDuckGo may surface reuters.com URLs but often headline/snippet only; paid feed would raise News Coverage",
        },
    ],
}
