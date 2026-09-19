# Offline Brain materialize from research

One-shot (or idempotent) CLI. Writes `brain_*` from existing `research_*` / related tables, then stops.

```bash
python -m stock_pm.brain.materialize_from_research --tickers AVGO,LITE
```

Hard constraints:

- Page views (`GET /api/market/overview`, `/api/brain/{symbol}/pm-view`, claim detail) keep reading persisted Brain only. They do not call this job, `run_brain`, or GLM.
- This module does not schedule a recurring rerun.
- Zero LLM. If a field cannot be copied or mechanically classified from existing JSON/tables, it stays empty.

## Why `/api/market/overview` was empty

Production `brain_*` tables were empty. `product_read.build_market_overview` only clusters `brain_market_hypotheses` / attentions / expectations / macro-or-industry `brain_states`. Research packs, theses, and evidence do not appear on that API until this job maps them.

`MarketDominantDriver` still requires a **cluster** (2+ tickers on the same theme, or a macro/industry state plus a hypothesis/attention). A single ticker hypothesis alone will not promote.

## What is copied

| Source | Brain target | Rule |
| --- | --- | --- |
| `research_packs.company_profile` | `brain_states` (company) | legal name / sector / existing summary only |
| `research_packs.industry_context` | `brain_states` (industry) | existing text; theme via `product_read.theme_key` |
| `research_packs.major_events` | `brain_events` | title/type already on the pack row |
| `research_packs.earnings_history` / `guidance_history` | `brain_expectations` | only when actual **and** expected numbers already exist |
| `research_assumptions` | `brain_claims` + market hyp/attention when the statement already matches a market-wide theme | status/role/confidence mapped; no rewrite |
| `assumption_evidence_links` | `brain_claim_evidence_links` | linked evidence ids only |
| `investment_theses` (latest) | `brain_thesis_snapshots` | `core_thesis` and existing invalidation / monitor strings |
| `research_valuations` | `brain_valuation_states.supporting_data` | cases copied as-is; direction left `uncertain` unless already present |
| latest `research_snapshots` + latest success per `research_agent_runs.agent_name` | hypotheses / value drivers | only `statement` / `driver` / `why_it_matters` already in JSON |
| `environment_snapshots` (latest per scope) | `brain_states` (macro, ticker-less for market scope) | skip `missing` / “环境信息暂缺” placeholders |
| `market_events` | `brain_events` | recent titles only; issuer capex stays a trigger, not a dominant driver |

LITE (or any ticker) without a pack / assumptions / thesis / snapshot returns `status=empty` and writes nothing ticker-specific.

## Gaps (left empty on purpose)

- Causal edges / graph
- Exposures, unless `key_economic_drivers` already has `mechanism` or `valuation_channel`
- `brain_scenarios` and `brain_financial_impacts`
- `what_would_invalidate` unless already on the assumption or thesis
- Price divergences
- Cross-asset / sector summaries
- Unlinked `research_evidence` (thousands of rows) — not reinterpreted as claims
- Any GLM paraphrase, probability, or invented mechanism

## Idempotency

Upserts use existing unique keys (`ticker+canonical_key`, `ticker+name`, `ticker+state_key`, `ticker+fingerprint`, `claim_key`). Thesis snapshots are written once per ticker by this job. Re-running the CLI does not grow those tables.

## Not in scope

Deploy, cron, page-open bootstrap, or calling `run_brain` / `bootstrap_brain`.
