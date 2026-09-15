-- Sprint 2.5: research source documents + per-ticker backfill observability.
-- Raw filings/transcripts/press live here; Research Pack remains a rebuildable snapshot.

CREATE TABLE IF NOT EXISTS research_source_documents (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    doc_type TEXT NOT NULL
        CHECK (doc_type IN ('transcript', 'filing', 'press_release', 'guidance')),
    source_key TEXT NOT NULL,
    fiscal_period TEXT,
    published_at TIMESTAMPTZ,
    title TEXT NOT NULL DEFAULT '',
    url TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    source_provider TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, doc_type, source_key)
);

CREATE INDEX IF NOT EXISTS idx_research_source_documents_ticker
    ON research_source_documents (ticker, doc_type, published_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS research_data_backfills (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'partial', 'success', 'failed')),
    steps JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    error TEXT,
    workflow_run_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_data_backfills_ticker
    ON research_data_backfills (ticker, started_at DESC);
