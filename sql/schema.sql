CREATE TABLE IF NOT EXISTS jobs (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,            -- greenhouse | lever | ashby
    company       TEXT NOT NULL,            -- board slug, e.g. "stripe"
    external_id   TEXT NOT NULL,            -- the job's id at the source
    title         TEXT NOT NULL,
    company_name  TEXT,
    location      TEXT,
    remote        BOOLEAN NOT NULL DEFAULT FALSE,
    url           TEXT,
    description   TEXT,
    posted_at     TIMESTAMPTZ,
    content_hash  TEXT NOT NULL,            -- detects changed content
    dedupe_key    TEXT,                     -- normalized company+title+location (used in Phase 7)
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expired_at    TIMESTAMPTZ,              -- NULL = still active
    embedding     vector(384),              -- NULL = needs embedding
    fts           tsvector GENERATED ALWAYS AS (
                    to_tsvector('english',
                        coalesce(title, '') || ' ' ||
                        coalesce(company_name, '') || ' ' ||
                        coalesce(description, ''))
                  ) STORED,
    UNIQUE (source, company, external_id)
);

CREATE INDEX IF NOT EXISTS jobs_fts_idx ON jobs USING GIN (fts);
CREATE INDEX IF NOT EXISTS jobs_active_idx ON jobs (expired_at);
CREATE INDEX IF NOT EXISTS jobs_dedupe_idx ON jobs (dedupe_key);
CREATE INDEX IF NOT EXISTS jobs_embedding_idx ON jobs USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS users (
    telegram_id    BIGINT PRIMARY KEY,
    username       TEXT,
    profile        JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    kind        TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_user_idx ON events (telegram_id, kind);