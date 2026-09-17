-- Brain Integrity: stable claim identity, frozen evidence sets, richer links.

ALTER TABLE brain_claims
    ADD COLUMN IF NOT EXISTS claim_key TEXT,
    ADD COLUMN IF NOT EXISTS claim_subject TEXT,
    ADD COLUMN IF NOT EXISTS claim_dimension TEXT,
    ADD COLUMN IF NOT EXISTS proposed_status TEXT,
    ADD COLUMN IF NOT EXISTS lifecycle TEXT NOT NULL DEFAULT 'core',
    ADD COLUMN IF NOT EXISTS why_core TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS evidence_set_id TEXT,
    ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS unverified_detail TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS counter_search JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS match_action TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_claims_key
    ON brain_claims (ticker, claim_key)
    WHERE claim_key IS NOT NULL AND lifecycle IS DISTINCT FROM 'closed';

ALTER TABLE brain_claim_versions
    ADD COLUMN IF NOT EXISTS old_statement TEXT,
    ADD COLUMN IF NOT EXISTS new_statement TEXT,
    ADD COLUMN IF NOT EXISTS old_status TEXT,
    ADD COLUMN IF NOT EXISTS new_status TEXT,
    ADD COLUMN IF NOT EXISTS old_confidence TEXT,
    ADD COLUMN IF NOT EXISTS new_confidence TEXT,
    ADD COLUMN IF NOT EXISTS added_counter_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS triggering_document_ids TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE brain_claim_evidence_links
    ADD COLUMN IF NOT EXISTS claim_version_id TEXT,
    ADD COLUMN IF NOT EXISTS source_relationship TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS incomplete BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS brain_evidence_sets (
    evidence_set_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_evidence_sets_ticker
    ON brain_evidence_sets (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_claim_candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL DEFAULT '',
    selected_as_core BOOLEAN NOT NULL DEFAULT FALSE,
    why_core TEXT NOT NULL DEFAULT '',
    why_not_core TEXT NOT NULL DEFAULT '',
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    supporting_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    opposing_evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    missing_evidence TEXT[] NOT NULL DEFAULT '{}',
    claim_id TEXT REFERENCES brain_claims(claim_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_claim_candidates_run
    ON brain_claim_candidates (run_id, selected_as_core DESC);
