-- Brain v2 Phase 4: PriceFundamentalDivergence (price is a sensor, not evidence).

CREATE TABLE IF NOT EXISTS brain_price_divergences (
    divergence_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    signature TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'price_fundamental_divergence',
    status TEXT NOT NULL DEFAULT 'open',
    explanation_grade TEXT NOT NULL DEFAULT 'largely_unexplained',
    direction TEXT NOT NULL DEFAULT '',
    price_change_pct DOUBLE PRECISION,
    peer_pattern TEXT,
    opened_by_event_id TEXT,
    opened_as_of TEXT NOT NULL DEFAULT '',
    resolved_by_event_id TEXT,
    resolved_as_of TEXT NOT NULL DEFAULT '',
    known_at_open JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolution_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    price_observation_ids TEXT[] NOT NULL DEFAULT '{}',
    price_is_not_evidence_for_resolution BOOLEAN NOT NULL DEFAULT TRUE,
    unresolved_question TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'price',
    observation_count INTEGER NOT NULL DEFAULT 1,
    as_of TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_price_divergences_ticker
    ON brain_price_divergences (ticker, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_brain_price_divergences_signature
    ON brain_price_divergences (ticker, signature, status);
