BEGIN;

ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS is_temporarily_unavailable BOOLEAN
        NOT NULL DEFAULT FALSE;
ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS availability_confirmed_at TIMESTAMPTZ NULL;
ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS rent_confirmed_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS pg_availability_events (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    event_type VARCHAR(20) NOT NULL,
    previous_available_beds INTEGER NULL,
    new_available_beds INTEGER NOT NULL,
    previous_status VARCHAR(32) NULL,
    new_status VARCHAR(32) NOT NULL,
    actor_owner_id INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_availability_events_pg_id_pgs
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_availability_events_actor_owner_id_owners
        FOREIGN KEY (actor_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_pg_availability_events_type
        CHECK (event_type IN ('updated', 'confirmed')),
    CONSTRAINT ck_pg_availability_events_previous_beds
        CHECK (
            previous_available_beds IS NULL
            OR previous_available_beds >= 0
        ),
    CONSTRAINT ck_pg_availability_events_new_beds
        CHECK (new_available_beds >= 0),
    CONSTRAINT ck_pg_availability_events_previous_status
        CHECK (
            previous_status IS NULL
            OR previous_status IN (
                'available',
                'full',
                'temporarily_unavailable'
            )
        ),
    CONSTRAINT ck_pg_availability_events_new_status
        CHECK (
            new_status IN (
                'available',
                'full',
                'temporarily_unavailable'
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_pg_availability_events_pg_created
    ON pg_availability_events (pg_id, created_at DESC, id DESC);

COMMIT;
