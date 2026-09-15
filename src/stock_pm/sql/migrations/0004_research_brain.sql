-- Brain V1 Sprint 1: research objects. Ticker is data. No symbol-specific logic.

CREATE TABLE IF NOT EXISTS issuer_profiles (
    ticker TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL DEFAULT '',
    cik TEXT,
    fiscal_year_end_month INTEGER
        CHECK (fiscal_year_end_month IS NULL OR (fiscal_year_end_month BETWEEN 1 AND 12)),
    sector TEXT,
    gics TEXT,
    primary_exchange TEXT NOT NULL DEFAULT '',
    asset_class TEXT NOT NULL DEFAULT 'stocks',
    aliases TEXT[] NOT NULL DEFAULT '{}',
    missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_issuer_profiles_cik
    ON issuer_profiles (cik)
    WHERE cik IS NOT NULL AND cik <> '';

CREATE TABLE IF NOT EXISTS research_workflow_runs (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'api'
        CHECK (trigger IN ('watchlist', 'follow_up', 'api', 'monitor', 'test')),
    template_id TEXT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'partial', 'failed', 'cancelled')),
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    item_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_workflow_runs_ticker
    ON research_workflow_runs (ticker, started_at DESC);

CREATE TABLE IF NOT EXISTS research_tasks (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    parent_task_id TEXT REFERENCES research_tasks(id) ON DELETE SET NULL,
    root_task_id TEXT,
    depth INTEGER NOT NULL DEFAULT 0 CHECK (depth >= 0),
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_reason TEXT NOT NULL DEFAULT '',
    required_data JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_agents TEXT[] NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'blocked', 'cancelled')),
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_tasks_queue
    ON research_tasks (ticker, status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_research_tasks_run
    ON research_tasks (workflow_run_id, status);

CREATE TABLE IF NOT EXISTS research_agent_runs (
    id TEXT PRIMARY KEY,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    task_id TEXT REFERENCES research_tasks(id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    input_hash TEXT,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_agent_runs_workflow
    ON research_agent_runs (workflow_run_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_agent_runs_ticker
    ON research_agent_runs (ticker, started_at DESC);

CREATE TABLE IF NOT EXISTS research_evidence (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    fact TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    source_time TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    confidence NUMERIC,
    importance TEXT NOT NULL DEFAULT 'medium'
        CHECK (importance IN ('low', 'medium', 'high', 'critical')),
    direction TEXT NOT NULL DEFAULT 'neutral'
        CHECK (direction IN ('support', 'oppose', 'neutral')),
    raw_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    produced_by TEXT NOT NULL DEFAULT 'human_api',
    task_id TEXT REFERENCES research_tasks(id) ON DELETE SET NULL,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT research_evidence_fact_present CHECK (btrim(fact) <> ''),
    CONSTRAINT research_evidence_source_present CHECK (btrim(source) <> '')
);

CREATE INDEX IF NOT EXISTS idx_research_evidence_ticker
    ON research_evidence (ticker, source_time DESC);

CREATE TABLE IF NOT EXISTS research_assumptions (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    statement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (status IN ('unverified', 'strengthened', 'unchanged', 'weakened', 'broken')),
    importance TEXT NOT NULL DEFAULT 'medium'
        CHECK (importance IN ('low', 'medium', 'high', 'critical')),
    thesis_role TEXT NOT NULL DEFAULT 'supporting'
        CHECK (thesis_role IN ('core', 'supporting', 'watch', 'risk', 'none')),
    confidence NUMERIC,
    next_verification TEXT,
    proposed_by TEXT NOT NULL DEFAULT 'human_api',
    status_updated_by TEXT,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT research_assumptions_statement_present CHECK (btrim(statement) <> '')
);

CREATE INDEX IF NOT EXISTS idx_research_assumptions_ticker
    ON research_assumptions (ticker, thesis_role, status);

CREATE TABLE IF NOT EXISTS assumption_evidence_links (
    assumption_id TEXT NOT NULL REFERENCES research_assumptions(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES research_evidence(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('support', 'oppose')),
    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    linked_by TEXT NOT NULL DEFAULT 'system',
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    PRIMARY KEY (assumption_id, evidence_id, direction)
);

CREATE INDEX IF NOT EXISTS idx_assumption_evidence_links_evidence
    ON assumption_evidence_links (evidence_id);

CREATE TABLE IF NOT EXISTS investment_theses (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    short_term_view TEXT NOT NULL DEFAULT '',
    mid_term_view TEXT NOT NULL DEFAULT '',
    long_term_view TEXT NOT NULL DEFAULT '',
    core_thesis TEXT NOT NULL,
    key_assumption_ids TEXT[] NOT NULL DEFAULT '{}',
    key_risks JSONB NOT NULL DEFAULT '[]'::jsonb,
    invalidation_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    monitoring_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC,
    valuation_id TEXT,
    change_summary TEXT,
    actor TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, version),
    CONSTRAINT investment_theses_core_present CHECK (btrim(core_thesis) <> ''),
    CONSTRAINT investment_theses_actor_pm CHECK (actor = 'pm_judge')
);

CREATE INDEX IF NOT EXISTS idx_investment_theses_ticker
    ON investment_theses (ticker, version DESC);

CREATE TABLE IF NOT EXISTS valuations (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    thesis_id TEXT REFERENCES investment_theses(id) ON DELETE SET NULL,
    thesis_version INTEGER,
    horizon TEXT NOT NULL DEFAULT '2y',
    bear_case JSONB NOT NULL DEFAULT '{}'::jsonb,
    base_case JSONB NOT NULL DEFAULT '{}'::jsonb,
    bull_case JSONB NOT NULL DEFAULT '{}'::jsonb,
    spot_price NUMERIC,
    actor TEXT NOT NULL DEFAULT 'pm_judge',
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valuations_cases_present CHECK (
        jsonb_typeof(bear_case) = 'object'
        AND jsonb_typeof(base_case) = 'object'
        AND jsonb_typeof(bull_case) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS idx_valuations_ticker
    ON valuations (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS research_packs (
    ticker TEXT PRIMARY KEY,
    template_id TEXT NOT NULL DEFAULT 'generic_company',
    company_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    earnings_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    guidance_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    price_reaction_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    industry_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    competitive_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    major_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
