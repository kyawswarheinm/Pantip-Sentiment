-- Pantip SET Sentiment — canonical DDL
-- Source of truth for all table definitions. Run migrations/ for schema changes.

CREATE TABLE IF NOT EXISTS tickers (
    ticker          TEXT PRIMARY KEY,
    company_name_th TEXT,
    company_name_en TEXT,
    sector          TEXT,
    market          TEXT,          -- 'SET' or 'mai'
    listed_date     DATE,
    updated_at      DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posts (
    post_id     TEXT PRIMARY KEY,   -- Pantip thread ID (dedup key)
    url         TEXT NOT NULL,
    title_th    TEXT,
    body_th     TEXT,               -- truncated to 2000 chars
    replies     INTEGER DEFAULT 0,
    posted_at   DATETIME,
    scraped_at  DATETIME DEFAULT (datetime('now'))
);

-- Junction table: one post can mention many tickers
CREATE TABLE IF NOT EXISTS post_tickers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id          TEXT NOT NULL REFERENCES posts(post_id),
    ticker           TEXT NOT NULL REFERENCES tickers(ticker),
    match_confidence REAL,          -- 0.0–1.0
    match_method     TEXT           -- 'exact', 'fuzzy', 'alias'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_post_ticker ON post_tickers(post_id, ticker);

CREATE TABLE IF NOT EXISTS scores (
    score_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    post_ticker_id INTEGER NOT NULL REFERENCES post_tickers(id),
    sentiment      REAL NOT NULL,    -- continuous [-1.0, 1.0]
    confidence     REAL NOT NULL,    -- model softmax confidence
    label          TEXT NOT NULL,    -- 'positive', 'neutral', 'negative'
    scored_at      DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prices (
    price_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT NOT NULL REFERENCES tickers(ticker),
    trade_date DATE NOT NULL,
    close_adj  REAL,
    volume     REAL,
    return_1d  REAL,                -- log return vs previous close
    UNIQUE(ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL REFERENCES tickers(ticker),
    rule_type      TEXT NOT NULL,   -- 'zscore' or 'volume_surge'
    trigger_value  REAL,            -- actual Z-score or surge ratio
    threshold_used REAL,            -- threshold at time of firing
    fired_at       DATETIME DEFAULT (datetime('now')),
    resolved       INTEGER DEFAULT 0  -- 0=open, 1=resolved
);

CREATE TABLE IF NOT EXISTS kaggle_exports (
    export_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_slug  TEXT,
    version_note  TEXT,
    exported_at   DATETIME DEFAULT (datetime('now')),
    rows_exported INTEGER
);
