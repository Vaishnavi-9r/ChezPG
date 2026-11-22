BEGIN;

CREATE INDEX IF NOT EXISTS ix_pgs_public_rent
    ON pgs (is_active, verification_status, monthly_rent);

CREATE INDEX IF NOT EXISTS ix_pgs_food_electricity
    ON pgs (food_available, electricity_included);

COMMIT;
