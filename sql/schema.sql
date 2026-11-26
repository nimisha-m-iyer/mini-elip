ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS digest_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_digest_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS matches (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    job_id      BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source      TEXT NOT NULL DEFAULT 'manual',   -- manual | agent | digest
    reason      TEXT,
    shown_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS matches_user_idx ON matches (telegram_id, id DESC);

CREATE TABLE IF NOT EXISTS feedback (
    telegram_id BIGINT NOT NULL,
    job_id      BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    vote        SMALLINT NOT NULL CHECK (vote IN (-1, 1)),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (telegram_id, job_id)
);