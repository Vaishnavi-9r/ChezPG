BEGIN;

ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS legal_name VARCHAR(200) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS identity_document_type VARCHAR(40) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS identity_document_key VARCHAR(100) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS identity_document_media_type VARCHAR(100) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS authority_document_type VARCHAR(40) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS authority_document_key VARCHAR(100) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS authority_document_media_type VARCHAR(100) NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS management_authority_status VARCHAR(24)
        NOT NULL DEFAULT 'pending';
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS identity_reviewer_id INTEGER NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS authority_reviewer_id INTEGER NULL;
ALTER TABLE owner_verifications
    ADD COLUMN IF NOT EXISTS authority_review_notes TEXT NULL;

ALTER TABLE owner_verifications
    DROP CONSTRAINT IF EXISTS ck_owner_verifications_status;
UPDATE owner_verifications
SET verification_status = 'approved'
WHERE verification_status = 'verified';
ALTER TABLE owner_verifications
    ADD CONSTRAINT ck_owner_verifications_status
    CHECK (
        verification_status IN (
            'pending',
            'approved',
            'rejected',
            'needs_resubmission'
        )
    );
ALTER TABLE owner_verifications
    DROP CONSTRAINT IF EXISTS ck_owner_verifications_authority_status;
ALTER TABLE owner_verifications
    ADD CONSTRAINT ck_owner_verifications_authority_status
    CHECK (
        management_authority_status IN (
            'pending',
            'approved',
            'rejected',
            'needs_resubmission'
        )
    );
ALTER TABLE owner_verifications
    DROP CONSTRAINT IF EXISTS fk_owner_verifications_identity_reviewer;
ALTER TABLE owner_verifications
    ADD CONSTRAINT fk_owner_verifications_identity_reviewer
    FOREIGN KEY (identity_reviewer_id) REFERENCES owners (id) ON DELETE SET NULL;
ALTER TABLE owner_verifications
    DROP CONSTRAINT IF EXISTS fk_owner_verifications_authority_reviewer;
ALTER TABLE owner_verifications
    ADD CONSTRAINT fk_owner_verifications_authority_reviewer
    FOREIGN KEY (authority_reviewer_id) REFERENCES owners (id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS owner_verification_audit_events (
    id SERIAL PRIMARY KEY,
    verification_id INTEGER NOT NULL,
    reviewer_owner_id INTEGER NULL,
    verification_type VARCHAR(32) NOT NULL,
    action VARCHAR(24) NOT NULL,
    previous_status VARCHAR(24) NOT NULL,
    new_status VARCHAR(24) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    details JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_owner_verification_audit_verification
        FOREIGN KEY (verification_id)
        REFERENCES owner_verifications (id) ON DELETE CASCADE,
    CONSTRAINT fk_owner_verification_audit_reviewer
        FOREIGN KEY (reviewer_owner_id)
        REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_owner_verification_audit_type
        CHECK (verification_type IN ('identity', 'management_authority')),
    CONSTRAINT ck_owner_verification_audit_action
        CHECK (action IN ('approved', 'rejected', 'needs_resubmission'))
);
CREATE INDEX IF NOT EXISTS ix_owner_verification_audit_verification_created
    ON owner_verification_audit_events (verification_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS pg_review_events (
    id SERIAL PRIMARY KEY,
    pg_id INTEGER NOT NULL,
    reviewer_owner_id INTEGER NULL,
    action VARCHAR(24) NOT NULL,
    previous_status VARCHAR(24) NOT NULL,
    new_status VARCHAR(24) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pg_review_events_pg
        FOREIGN KEY (pg_id) REFERENCES pgs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pg_review_events_reviewer
        FOREIGN KEY (reviewer_owner_id) REFERENCES owners (id) ON DELETE SET NULL,
    CONSTRAINT ck_pg_review_events_action
        CHECK (action IN ('approved', 'rejected', 'needs_resubmission'))
);
CREATE INDEX IF NOT EXISTS ix_pg_review_events_pg_created
    ON pg_review_events (pg_id, created_at DESC, id DESC);

COMMIT;
