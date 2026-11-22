BEGIN;

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    recipient_user_id INTEGER NOT NULL,
    type VARCHAR(48) NOT NULL,
    title VARCHAR(160) NOT NULL,
    message TEXT NOT NULL,
    related_entity_type VARCHAR(32) NULL,
    related_entity_id INTEGER NULL,
    dedupe_key VARCHAR(200) NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_notifications_recipient
        FOREIGN KEY (recipient_user_id) REFERENCES owners (id) ON DELETE CASCADE,
    CONSTRAINT uq_notifications_dedupe_key UNIQUE (dedupe_key)
);

CREATE INDEX IF NOT EXISTS ix_notifications_recipient_id
    ON notifications (recipient_user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_read_created
    ON notifications (recipient_user_id, is_read, created_at DESC, id DESC);

COMMIT;
