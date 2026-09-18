-- Brain v2 Phase 1: persist rejected proposals and observation memory.

ALTER TABLE brain_change_proposals
    ADD COLUMN IF NOT EXISTS reason_code TEXT NOT NULL DEFAULT '';

ALTER TABLE brain_change_proposals
    ADD COLUMN IF NOT EXISTS related_objects TEXT[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS brain_observation_memory (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'news',
    material BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT NOT NULL DEFAULT '',
    fingerprint TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_observation_memory_ticker
    ON brain_observation_memory (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_brain_observation_memory_fingerprint
    ON brain_observation_memory (ticker, fingerprint)
    WHERE fingerprint IS NOT NULL AND fingerprint <> '';
