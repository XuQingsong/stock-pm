-- Phase 1 Intelligent Brain. Parallel to the existing Research pipeline.
-- Does not replace research_packs, research_evidence, or research_snapshots.

CREATE TABLE IF NOT EXISTS brain_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    snapshot_id TEXT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'partial', 'failed')),
    model TEXT,
    prompt_version TEXT NOT NULL DEFAULT 'brain-phase1-v1',
    llm_calls JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    news_searched INTEGER NOT NULL DEFAULT 0,
    sources_fetched INTEGER NOT NULL DEFAULT 0,
    evidence_created INTEGER NOT NULL DEFAULT 0,
    candidate_claim_count INTEGER NOT NULL DEFAULT 0,
    core_claim_count INTEGER NOT NULL DEFAULT 0,
    claim_versions_changed INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    fallbacks JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality JSONB NOT NULL DEFAULT '{}'::jsonb,
    company_understanding JSONB NOT NULL DEFAULT '{}'::jsonb,
    pm_synthesis JSONB NOT NULL DEFAULT '{}'::jsonb,
    header JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_brain_runs_ticker
    ON brain_runs (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_states (
    state_id TEXT PRIMARY KEY,
    ticker TEXT,
    state_type TEXT NOT NULL
        CHECK (state_type IN ('company', 'industry', 'macro', 'event')),
    name TEXT NOT NULL,
    statement TEXT NOT NULL DEFAULT '',
    direction TEXT,
    confidence TEXT
        CHECK (confidence IS NULL OR confidence IN ('high', 'medium', 'low')),
    effective_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    source TEXT,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_states_ticker
    ON brain_states (ticker, updated_at DESC);

CREATE TABLE IF NOT EXISTS brain_claims (
    claim_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    claim_type TEXT NOT NULL
        CHECK (claim_type IN ('structural', 'operating', 'valuation', 'event')),
    status TEXT NOT NULL
        CHECK (status IN (
            'emerging', 'strongly_supported', 'partially_supported', 'unverified',
            'challenged', 'contradicted', 'background', 'closed'
        )),
    importance TEXT NOT NULL DEFAULT 'medium'
        CHECK (importance IN ('high', 'medium', 'low')),
    confidence TEXT NOT NULL DEFAULT 'low'
        CHECK (confidence IN ('high', 'medium', 'low')),
    time_horizon TEXT
        CHECK (time_horizon IS NULL OR time_horizon IN ('short', 'medium', 'long')),
    why_it_matters TEXT NOT NULL DEFAULT '',
    financial_driver TEXT,
    is_core BOOLEAN NOT NULL DEFAULT FALSE,
    current_version_id TEXT,
    reasoning JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    snapshot_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_claims_ticker
    ON brain_claims (ticker, is_core DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS brain_claim_versions (
    claim_version_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES brain_claims(claim_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    reason_for_change TEXT NOT NULL DEFAULT '',
    added_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    removed_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    counter_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    snapshot_id TEXT,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (claim_id, version)
);

CREATE INDEX IF NOT EXISTS idx_brain_claim_versions_claim
    ON brain_claim_versions (claim_id, version DESC);

CREATE TABLE IF NOT EXISTS brain_claim_evidence_links (
    link_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES brain_claims(claim_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    direction TEXT NOT NULL
        CHECK (direction IN ('support', 'oppose', 'contextual', 'irrelevant')),
    strength TEXT NOT NULL DEFAULT 'medium'
        CHECK (strength IN ('strong', 'medium', 'weak')),
    relevance TEXT NOT NULL DEFAULT 'direct'
        CHECK (relevance IN ('direct', 'indirect', 'background')),
    reason TEXT NOT NULL DEFAULT '',
    proves TEXT NOT NULL DEFAULT '',
    does_not_prove TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_claim_links_claim
    ON brain_claim_evidence_links (claim_id);
CREATE INDEX IF NOT EXISTS idx_brain_claim_links_evidence
    ON brain_claim_evidence_links (evidence_id);

CREATE TABLE IF NOT EXISTS brain_research_questions (
    question_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    related_claim_id TEXT REFERENCES brain_claims(claim_id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    why_it_matters TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('high', 'medium', 'low')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'answered', 'dropped')),
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_questions_ticker
    ON brain_research_questions (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_news_items (
    news_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    evidence_id TEXT,
    layer TEXT NOT NULL DEFAULT 'uninterpreted'
        CHECK (layer IN ('material', 'contextual', 'noise', 'uninterpreted')),
    title TEXT NOT NULL DEFAULT '',
    source TEXT,
    url TEXT,
    published_at TIMESTAMPTZ,
    new_fact TEXT,
    affected_claim_id TEXT,
    impact TEXT,
    reason TEXT,
    financial_impact TEXT,
    quantifiable BOOLEAN,
    claim_version_changed BOOLEAN NOT NULL DEFAULT FALSE,
    interpretation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_news_run
    ON brain_news_items (run_id, layer);
CREATE INDEX IF NOT EXISTS idx_brain_news_ticker
    ON brain_news_items (ticker, published_at DESC);
