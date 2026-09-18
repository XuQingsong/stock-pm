-- Brain v2 Phase 3: thin market attention. Not a full Market Driver / Expectation system.

CREATE TABLE IF NOT EXISTS brain_market_attention (
    attention_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    statement TEXT NOT NULL DEFAULT '',
    object_id TEXT NOT NULL DEFAULT '',
    related_objects TEXT[] NOT NULL DEFAULT '{}',
    source_kind TEXT NOT NULL DEFAULT 'news',
    alignment TEXT NOT NULL DEFAULT 'unknown',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_market_attention_name
    ON brain_market_attention (ticker, name);

CREATE INDEX IF NOT EXISTS idx_brain_market_attention_ticker
    ON brain_market_attention (ticker, updated_at DESC);
