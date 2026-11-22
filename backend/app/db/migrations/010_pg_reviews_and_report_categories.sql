BEGIN;

CREATE TABLE IF NOT EXISTS pg_user_reviews (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    text TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_user_reviews_pg
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_user_reviews_author
        FOREIGN KEY (author_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT ck_pg_user_reviews_rating
        CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT ck_pg_user_reviews_status
        CHECK (status IN ('pending', 'approved', 'rejected', 'hidden', 'removed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_user_reviews_pg_author
    ON pg_user_reviews (pg_id, author_id);
CREATE INDEX IF NOT EXISTS ix_pg_user_reviews_public
    ON pg_user_reviews (pg_id, status, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS pg_user_review_events (
    id SERIAL PRIMARY KEY,
    review_id INTEGER NOT NULL,
    actor_owner_id INTEGER NULL,
    action VARCHAR(24) NOT NULL,
    previous_status VARCHAR(24) NULL,
    new_status VARCHAR(24) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_user_review_events_review
        FOREIGN KEY (review_id) REFERENCES pg_user_reviews (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_user_review_events_actor
        FOREIGN KEY (actor_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_pg_user_review_events_action
        CHECK (action IN (
            'submitted',
            'edited',
            'author_removed',
            'approved',
            'rejected',
            'hidden',
            'restored'
        ))
);
CREATE INDEX IF NOT EXISTS ix_pg_user_review_events_review_created
    ON pg_user_review_events (review_id, created_at DESC, id DESC);

ALTER TABLE pg_reports
    DROP CONSTRAINT IF EXISTS ck_pg_reports_category;
ALTER TABLE pg_reports
    ADD CONSTRAINT ck_pg_reports_category
    CHECK (category IN (
        'incorrect_price',
        'no_beds_available',
        'incorrect_address',
        'duplicate_listing',
        'misleading_photos',
        'incorrect_details',
        'misleading_photos_or_details',
        'suspected_fraud',
        'other'
    ));

COMMIT;
