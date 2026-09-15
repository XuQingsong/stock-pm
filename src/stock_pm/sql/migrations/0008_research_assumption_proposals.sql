-- Sprint 3: agents may propose assumption state changes; only PM/Judge writes status.
-- proposed_status uses suggestion verbs, not research_assumptions.status values.

CREATE TABLE IF NOT EXISTS research_assumption_proposals (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    assumption_id TEXT NOT NULL REFERENCES research_assumptions(id) ON DELETE CASCADE,
    current_status TEXT NOT NULL DEFAULT 'unverified',
    proposed_status TEXT NOT NULL
        CHECK (proposed_status IN ('strengthen', 'weaken', 'unchanged', 'broken')),
    reason TEXT NOT NULL DEFAULT '',
    confidence NUMERIC,
    supporting_count INTEGER NOT NULL DEFAULT 0,
    opposing_count INTEGER NOT NULL DEFAULT 0,
    contextual_count INTEGER NOT NULL DEFAULT 0,
    unresolved_gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    produced_by TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    agent_run_id TEXT REFERENCES research_agent_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT research_assumption_proposals_reason_present CHECK (btrim(reason) <> '')
);

CREATE INDEX IF NOT EXISTS idx_research_assumption_proposals_ticker
    ON research_assumption_proposals (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_assumption_proposals_assumption
    ON research_assumption_proposals (assumption_id, created_at DESC);
