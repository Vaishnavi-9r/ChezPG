BEGIN;

CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    label VARCHAR(100) NOT NULL,
    sharing_type VARCHAR(24) NOT NULL,
    monthly_rent_per_person NUMERIC(10, 2) NOT NULL,
    total_beds INTEGER NOT NULL,
    occupied_beds INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rooms_pg_id_pgs
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT ck_rooms_total_beds_positive
        CHECK (total_beds > 0),
    CONSTRAINT ck_rooms_occupied_beds_capacity
        CHECK (occupied_beds >= 0 AND occupied_beds <= total_beds),
    CONSTRAINT ck_rooms_rent_nonnegative
        CHECK (monthly_rent_per_person >= 0),
    CONSTRAINT ck_rooms_sharing_type CHECK (
        sharing_type IN (
            'single',
            'double',
            'triple',
            'four_sharing',
            'five_plus_sharing'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_rooms_pg_id ON rooms (pg_id);
CREATE INDEX IF NOT EXISTS ix_rooms_active_sharing_rent
    ON rooms (is_active, sharing_type, monthly_rent_per_person);

CREATE TABLE IF NOT EXISTS room_availability_history (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    room_id INTEGER NOT NULL,
    previous_occupied_beds INTEGER NULL,
    new_occupied_beds INTEGER NOT NULL,
    previous_monthly_rent_per_person NUMERIC(10, 2) NULL,
    new_monthly_rent_per_person NUMERIC(10, 2) NOT NULL,
    actor_owner_id INTEGER NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    change_notes TEXT NULL,
    CONSTRAINT fk_room_history_pg_id_pgs
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_room_history_room_id_rooms
        FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE,
    CONSTRAINT fk_room_history_actor_owner_id_owners
        FOREIGN KEY (actor_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_room_history_previous_occupied_nonnegative
        CHECK (
            previous_occupied_beds IS NULL
            OR previous_occupied_beds >= 0
        ),
    CONSTRAINT ck_room_history_new_occupied_nonnegative
        CHECK (new_occupied_beds >= 0)
);

CREATE INDEX IF NOT EXISTS ix_room_availability_history_pg_id
    ON room_availability_history (pg_id);
CREATE INDEX IF NOT EXISTS ix_room_availability_history_room_id_updated_at
    ON room_availability_history (room_id, updated_at);

COMMIT;
