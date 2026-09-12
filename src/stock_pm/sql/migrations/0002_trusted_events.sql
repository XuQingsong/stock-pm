CREATE TABLE IF NOT EXISTS trusted_events (
    event_id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    countries JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_time TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    dedupe_group TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'updated', 'revoked')),
    freshness TEXT NOT NULL DEFAULT 'fresh',
    severity TEXT NOT NULL DEFAULT 'watch'
        CHECK (severity IN ('info', 'watch', 'high', 'critical')),
    scope TEXT NOT NULL DEFAULT 'market',
    duration TEXT,
    invalidation TEXT,
    coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_trusted_events_type_time
    ON trusted_events (event_type, event_time DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_trusted_events_group
    ON trusted_events (dedupe_group);

CREATE TABLE IF NOT EXISTS trusted_event_sources (
    source_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES trusted_events(event_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_tier INTEGER NOT NULL CHECK (source_tier IN (1, 2, 3, 4)),
    content_type TEXT NOT NULL
        CHECK (content_type IN ('official_fact', 'media_report', 'research_opinion', 'aggregator')),
    fact_or_opinion TEXT NOT NULL CHECK (fact_or_opinion IN ('fact', 'opinion')),
    primary_or_secondary TEXT NOT NULL CHECK (primary_or_secondary IN ('primary', 'secondary')),
    title TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE (canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_trusted_event_sources_event
    ON trusted_event_sources (event_id, source_tier);

CREATE TABLE IF NOT EXISTS trusted_event_claims (
    claim_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES trusted_events(event_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES trusted_event_sources(source_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    polarity TEXT NOT NULL DEFAULT 'supports'
        CHECK (polarity IN ('supports', 'contradicts', 'updates', 'revokes')),
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_trusted_event_claims_event
    ON trusted_event_claims (event_id, polarity);

CREATE TABLE IF NOT EXISTS event_job_cursors (
    provider TEXT PRIMARY KEY,
    last_success TIMESTAMPTZ,
    last_attempt TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'idle',
    reason_code TEXT,
    item_count INTEGER NOT NULL DEFAULT 0
);

INSERT INTO watchlist (symbol, name, primary_exchange, asset_class, sector, themes, rate_sensitivity, active)
VALUES
    ('XOM', 'Exxon Mobil Corp', 'NYSE', 'stocks', '能源', ARRAY['energy', 'oil_producer'], 'low', TRUE),
    ('JPM', 'JPMorgan Chase & Co', 'NYSE', 'stocks', '银行', ARRAY['banks', 'credit'], 'medium', TRUE)
ON CONFLICT (symbol) DO UPDATE SET
    name = EXCLUDED.name,
    active = TRUE;
