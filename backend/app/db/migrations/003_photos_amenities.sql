BEGIN;

CREATE TABLE IF NOT EXISTS amenities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_amenities_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS pg_amenities (
    pg_id INTEGER NOT NULL,
    amenity_id INTEGER NOT NULL,
    PRIMARY KEY (pg_id, amenity_id),
    CONSTRAINT fk_pg_amenities_pg_id_pgs
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_amenities_amenity_id_amenities
        FOREIGN KEY (amenity_id) REFERENCES amenities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_pg_amenities_amenity_id
    ON pg_amenities (amenity_id);

CREATE TABLE IF NOT EXISTS pg_photos (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    storage_key VARCHAR(100) NOT NULL,
    media_type VARCHAR(30) NOT NULL,
    caption VARCHAR(300) NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_cover BOOLEAN NOT NULL DEFAULT FALSE,
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    moderation_notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_pg_photos_storage_key UNIQUE (storage_key),
    CONSTRAINT fk_pg_photos_pg_id_pgs
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT ck_pg_photos_order_nonnegative
        CHECK (display_order >= 0),
    CONSTRAINT ck_pg_photos_review_status
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS ix_pg_photos_pg_id_order
    ON pg_photos (pg_id, display_order, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_photos_one_cover_per_pg
    ON pg_photos (pg_id)
    WHERE is_cover;

INSERT INTO amenities (name, is_active)
VALUES
    ('Wi-Fi', TRUE),
    ('Air conditioning', TRUE),
    ('Attached bathroom', TRUE),
    ('Laundry', TRUE),
    ('Parking', TRUE),
    ('Housekeeping', TRUE),
    ('TV', TRUE),
    ('Washing machine', TRUE)
ON CONFLICT (name) DO NOTHING;

COMMIT;
