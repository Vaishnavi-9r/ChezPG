BEGIN;

ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION NULL;
ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_pgs_coordinates_pair_and_range'
          AND conrelid = 'pgs'::regclass
    ) THEN
        ALTER TABLE pgs
            ADD CONSTRAINT ck_pgs_coordinates_pair_and_range
            CHECK (
                (latitude IS NULL AND longitude IS NULL)
                OR (
                    latitude IS NOT NULL
                    AND longitude IS NOT NULL
                    AND latitude BETWEEN -90 AND 90
                    AND longitude BETWEEN -180 AND 180
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_pgs_city_coordinates
    ON pgs (city_id, latitude, longitude);

CREATE TABLE IF NOT EXISTS nearby_places (
    id SERIAL PRIMARY KEY,
    city_id INTEGER NOT NULL,
    area_id INTEGER NULL,
    name VARCHAR(150) NOT NULL,
    category VARCHAR(30) NOT NULL,
    address VARCHAR(500) NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_nearby_places_city_id_cities
        FOREIGN KEY (city_id) REFERENCES cities (id) ON DELETE CASCADE,
    CONSTRAINT fk_nearby_places_area_id_areas
        FOREIGN KEY (area_id) REFERENCES areas (id) ON DELETE SET NULL,
    CONSTRAINT ck_nearby_places_category CHECK (
        category IN (
            'tech_park',
            'college',
            'university',
            'coaching_center',
            'hospital',
            'metro_station'
        )
    ),
    CONSTRAINT ck_nearby_places_latitude_range
        CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_nearby_places_longitude_range
        CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT uq_nearby_places_city_name_category
        UNIQUE (city_id, name, category)
);

CREATE INDEX IF NOT EXISTS ix_nearby_places_city_category
    ON nearby_places (city_id, category);
CREATE INDEX IF NOT EXISTS ix_nearby_places_area_category
    ON nearby_places (area_id, category);

COMMIT;
