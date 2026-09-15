-- Sprint 3.5: evidence relevance, quality, independence, and confidence calibration.

ALTER TABLE assumption_evidence_links
    ADD COLUMN IF NOT EXISTS relevance TEXT NOT NULL DEFAULT 'indirect';

ALTER TABLE assumption_evidence_links DROP CONSTRAINT IF EXISTS assumption_evidence_links_relevance_check;
ALTER TABLE assumption_evidence_links
    ADD CONSTRAINT assumption_evidence_links_relevance_check
    CHECK (relevance IN ('direct', 'indirect', 'background'));

ALTER TABLE research_evidence
    ADD COLUMN IF NOT EXISTS source_quality TEXT NOT NULL DEFAULT 'secondary';

ALTER TABLE research_evidence DROP CONSTRAINT IF EXISTS research_evidence_source_quality_check;
ALTER TABLE research_evidence
    ADD CONSTRAINT research_evidence_source_quality_check
    CHECK (source_quality IN ('primary', 'high_quality_secondary', 'secondary', 'weak'));

ALTER TABLE research_evidence
    ADD COLUMN IF NOT EXISTS independence_key TEXT NOT NULL DEFAULT '';

ALTER TABLE research_assumption_proposals
    ADD COLUMN IF NOT EXISTS current_confidence NUMERIC;
ALTER TABLE research_assumption_proposals
    ADD COLUMN IF NOT EXISTS confidence_delta NUMERIC;
ALTER TABLE research_assumption_proposals
    ADD COLUMN IF NOT EXISTS reasoning JSONB NOT NULL DEFAULT '{}'::jsonb;
