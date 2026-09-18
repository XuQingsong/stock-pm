-- Brain v1 Stage 1: Value Driver Layer. Does not rewrite Evidence Set or claims.

CREATE TABLE IF NOT EXISTS brain_value_drivers (
    driver_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    driver_key TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'demand',
    financial_link TEXT,
    time_horizon TEXT,
    current_state TEXT NOT NULL DEFAULT '',
    direction TEXT,
    importance TEXT NOT NULL DEFAULT 'medium'
        CHECK (importance IN ('high', 'medium', 'low')),
    uncertainty TEXT NOT NULL DEFAULT 'medium'
        CHECK (uncertainty IN ('high', 'medium', 'low')),
    persistence TEXT NOT NULL DEFAULT 'medium'
        CHECK (persistence IN ('high', 'medium', 'low')),
    reversibility TEXT,
    why_it_matters TEXT NOT NULL DEFAULT '',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    related_claim_ids TEXT[] NOT NULL DEFAULT '{}',
    related_entity_ids TEXT[] NOT NULL DEFAULT '{}',
    missing_evidence TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    match_action TEXT,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_value_drivers_key
    ON brain_value_drivers (ticker, canonical_key)
    WHERE status IS DISTINCT FROM 'closed';

CREATE INDEX IF NOT EXISTS idx_brain_value_drivers_ticker
    ON brain_value_drivers (ticker, importance, updated_at DESC);

ALTER TABLE brain_claims
    ADD COLUMN IF NOT EXISTS related_driver_ids TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE brain_runs
    ADD COLUMN IF NOT EXISTS run_mode TEXT NOT NULL DEFAULT 'full';
