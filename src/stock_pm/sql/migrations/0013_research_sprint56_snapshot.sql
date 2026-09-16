-- Sprint 5.6: freeze one Research Snapshot per official PM/Judge run.

ALTER TABLE research_packs
    ADD COLUMN IF NOT EXISTS pack_id TEXT;
ALTER TABLE research_packs
    ADD COLUMN IF NOT EXISTS pack_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE research_packs
    ADD COLUMN IF NOT EXISTS is_fixture BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE research_packs
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'production';

CREATE TABLE IF NOT EXISTS research_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    workflow_run_id TEXT REFERENCES research_workflow_runs(id) ON DELETE SET NULL,
    pack_id TEXT,
    pack_version INTEGER,
    pack_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    evidence_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    assumption_ids TEXT[] NOT NULL DEFAULT '{}',
    assumption_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    findings_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    market_data_timestamp TIMESTAMPTZ,
    spot_price NUMERIC,
    valuation_input_version TEXT,
    valuation_method_version TEXT,
    valuation_id TEXT,
    is_fixture BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot_status TEXT NOT NULL DEFAULT 'valid'
        CHECK (snapshot_status IN ('valid', 'invalid')),
    invalid_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    pack_latest_report_date TEXT,
    pack_updated_at TIMESTAMPTZ,
    source TEXT NOT NULL DEFAULT 'production',
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    model TEXT,
    prompt_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_snapshots_ticker
    ON research_snapshots (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_snapshots_workflow
    ON research_snapshots (workflow_run_id);

CREATE INDEX IF NOT EXISTS idx_research_snapshots_production
    ON research_snapshots (ticker, created_at DESC)
    WHERE is_fixture = FALSE AND snapshot_status = 'valid';

ALTER TABLE research_valuations
    ADD COLUMN IF NOT EXISTS snapshot_id TEXT REFERENCES research_snapshots(snapshot_id) ON DELETE SET NULL;
ALTER TABLE research_valuations
    ADD COLUMN IF NOT EXISTS valuation_method_version TEXT;

ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS snapshot_id TEXT REFERENCES research_snapshots(snapshot_id) ON DELETE SET NULL;

ALTER TABLE research_pm_rulings
    ADD COLUMN IF NOT EXISTS snapshot_id TEXT REFERENCES research_snapshots(snapshot_id) ON DELETE SET NULL;
