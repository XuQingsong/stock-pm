-- Sprint 2.5 correction: provenance fields and official document kinds.
-- Distinguishes template seeds from evidence-discovered tasks; stores excerpt + source_type on evidence.

ALTER TABLE research_source_documents DROP CONSTRAINT IF EXISTS research_source_documents_doc_type_check;
ALTER TABLE research_source_documents
    ADD CONSTRAINT research_source_documents_doc_type_check
    CHECK (doc_type IN (
        'transcript',
        'filing',
        'press_release',
        'guidance',
        'earnings_release',
        'exhibit',
        'investor_presentation',
        'prepared_remarks'
    ));

ALTER TABLE research_tasks
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'agent_followup';

ALTER TABLE research_tasks DROP CONSTRAINT IF EXISTS research_tasks_source_type_check;
ALTER TABLE research_tasks
    ADD CONSTRAINT research_tasks_source_type_check
    CHECK (source_type IN (
        'template_seed',
        'evidence_discovered',
        'assumption_gap',
        'agent_followup',
        'pm_request'
    ));

ALTER TABLE research_evidence
    ADD COLUMN IF NOT EXISTS excerpt TEXT NOT NULL DEFAULT '';
ALTER TABLE research_evidence
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT '';

ALTER TABLE research_assumptions
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'template_seed';

ALTER TABLE research_assumptions DROP CONSTRAINT IF EXISTS research_assumptions_source_type_check;
ALTER TABLE research_assumptions
    ADD CONSTRAINT research_assumptions_source_type_check
    CHECK (source_type IN (
        'template_seed',
        'evidence_discovered',
        'assumption_gap',
        'agent_followup',
        'pm_request'
    ));
