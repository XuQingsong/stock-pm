-- Brain v1 Stage 4: Financial impact bridge and scenario policy fields.

CREATE TABLE IF NOT EXISTS brain_financial_impacts (
    impact_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    direction TEXT,
    magnitude_range JSONB,
    time_horizon TEXT,
    confidence TEXT,
    mechanism TEXT NOT NULL DEFAULT '',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    direction_only BOOLEAN NOT NULL DEFAULT TRUE,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_financial_impacts_ticker
    ON brain_financial_impacts (ticker, object_type, created_at DESC);
