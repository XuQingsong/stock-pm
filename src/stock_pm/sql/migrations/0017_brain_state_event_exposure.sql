-- Brain v1 Stage 2: State identity, Events, Exposure.

ALTER TABLE brain_states
    ADD COLUMN IF NOT EXISTS state_key TEXT,
    ADD COLUMN IF NOT EXISTS subject TEXT,
    ADD COLUMN IF NOT EXISTS qualitative_state TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS current_value TEXT,
    ADD COLUMN IF NOT EXISTS related_entities TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE brain_states DROP CONSTRAINT IF EXISTS brain_states_state_type_check;
ALTER TABLE brain_states
    ADD CONSTRAINT brain_states_state_type_check
    CHECK (state_type IN (
        'company', 'industry', 'macro', 'event', 'event_shock', 'market_expectation', 'data_quality'
    ));

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_states_key
    ON brain_states (ticker, state_key)
    WHERE state_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS brain_events (
    event_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'other',
    subject TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    event_date TIMESTAMPTZ,
    entities TEXT[] NOT NULL DEFAULT '{}',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    confidence TEXT,
    materiality TEXT NOT NULL DEFAULT 'context',
    novelty TEXT,
    source_quality TEXT,
    fact_reliability TEXT,
    decision_targets TEXT[] NOT NULL DEFAULT '{}',
    affected_states TEXT[] NOT NULL DEFAULT '{}',
    affected_drivers TEXT[] NOT NULL DEFAULT '{}',
    affected_claims TEXT[] NOT NULL DEFAULT '{}',
    transmission JSONB NOT NULL DEFAULT '{}'::jsonb,
    financial_impact JSONB NOT NULL DEFAULT '{}'::jsonb,
    scenario_impact JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint TEXT,
    url TEXT,
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_events_ticker
    ON brain_events (ticker, event_date DESC NULLS LAST);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_events_fingerprint
    ON brain_events (ticker, fingerprint)
    WHERE fingerprint IS NOT NULL;

CREATE TABLE IF NOT EXISTS brain_exposures (
    exposure_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    state_or_event TEXT,
    event_id TEXT,
    state_id TEXT,
    exposure_type TEXT NOT NULL DEFAULT 'financial',
    direction TEXT,
    magnitude TEXT,
    direct_or_indirect TEXT,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    uncertainty TEXT,
    related_only BOOLEAN NOT NULL DEFAULT FALSE,
    can_affect_claim BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_exposures_ticker
    ON brain_exposures (ticker, created_at DESC);
