-- Sprint 4.5: persist valuation calibration (bridge, drivers, status) without overwriting cases.

ALTER TABLE research_valuations
    ADD COLUMN IF NOT EXISTS calibration_json JSONB NOT NULL DEFAULT '{}'::jsonb;
