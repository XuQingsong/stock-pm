-- Brain v2 Phase 3 completion: Expectation State + Market Driver Hypothesis.

CREATE TABLE IF NOT EXISTS brain_expectations (
    expectation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    actual DOUBLE PRECISION,
    expected DOUBLE PRECISION,
    comparison TEXT NOT NULL DEFAULT 'in_line',
    trend TEXT NOT NULL DEFAULT 'unchanged',
    confidence TEXT NOT NULL DEFAULT 'medium',
    supporting_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    last_material_change TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'news',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_expectations_name
    ON brain_expectations (ticker, name);

CREATE INDEX IF NOT EXISTS idx_brain_expectations_ticker
    ON brain_expectations (ticker, updated_at DESC);

CREATE TABLE IF NOT EXISTS brain_market_hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',
    hypothesis TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'candidate',
    supporting_observations TEXT[] NOT NULL DEFAULT '{}',
    counter_observations TEXT[] NOT NULL DEFAULT '{}',
    related_expectation_id TEXT,
    related_attention_id TEXT,
    related_causal_path TEXT[] NOT NULL DEFAULT '{}',
    source_kind TEXT NOT NULL DEFAULT 'news',
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_market_hypotheses_key
    ON brain_market_hypotheses (ticker, canonical_key);

CREATE INDEX IF NOT EXISTS idx_brain_market_hypotheses_ticker
    ON brain_market_hypotheses (ticker, status, updated_at DESC);
