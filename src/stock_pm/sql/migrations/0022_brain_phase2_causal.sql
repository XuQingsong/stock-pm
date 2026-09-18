-- Brain v2 Phase 2: Causal Brain relationship layer. Reuses existing objects.

ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS from_type TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS to_type TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS relationship_type TEXT NOT NULL DEFAULT 'other';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS mechanism TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'positive';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS strength TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS confidence TEXT NOT NULL DEFAULT 'low';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS time_horizon TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS lag TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS conditions TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS support_evidence_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS counter_evidence_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS support_strength INTEGER NOT NULL DEFAULT 0;
ALTER TABLE brain_causal_edges
    ADD COLUMN IF NOT EXISTS counter_strength INTEGER NOT NULL DEFAULT 0;

ALTER TABLE brain_exposures
    ADD COLUMN IF NOT EXISTS subject TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_exposures
    ADD COLUMN IF NOT EXISTS object_name TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_exposures
    ADD COLUMN IF NOT EXISTS mechanism TEXT NOT NULL DEFAULT '';
ALTER TABLE brain_exposures
    ADD COLUMN IF NOT EXISTS related_driver_id TEXT;
ALTER TABLE brain_exposures
    ADD COLUMN IF NOT EXISTS related_claim_id TEXT;
