-- Brain v2 Phase 0: cognitive foundation. Shadow State, Change Proposals, Causal Edges.

ALTER TABLE brain_research_questions
    ADD COLUMN IF NOT EXISTS related_objects TEXT[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS brain_shadow_states (
    shadow_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    statement TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'low'
        CHECK (confidence IN ('high', 'medium', 'low')),
    materiality_if_true TEXT NOT NULL DEFAULT 'high'
        CHECK (materiality_if_true IN ('high', 'medium', 'low')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'watching', 'confirmed', 'closed')),
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    related_object_ids TEXT[] NOT NULL DEFAULT '{}',
    source_kind TEXT NOT NULL DEFAULT 'signal',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_shadow_states_name
    ON brain_shadow_states (ticker, name);

CREATE INDEX IF NOT EXISTS idx_brain_shadow_states_ticker
    ON brain_shadow_states (ticker, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS brain_change_proposals (
    proposal_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT '',
    object_id TEXT NOT NULL DEFAULT '',
    from_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    to_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    source_kind TEXT NOT NULL DEFAULT 'news',
    decision TEXT NOT NULL DEFAULT 'requires_review'
        CHECK (decision IN ('approve', 'reject', 'requires_review')),
    rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    layer TEXT NOT NULL DEFAULT '',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_change_proposals_ticker
    ON brain_change_proposals (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_brain_change_proposals_decision
    ON brain_change_proposals (ticker, decision, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_causal_edges (
    edge_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    from_node TEXT NOT NULL,
    to_node TEXT NOT NULL,
    statement TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN (
            'candidate', 'observed', 'supported', 'established', 'challenged', 'deprecated'
        )),
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    run_id TEXT REFERENCES brain_runs(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_causal_edges_nodes
    ON brain_causal_edges (ticker, from_node, to_node);

CREATE INDEX IF NOT EXISTS idx_brain_causal_edges_ticker
    ON brain_causal_edges (ticker, status, created_at DESC);
