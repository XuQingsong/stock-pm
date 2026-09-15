-- Sprint 1 close-out: unify research_valuations; links gain strength/reason/contextual.
-- Idempotent for databases that already applied the original 0004.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'valuations'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'research_valuations'
    ) THEN
        ALTER TABLE valuations RENAME TO research_valuations;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'valuations_cases_present'
          AND conrelid = 'public.research_valuations'::regclass
    ) THEN
        ALTER TABLE research_valuations
            RENAME CONSTRAINT valuations_cases_present TO research_valuations_cases_present;
    END IF;
EXCEPTION
    WHEN undefined_table THEN
        NULL;
END
$$;

ALTER INDEX IF EXISTS idx_valuations_ticker RENAME TO idx_research_valuations_ticker;

ALTER TABLE assumption_evidence_links
    ADD COLUMN IF NOT EXISTS strength TEXT NOT NULL DEFAULT 'moderate';

ALTER TABLE assumption_evidence_links
    ADD COLUMN IF NOT EXISTS reason TEXT;

ALTER TABLE assumption_evidence_links
    DROP CONSTRAINT IF EXISTS assumption_evidence_links_direction_check;

ALTER TABLE assumption_evidence_links
    ADD CONSTRAINT assumption_evidence_links_direction_check
        CHECK (direction IN ('support', 'oppose', 'contextual'));

ALTER TABLE assumption_evidence_links
    DROP CONSTRAINT IF EXISTS assumption_evidence_links_strength_check;

ALTER TABLE assumption_evidence_links
    ADD CONSTRAINT assumption_evidence_links_strength_check
        CHECK (strength IN ('strong', 'moderate', 'weak'));
