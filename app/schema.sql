CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    is_secret INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cookies (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data_enc TEXT NOT NULL,
    names_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_test_at TEXT,
    last_test_ok INTEGER,
    last_test_message TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
    collection_name TEXT NOT NULL,
    collection_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'failed')),
    stage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    md_count INTEGER,
    error TEXT,
    log_text TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_collection
    ON jobs(collection_id)
    WHERE status IN ('queued', 'running') AND collection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS epubs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    collection_name TEXT NOT NULL,
    title TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    email_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (email_status IN ('pending', 'sent', 'failed', 'skipped')),
    email_attempts INTEGER NOT NULL DEFAULT 0,
    last_email_at TEXT,
    last_email_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_epubs_created ON epubs(created_at DESC);

CREATE TABLE IF NOT EXISTS archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    collection_name TEXT NOT NULL,
    title TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    email_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (email_status IN ('pending', 'sent', 'failed', 'skipped')),
    email_attempts INTEGER NOT NULL DEFAULT 0,
    last_email_at TEXT,
    last_email_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_archives_created ON archives(created_at DESC);
