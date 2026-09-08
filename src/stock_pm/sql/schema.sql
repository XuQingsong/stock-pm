CREATE TABLE IF NOT EXISTS sync_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'alpaca',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    item_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    contract_id BIGINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    last_price NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    prior_close NUMERIC,
    volume NUMERIC,
    halted BOOLEAN,
    source TEXT NOT NULL DEFAULT 'alpaca',
    raw_data JSONB NOT NULL,
    UNIQUE (symbol, captured_at)
);

ALTER TABLE market_snapshots
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'alpaca';

CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_time
    ON market_snapshots (symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS price_bars (
    symbol TEXT NOT NULL,
    bar_size TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    volume NUMERIC,
    source TEXT NOT NULL DEFAULT 'alpaca',
    raw_data JSONB NOT NULL,
    PRIMARY KEY (symbol, bar_size, bar_time)
);

CREATE INDEX IF NOT EXISTS idx_price_bars_symbol_time
    ON price_bars (symbol, bar_time DESC);

CREATE OR REPLACE VIEW daily_price_bars AS
SELECT DISTINCT ON (symbol, bar_time::date)
       symbol, bar_size, bar_time, open_price, high_price, low_price,
       close_price, volume, source, raw_data
FROM price_bars
WHERE bar_size = '1d'
ORDER BY symbol, bar_time::date, (source LIKE 'alpaca_sip%') DESC,
         (source LIKE 'alpaca%') DESC, bar_time DESC;

CREATE TABLE IF NOT EXISTS position_snapshots (
    captured_at TIMESTAMPTZ NOT NULL,
    contract_id BIGINT NOT NULL,
    symbol TEXT,
    description TEXT,
    asset_class TEXT,
    currency TEXT,
    quantity NUMERIC,
    average_price NUMERIC,
    market_price NUMERIC,
    market_value NUMERIC,
    daily_pnl NUMERIC,
    unrealized_pnl NUMERIC,
    raw_data JSONB NOT NULL,
    PRIMARY KEY (captured_at, contract_id)
);

CREATE INDEX IF NOT EXISTS idx_positions_time
    ON position_snapshots (captured_at DESC);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    symbol TEXT,
    trade_time TIMESTAMPTZ,
    side TEXT,
    quantity NUMERIC,
    price NUMERIC,
    commission NUMERIC,
    realized_pnl NUMERIC,
    currency TEXT,
    exchange TEXT,
    company_name TEXT,
    raw_data JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON trades (symbol, trade_time DESC);

CREATE TABLE IF NOT EXISTS account_snapshots (
    captured_at TIMESTAMPTZ PRIMARY KEY,
    currency TEXT,
    net_liquidation NUMERIC,
    total_cash_value NUMERIC,
    gross_position_value NUMERIC,
    available_funds NUMERIC,
    buying_power NUMERIC,
    maintenance_margin NUMERIC,
    excess_liquidity NUMERIC,
    raw_data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS option_wall_snapshots (
    symbol TEXT NOT NULL,
    expiration_date DATE NOT NULL,
    strike NUMERIC NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    spot_price NUMERIC,
    call_last NUMERIC,
    call_bid NUMERIC,
    call_ask NUMERIC,
    call_volume NUMERIC,
    call_open_interest NUMERIC,
    call_implied_volatility NUMERIC,
    put_last NUMERIC,
    put_bid NUMERIC,
    put_ask NUMERIC,
    put_volume NUMERIC,
    put_open_interest NUMERIC,
    put_implied_volatility NUMERIC,
    raw_data JSONB NOT NULL,
    PRIMARY KEY (symbol, expiration_date, strike, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_option_wall_latest
    ON option_wall_snapshots (symbol, expiration_date, captured_at DESC);

CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT,
    source TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    url TEXT NOT NULL,
    sentiment TEXT CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    synced_at TIMESTAMPTZ NOT NULL,
    raw_data JSONB NOT NULL,
    UNIQUE (symbol, url)
);

CREATE INDEX IF NOT EXISTS idx_news_symbol_time
    ON news_articles (symbol, published_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS fundamentals_snapshots (
    symbol TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    market_cap NUMERIC,
    enterprise_value NUMERIC,
    pe_ttm NUMERIC,
    pe_forward NUMERIC,
    peg_ratio NUMERIC,
    price_to_book NUMERIC,
    price_to_sales NUMERIC,
    ev_to_ebitda NUMERIC,
    eps_ttm NUMERIC,
    revenue_ttm NUMERIC,
    gross_margin_pct NUMERIC,
    operating_margin_pct NUMERIC,
    net_margin_pct NUMERIC,
    revenue_growth_yoy_pct NUMERIC,
    eps_growth_yoy_pct NUMERIC,
    dividend_yield_pct NUMERIC,
    beta NUMERIC,
    analyst_target_price NUMERIC,
    source TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    PRIMARY KEY (symbol, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_symbol_time
    ON fundamentals_snapshots (symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS earnings_reports (
    symbol TEXT NOT NULL,
    report_date DATE NOT NULL,
    report_timing TEXT NOT NULL DEFAULT 'unknown'
        CHECK (report_timing IN ('before_market', 'after_market', 'during_market', 'unknown')),
    fiscal_period TEXT NOT NULL,
    fiscal_year INTEGER,
    period_end DATE,
    currency TEXT NOT NULL DEFAULT 'USD',
    eps_actual NUMERIC,
    eps_estimate NUMERIC,
    eps_surprise_pct NUMERIC,
    revenue_actual NUMERIC,
    revenue_estimate NUMERIC,
    revenue_surprise_pct NUMERIC,
    net_income_actual NUMERIC,
    net_income_estimate NUMERIC,
    net_income_surprise_pct NUMERIC,
    provider_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL,
    raw_data JSONB NOT NULL,
    PRIMARY KEY (symbol, report_date, fiscal_period)
);

CREATE INDEX IF NOT EXISTS idx_earnings_symbol_date
    ON earnings_reports (symbol, report_date DESC);

ALTER TABLE earnings_reports
    ADD COLUMN IF NOT EXISTS net_income_actual NUMERIC,
    ADD COLUMN IF NOT EXISTS net_income_estimate NUMERIC,
    ADD COLUMN IF NOT EXISTS net_income_surprise_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS provider_fields JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS market_events (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'watch', 'high')),
    title TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    unique_key TEXT NOT NULL UNIQUE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_events_time
    ON market_events (event_time DESC, symbol);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    primary_exchange TEXT NOT NULL DEFAULT '',
    asset_class TEXT NOT NULL DEFAULT 'stocks'
        CHECK (asset_class IN ('stocks', 'etf')),
    sector TEXT,
    themes TEXT[] NOT NULL DEFAULT '{}',
    rate_sensitivity TEXT NOT NULL DEFAULT 'medium'
        CHECK (rate_sensitivity IN ('low', 'medium', 'high')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS large_trades (
    symbol TEXT NOT NULL,
    trade_time TIMESTAMPTZ NOT NULL,
    price NUMERIC NOT NULL,
    size NUMERIC NOT NULL,
    notional NUMERIC NOT NULL,
    side_inferred TEXT NOT NULL DEFAULT 'unknown'
        CHECK (side_inferred IN ('buy', 'sell', 'unknown')),
    exchange TEXT,
    trade_id TEXT,
    PRIMARY KEY (symbol, trade_time, price, size)
);

CREATE INDEX IF NOT EXISTS idx_large_trades_symbol_time
    ON large_trades (symbol, trade_time DESC);

CREATE TABLE IF NOT EXISTS intraday_segments (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    seg_no INTEGER NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('up', 'down', 'flat')),
    start_price NUMERIC,
    end_price NUMERIC,
    change_pct NUMERIC,
    volume NUMERIC,
    rel_volume NUMERIC,
    vwap_side TEXT CHECK (vwap_side IN ('above', 'below')),
    large_buy_notional NUMERIC NOT NULL DEFAULT 0,
    large_sell_notional NUMERIC NOT NULL DEFAULT 0,
    large_trade_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, trade_date, seg_no)
);

CREATE INDEX IF NOT EXISTS idx_segments_date
    ON intraday_segments (trade_date DESC, symbol);

CREATE TABLE IF NOT EXISTS macro_events (
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    name TEXT NOT NULL,
    actual NUMERIC,
    consensus NUMERIC,
    prior NUMERIC,
    unit TEXT,
    surprise TEXT NOT NULL DEFAULT 'unknown'
        CHECK (surprise IN ('above', 'below', 'inline', 'cut', 'hold', 'hike', 'unknown')),
    confirmed BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'manual',
    notes TEXT,
    PRIMARY KEY (event_type, event_time)
);

ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS themes TEXT[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS daily_reviews (
    symbol TEXT NOT NULL,
    review_date DATE NOT NULL,
    close_price NUMERIC,
    short_trend TEXT,
    medium_trend TEXT,
    long_trend TEXT,
    support_price NUMERIC,
    resistance_price NUMERIC,
    breakout_status TEXT,
    large_trade_count INTEGER NOT NULL DEFAULT 0,
    unusual_option_count INTEGER NOT NULL DEFAULT 0,
    score NUMERIC,
    summary TEXT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, review_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_reviews_date
    ON daily_reviews (review_date DESC, symbol);

ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS rule_bias TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS watch_low NUMERIC;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS watch_high NUMERIC;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_why TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_outlook TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_bias TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_model TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_status TEXT NOT NULL DEFAULT 'missing_key';
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_context_hash TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_generated_at TIMESTAMPTZ;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS llm_error TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS user_bias TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS user_outlook TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS user_note TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS user_confirmed_at TIMESTAMPTZ;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS outcome_return_pct NUMERIC;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS outcome_volume_ratio NUMERIC;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS outcome_broke_support BOOLEAN;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS outcome_vs_bias TEXT;
ALTER TABLE daily_reviews ADD COLUMN IF NOT EXISTS outcome_bias_source TEXT;

CREATE TABLE IF NOT EXISTS cboe_option_stats (
    trade_date DATE PRIMARY KEY,
    total_volume NUMERIC,
    total_call_volume NUMERIC,
    total_put_volume NUMERIC,
    total_put_call NUMERIC,
    total_call_put NUMERIC,
    buckets JSONB NOT NULL DEFAULT '[]'::jsonb,
    vix_put_call NUMERIC,
    spx_put_call NUMERIC,
    source TEXT NOT NULL DEFAULT 'cboe',
    disclaimer TEXT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Slice A/B: append-only environment snapshots. Never upsert a date away.
CREATE TABLE IF NOT EXISTS environment_snapshots (
    id BIGSERIAL PRIMARY KEY,
    as_of_date DATE NOT NULL,
    scope TEXT NOT NULL DEFAULT 'market'
        CHECK (scope IN ('market', 'symbol')),
    symbol TEXT,
    one_liner TEXT,
    row_thesis TEXT,
    struct JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    publish_state TEXT NOT NULL DEFAULT 'draft'
        CHECK (publish_state IN ('draft', 'published', 'stale', 'missing')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_environment_snapshots_date
    ON environment_snapshots (as_of_date DESC, scope, symbol, created_at DESC);

-- Slice A: severe alerts. History is append-only; hide by resolving, do not delete.
CREATE TABLE IF NOT EXISTS severity_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_key TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'severe')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    symbol TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_severity_alerts_active
    ON severity_alerts (active, severity, created_at DESC);

-- Slice A stub: dedicated job log. sync_runs remains the live Alpaca collector.
CREATE TABLE IF NOT EXISTS job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'partial', 'failed', 'skipped')),
    item_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name_time
    ON job_runs (job_name, started_at DESC);

-- Slice C / knife 3: append-only yesterday tape. Never upsert a date away.
CREATE TABLE IF NOT EXISTS tape_analyses (
    id BIGSERIAL PRIMARY KEY,
    as_of_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    one_liner TEXT,
    conclusion TEXT,
    struct JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    publish_state TEXT NOT NULL DEFAULT 'draft'
        CHECK (publish_state IN ('draft', 'published', 'stale', 'missing')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tape_analyses_symbol_date
    ON tape_analyses (symbol, as_of_date DESC, created_at DESC);

-- Slice C / knife 3: append-only ReviewNote 总结/解释.
CREATE TABLE IF NOT EXISTS review_notes (
    id BIGSERIAL PRIMARY KEY,
    as_of_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    summary TEXT,
    explanation TEXT,
    unexplained BOOLEAN NOT NULL DEFAULT FALSE,
    struct JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    publish_state TEXT NOT NULL DEFAULT 'draft'
        CHECK (publish_state IN ('draft', 'published', 'stale', 'missing')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_notes_symbol_date
    ON review_notes (symbol, as_of_date DESC, created_at DESC);
