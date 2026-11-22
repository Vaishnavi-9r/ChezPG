# PG photos and amenities

## Storage configuration

The development adapter stores photo bytes outside the FastAPI static tree. By
default, its root is `backend/private_uploads`, resolved from `config.py` rather
than the current working directory. The directory is ignored by Git.

Optional `.env` settings:

```dotenv
PHOTO_STORAGE_DIR=C:\ChezPG\backend\private_uploads
PHOTO_MAX_UPLOAD_BYTES=10485760
PHOTO_MAX_PER_PG=10
```

The upload path accepts JPEG, PNG, and WebP image content, checks the decoded
image format and dimensions, and generates the storage key itself. It does not
trust the submitted filename or MIME type. Public API responses contain
controlled API URLs, never local paths or storage keys.

`PhotoStorage` is the storage boundary for replacing the development filesystem
adapter with private object storage. Do not mount `private_uploads` as a public
static directory. Failed DB writes attempt to remove their newly written file.
To find abandoned files older than 24 hours, from `backend` run:

```powershell
.\.venv\Scripts\python.exe -m app.db.cleanup_photo_storage
```

This defaults to a dry run. Add `--delete` only after reviewing the count to
remove unreferenced files older than 24 hours.

## Database migration

The project uses additive SQL migrations rather than Alembic. After the
PostgreSQL container is running, from `backend`:

```powershell
docker cp .\app\db\migrations\003_photos_amenities.sql chezpg-postgres:/tmp/003_photos_amenities.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/003_photos_amenities.sql
```

The migration creates the amenity catalog, PG association table, and photo
metadata table. It seeds the initial catalog idempotently and does not drop or
replace existing data.

## API surface

- `GET /api/v1/amenities` lists active catalog entries.
- `GET /api/v1/pgs/{pg_id}/media` returns approved photos and active amenities
  for a public, active, verified PG.
- `PUT /api/v1/owners/me/pgs/{pg_id}/amenities` replaces an owner's amenity
  associations with `{"amenity_ids":[1,2]}`.
- `POST /api/v1/owners/me/pgs/{pg_id}/photos` accepts multipart `file` and
  optional `caption` fields. Owners need a bearer token.
- Owner photo routes under `/api/v1/owners/me/...` list, reorder, caption,
  choose an approved cover, and remove photos. A photo is not public until an
  administrator approves it and its PG is itself public.
- `GET /api/v1/admin/photos/pending` lists pending reviews;
  `PATCH /api/v1/admin/photos/{photo_id}/review` accepts
  `{"action":"approve"}` or `{"action":"reject"}`. These routes and reviewer-only
  content require the existing `x-admin-key` header.

## Deployment limitations

The filesystem adapter is for local development and a single application host;
it is not shared or replicated storage. The existing shared admin API key is a
development gate, not production-grade administrator authentication. Before
production, configure private durable object storage, secure administrator
identity/authorization, transport and rate limits for uploads, backups, and a
retention/deletion policy for user-submitted images.
