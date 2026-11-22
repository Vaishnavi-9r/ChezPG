BEGIN;

ALTER TABLE owners
    ALTER COLUMN email DROP NOT NULL;
ALTER TABLE owners
    ALTER COLUMN relationship_type DROP NOT NULL;

ALTER TABLE owners
    ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'owner';
ALTER TABLE owners
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
ALTER TABLE owners
    ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE owners
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

UPDATE owners
SET is_active = (account_status = 'active')
WHERE is_active IS NULL;

ALTER TABLE owners
    ALTER COLUMN is_active SET DEFAULT TRUE;
ALTER TABLE owners
    ALTER COLUMN is_active SET NOT NULL;

CREATE TEMPORARY TABLE normalized_owner_phones
ON COMMIT DROP
AS
WITH digit_values AS (
    SELECT
        id,
        regexp_replace(phone_number, '[^0-9]', '', 'g') AS digits
    FROM owners
),
country_values AS (
    SELECT
        id,
        CASE
            WHEN digits LIKE '00%' THEN substring(digits FROM 3)
            ELSE digits
        END AS digits
    FROM digit_values
)
SELECT id, '+' || digits AS phone_number
FROM country_values;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM normalized_owner_phones
        WHERE length(phone_number) NOT BETWEEN 8 AND 16
           OR substring(phone_number FROM 2 FOR 1) NOT BETWEEN '1' AND '9'
    ) THEN
        RAISE EXCEPTION
            'Owner phone data contains values that cannot be normalized to international format';
    END IF;

    IF EXISTS (
        SELECT phone_number
        FROM normalized_owner_phones
        GROUP BY phone_number
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Normalizing owner phone numbers would create duplicates; resolve duplicates before retrying migration 006';
    END IF;
END
$$;

UPDATE owners AS owner
SET phone_number = normalized.phone_number
FROM normalized_owner_phones AS normalized
WHERE owner.id = normalized.id
  AND owner.phone_number <> normalized.phone_number;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_owners_role'
          AND conrelid = 'owners'::regclass
    ) THEN
        ALTER TABLE owners
            ADD CONSTRAINT ck_owners_role
            CHECK (role IN ('owner', 'admin', 'user'));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_owners_phone_e164'
          AND conrelid = 'owners'::regclass
    ) THEN
        ALTER TABLE owners
            ADD CONSTRAINT ck_owners_phone_e164
            CHECK (phone_number ~ '^[+][1-9][0-9]{6,14}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_owners_token_version_nonnegative'
          AND conrelid = 'owners'::regclass
    ) THEN
        ALTER TABLE owners
            ADD CONSTRAINT ck_owners_token_version_nonnegative
            CHECK (token_version >= 0);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_owners_phone_number
    ON owners (phone_number);

COMMIT;
