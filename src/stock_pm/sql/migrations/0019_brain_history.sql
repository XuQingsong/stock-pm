-- Brain v1 Stage 6: object history for reconstructing thesis changes.

CREATE TABLE IF NOT EXISTS brain_history (
    history_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    from_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    to_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    event_id TEXT,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_history_ticker
    ON brain_history (ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_history_object
    ON brain_history (object_type, object_id, created_at DESC);
