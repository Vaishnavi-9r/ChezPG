BEGIN;

CREATE TABLE IF NOT EXISTS owners (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(254) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    relationship_type VARCHAR(32) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    account_status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_owners_email UNIQUE (email),
    CONSTRAINT ck_owners_relationship_type CHECK (
        relationship_type IN (
            'property_owner',
            'pg_operator',
            'property_manager',
            'authorized_representative'
        )
    ),
    CONSTRAINT ck_owners_account_status CHECK (
        account_status IN ('active', 'suspended', 'disabled')
    )
);

CREATE INDEX IF NOT EXISTS ix_owners_email ON owners (email);
CREATE INDEX IF NOT EXISTS ix_owners_phone_number ON owners (phone_number);

CREATE TABLE IF NOT EXISTS owner_verifications (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    submission_notes TEXT NULL,
    review_notes TEXT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_owner_verifications_owner_id UNIQUE (owner_id),
    CONSTRAINT fk_owner_verifications_owner_id_owners
        FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE CASCADE,
    CONSTRAINT ck_owner_verifications_status CHECK (
        verification_status IN ('pending', 'verified', 'rejected')
    )
);

CREATE INDEX IF NOT EXISTS ix_owner_verifications_owner_id
    ON owner_verifications (owner_id);

ALTER TABLE pgs
    ADD COLUMN IF NOT EXISTS owner_id INTEGER NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_pgs_owner_id_owners'
          AND conrelid = 'pgs'::regclass
    ) THEN
        ALTER TABLE pgs
            ADD CONSTRAINT fk_pgs_owner_id_owners
            FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_pgs_owner_id ON pgs (owner_id);

COMMIT;
