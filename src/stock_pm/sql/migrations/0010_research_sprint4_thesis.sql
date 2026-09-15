-- Sprint 4: versioned thesis extras, PM rulings, monitoring role, invalidation.

ALTER TABLE research_assumptions DROP CONSTRAINT IF EXISTS research_assumptions_thesis_role_check;
ALTER TABLE research_assumptions
    ADD CONSTRAINT research_assumptions_thesis_role_check
    CHECK (thesis_role IN ('core', 'supporting', 'watch', 'risk', 'none', 'monitoring'));

ALTER TABLE research_assumptions
    ADD COLUMN IF NOT EXISTS invalidation_condition TEXT;

ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS core_assumption_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS supporting_assumption_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS key_catalysts JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS research_quality JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS market_reaction TEXT NOT NULL DEFAULT '';
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS thesis_diff JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS research_pm_rulings (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    thesis_id TEXT REFERENCES investment_theses(id) ON DELETE SET NULL,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    assumption_id TEXT NOT NULL REFERENCES research_assumptions(id) ON DELETE CASCADE,
    final_status TEXT NOT NULL
        CHECK (final_status IN ('unverified', 'strengthened', 'unchanged', 'weakened', 'broken')),
    final_confidence NUMERIC,
    thesis_role TEXT NOT NULL DEFAULT 'supporting'
        CHECK (thesis_role IN ('core', 'supporting', 'watch', 'risk', 'none', 'monitoring')),
    reasoning TEXT NOT NULL DEFAULT '',
    key_supporting_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    key_opposing_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    unresolved_gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    invalidation_condition TEXT,
    next_verification TEXT,
    engine_proposed_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT research_pm_rulings_reason_present CHECK (btrim(reasoning) <> '')
);

CREATE INDEX IF NOT EXISTS idx_research_pm_rulings_ticker
    ON research_pm_rulings (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_pm_rulings_thesis
    ON research_pm_rulings (thesis_id);
