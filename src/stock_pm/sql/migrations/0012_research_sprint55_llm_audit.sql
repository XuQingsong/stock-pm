-- Sprint 5.5: persist whether a research agent actually called a model.

ALTER TABLE research_agent_runs
    ADD COLUMN IF NOT EXISTS llm_called BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS llm_status TEXT,
    ADD COLUMN IF NOT EXISTS llm_provider TEXT,
    ADD COLUMN IF NOT EXISTS prompt_hash TEXT,
    ADD COLUMN IF NOT EXISTS latency_ms INTEGER,
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE research_agent_runs
    DROP CONSTRAINT IF EXISTS research_agent_runs_llm_status_check;

ALTER TABLE research_agent_runs
    ADD CONSTRAINT research_agent_runs_llm_status_check
    CHECK (llm_status IS NULL OR llm_status IN ('ok', 'skipped', 'failed', 'fallback'));
