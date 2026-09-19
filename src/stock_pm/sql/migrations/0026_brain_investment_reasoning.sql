-- Claim → Financial Impact → Scenario → ValuationState → Thesis.
-- Extends the existing financial-impact table; adds scenario / valuation / thesis.

ALTER TABLE brain_financial_impacts
    ADD COLUMN IF NOT EXISTS claim_id TEXT,
    ADD COLUMN IF NOT EXISTS magnitude_band TEXT,
    ADD COLUMN IF NOT EXISTS support_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS counter_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_financial_impacts_claim_metric
    ON brain_financial_impacts (ticker, claim_id, metric)
    WHERE claim_id IS NOT NULL AND claim_id <> '';

ALTER TABLE brain_claims
    ADD COLUMN IF NOT EXISTS what_would_invalidate TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS financial_impact_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS scenario_implication TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS brain_scenarios (
    scenario_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    scenario_type TEXT NOT NULL,
    assumptions TEXT[] NOT NULL DEFAULT '{}',
    linked_claim_ids TEXT[] NOT NULL DEFAULT '{}',
    financial_impact_ids TEXT[] NOT NULL DEFAULT '{}',
    probability_band TEXT NOT NULL DEFAULT 'unknown',
    confidence TEXT NOT NULL DEFAULT 'medium',
    key_upside_conditions TEXT[] NOT NULL DEFAULT '{}',
    key_downside_conditions TEXT[] NOT NULL DEFAULT '{}',
    invalidation_conditions TEXT[] NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, scenario_type)
);

CREATE INDEX IF NOT EXISTS idx_brain_scenarios_ticker
    ON brain_scenarios (ticker, scenario_type);

CREATE TABLE IF NOT EXISTS brain_valuation_states (
    valuation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    valuation_context TEXT NOT NULL DEFAULT '',
    scenario_id TEXT,
    valuation_direction TEXT NOT NULL DEFAULT 'uncertain',
    confidence TEXT NOT NULL DEFAULT 'low',
    valuation_data_missing BOOLEAN NOT NULL DEFAULT TRUE,
    supporting_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_valuation_states_ticker
    ON brain_valuation_states (ticker, updated_at DESC);

CREATE TABLE IF NOT EXISTS brain_thesis_snapshots (
    thesis_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    current_thesis TEXT NOT NULL DEFAULT '',
    top_supporting_claim_ids TEXT[] NOT NULL DEFAULT '{}',
    top_risk_claim_ids TEXT[] NOT NULL DEFAULT '{}',
    base_scenario_id TEXT,
    key_upside_condition TEXT NOT NULL DEFAULT '',
    key_downside_condition TEXT NOT NULL DEFAULT '',
    what_would_change_thesis TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium',
    reason TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_thesis_snapshots_ticker
    ON brain_thesis_snapshots (ticker, updated_at DESC);
