# Owner and PG verification

ChezPG keeps these states independent:

- Owner identity review: `pending`, `approved`, `rejected`, or
  `needs_resubmission`.
- Management-authority review: the same independent statuses.
- PG listing review: the PG's existing `pending`, `verified`, or `rejected`
  status. A listing is public only when it is active and approved.
- Availability freshness: an explicit owner confirmation timestamp; freshness
  is not an identity, authority, or listing approval.

Owner login, phone status, and availability updates do not approve any of these
reviews. Public listing search and public PG media additionally require linked
owners to be active and have both identity and management authority approved.
Legacy listings without an associated owner remain subject to the existing
active/PG-approved checks.

## Manual review and endpoints

There is no identity provider, SMS integration, or automated legal-document
verification. Admins manually review owner identity and authority submissions
through the authenticated `/api/v1/admin/owners/{owner_id}/verification`
workflow. PG approval is also admin-only and requires separately approved owner
identity and management authority, plus submitted identity and authority
evidence. Review actions record the reviewer, status transition, timestamp,
and reason without storing document contents in audit events.

Owners submit legal name and relationship-appropriate evidence through
`POST /api/v1/owners/me/verification/submit`. They can access or delete only
their own documents. Admin review/document endpoints require an authenticated
account whose server-side role is `admin`. Document metadata and audit history
are not included in public PG response schemas.

## Admin dashboard and moderation

All `/api/v1/admin/...` endpoints require a bearer token for an active account
whose database role is `admin`. Client-provided roles and IDs never grant
moderation access. An admin account cannot review its own owner verification
or approve its own listing.

`GET /api/v1/admin/dashboard` reports database counts with these definitions:

- Total, active, and inactive listings use all rows in `pgs`; active/inactive
  refer to `is_active`.
- Listing workflow counts use the PG status: `verified` is reported as
  approved; pending, rejected, and `needs_resubmission` are separate counts.
- Owner-review counts include both `pending` and `needs_resubmission` for the
  respective identity or management-authority status.
- Stale availability counts active PGs with no explicit confirmation or a
  confirmation older than `AVAILABILITY_STALE_HOURS` (default 168 hours).
- Zero-bed counts active PGs that have active room inventory and a computed
  available-bed total of zero; PGs with no room inventory are not counted.
- Unreviewed reports count reports still in `submitted` status; `under_review`
  reports are not included.

PG moderation endpoints include:

- `GET /api/v1/admin/pgs` with status, city, area, creation-date, and pagination
  filters; `X-Total-Count`, `X-Limit`, and `X-Offset` report pagination.
- `GET /api/v1/admin/pgs/{pg_id}` for listing and safe verification-evidence
  metadata (never document bytes or storage keys).
- `POST /api/v1/admin/pgs/{pg_id}/approve`,
  `/reject`, and `/request-corrections`. Rejection/correction decisions
  require a reason. The existing `PATCH /api/v1/admin/pgs/{pg_id}/review`
  remains available.
- `GET /api/v1/admin/pgs/{pg_id}/review-history` for protected audit events.
- `GET /api/v1/admin/owners/verification/pending` for paginated pending or
  correction-requested owner submissions, with the same pagination headers.

PG listing dates use the `created_at` column. Migration 009 leaves existing
records with an unknown creation date as `NULL` rather than fabricating one;
new records receive the database timestamp.

### User-submitted PG reports

An authenticated active account can submit
`POST /api/v1/pgs/{pg_id}/reports` for a currently public PG with a supported
category and optional concise details. The reporter ID comes from the signed-in
account, not the request. Listing owners cannot report their own listing, and
one account can have only one open report for a listing at a time (enforced by
a database partial unique index). The API returns only a report receipt; report
details are not added to public listing responses.

Admins can paginate/filter `GET /api/v1/admin/reports`, inspect
`GET /api/v1/admin/reports/{report_id}`, and set report status with
`PATCH /api/v1/admin/reports/{report_id}` using `under_review`, `resolved`, or
`dismissed` plus a required reason. Terminal statuses cannot be reopened.
`GET /api/v1/admin/reports/{report_id}/history` returns reviewer, reason, and
status transitions. There is no IP-based rate-limit service in this project;
report submission therefore requires account authentication and database
deduplication, and should additionally be rate-limited at the API gateway
before public production exposure.

### Reviews and ratings

Authenticated accounts can submit one review per PG with
`POST /api/v1/pgs/{pg_id}/reviews`. Listing owners cannot review their own PG.
Reviews start as `pending`; no stay verification is required or implied.
`GET /api/v1/pgs/{pg_id}/reviews` returns only approved reviews and is
paginated. `PATCH /api/v1/reviews/{review_id}` edits only the authenticated
author's review and returns it to pending moderation; `DELETE` soft-removes
the author's review and keeps its history. A removed review continues to count
against the one-review-per-account-per-PG rule, preserving the audit record and
preventing duplicate/repost abuse.

Admins can filter/paginate `GET /api/v1/admin/reviews`, moderate with
`PATCH /api/v1/admin/reviews/{review_id}` using approve, reject, hide, or
restore plus a required reason, and read protected history at
`GET /api/v1/admin/reviews/{review_id}/history`. Allowed transitions are
pending-to-approved/rejected, approved-to-hidden, and hidden-to-approved.
Admins cannot moderate their own review. Every submission, edit, author
removal, and moderation transition is audited. Public review responses do not
include author IDs or profile information. Review text is treated as text and
HTML-special characters are escaped; clients must still render review text as
text, not as trusted HTML.

Public PG search summaries average and count approved reviews only, with one
batched aggregate query for the current results page. Reviews and ratings do
not affect PG verification, owner verification, or availability freshness.

Changing address, rent, or other material listing fields returns an approved PG
to pending/inactive review and records the changed fields in the PG review
history. Re-submitting owner evidence resets both owner review types to pending;
the public eligibility rule then hides linked listings until both are approved
again.

## Private document storage

The local-development adapter stores files under
`backend/private_verification_uploads` by default, outside FastAPI's public
static routes. Configure `VERIFICATION_STORAGE_DIR` to use another private
directory and `VERIFICATION_MAX_UPLOAD_BYTES` to set the per-file limit
(default 10 MiB). Files are limited to supported images and PDF, validated from
their bytes, and saved using server-generated UUID keys; submitted names and
paths are not used as storage paths. Download responses are private and
non-cacheable. The default directory is excluded from Git.

This local adapter is not replicated/object storage and is intended for local
development or a single host. Before production, use private durable storage,
restrict its access, encrypt backups, and define a retention schedule with
legal/privacy review. Do not retain documents indefinitely by default. The
owner document-deletion route removes the stored file and metadata; confirm
applicable legal, moderation, backup, and audit-retention obligations before
deleting production records or setting automated expiration. No retention
period or external document check is currently configured.

## Additive database migration

Apply migration 008 against the existing database after taking the normal
database backup, from the project root:

```powershell
docker cp .\backend\app\db\migrations\008_owner_authority_and_review_audit.sql chezpg-postgres:/tmp/008_owner_authority_and_review_audit.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/008_owner_authority_and_review_audit.sql
```

The migration adds nullable evidence/reviewer fields, adds management-authority
status and audit tables, and maps legacy owner verification status `verified`
to `approved`. It does not drop tables, delete records, or reset the Docker
volume. Review the migration and retain a backup before applying it. The
database container remains on host port 5433; these commands connect to the
existing container directly.

After migration 008 is applied, apply the new additive admin/report migration
from the project root:

```powershell
docker cp .\backend\app\db\migrations\009_admin_dashboard_reports.sql chezpg-postgres:/tmp/009_admin_dashboard_reports.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/009_admin_dashboard_reports.sql
```

Migration 009 adds the listing creation timestamp (without backfilling unknown
historical dates), report and report-audit tables, status/category constraints,
and indexes. It preserves current listings and other records and does not
recreate the database or Docker volume. Apply it only after confirming migration
008 is already present; both run against the existing database, whose host port
remains 5433.

After migrations 008 and 009 are applied, add reviews and expanded report
categories using migration 010:

```powershell
docker cp .\backend\app\db\migrations\010_pg_reviews_and_report_categories.sql chezpg-postgres:/tmp/010_pg_reviews_and_report_categories.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/010_pg_reviews_and_report_categories.sql
```

Migration 010 creates review and review-audit tables with rating, status, and
one-review constraints, then expands the report category constraint while
preserving existing reports and their values. It is additive and does not drop
tables, delete records, or reset the database volume.
