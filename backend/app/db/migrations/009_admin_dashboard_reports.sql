BEGIN;

ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NULL;
ALTER TABLE pgs
    ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
CREATE INDEX IF NOT EXISTS ix_pgs_created_at
    ON pgs (created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS pg_reports (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    reporter_owner_id INTEGER NULL,
    category VARCHAR(32) NOT NULL,
    details VARCHAR(2000) NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_reports_pg
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_reports_reporter
        FOREIGN KEY (reporter_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_pg_reports_category
        CHECK (category IN (
            'incorrect_price',
            'no_beds_available',
            'incorrect_address',
            'duplicate_listing',
            'misleading_photos_or_details',
            'suspected_fraud'
        )),
    CONSTRAINT ck_pg_reports_status
        CHECK (status IN ('submitted', 'under_review', 'resolved', 'dismissed'))
);
CREATE INDEX IF NOT EXISTS ix_pg_reports_pg_id ON pg_reports (pg_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_reports_open_reporter_listing
    ON pg_reports (pg_id, reporter_owner_id)
    WHERE status IN ('submitted', 'under_review');

CREATE TABLE IF NOT EXISTS pg_report_events (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL,
    reviewer_owner_id INTEGER NULL,
    action VARCHAR(24) NOT NULL,
    previous_status VARCHAR(24) NOT NULL,
    new_status VARCHAR(24) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_report_events_report
        FOREIGN KEY (report_id) REFERENCES pg_reports (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_report_events_reviewer
        FOREIGN KEY (reviewer_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_pg_report_events_action
        CHECK (action IN ('under_review', 'resolved', 'dismissed'))
);
CREATE INDEX IF NOT EXISTS ix_pg_report_events_report_created
    ON pg_report_events (report_id, created_at DESC, id DESC);

COMMIT;
