ALTER TABLE event_job_cursors
    ADD COLUMN IF NOT EXISTS etag TEXT,
    ADD COLUMN IF NOT EXISTS last_modified TEXT,
    ADD COLUMN IF NOT EXISTS cursor_json JSONB NOT NULL DEFAULT '{}'::jsonb;
