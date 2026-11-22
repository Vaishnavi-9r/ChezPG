# In-app notifications

Notifications are persisted for an authenticated account in the `notifications`
table. Their API identity is always derived from the signed-in account; callers
cannot choose a recipient or create arbitrary notifications.

## API

- `GET /api/v1/notifications?limit=20&offset=0` lists the current user's
  notifications newest first, with notification ID as a stable tie-breaker.
  Pagination totals are returned in `X-Total-Count`, `X-Limit`, and
  `X-Offset`.
- `GET /api/v1/notifications/unread-count` returns the current user's unread
  count.
- `PATCH /api/v1/notifications/{notification_id}/read` marks one of that
  user's notifications read; another account's notification is returned as
  not found.
- `POST /api/v1/notifications/read-all` marks all unread notifications for the
  current user read.

## Events currently recorded

- Successful listing submission: confirmation to the owner and review alert
  for active admins.
- PG listing approval, rejection, or correction request: safe status update to
  its owner.
- Owner identity or management-authority approval, rejection, or correction
  request: generic status update to the owner; private document details and
  reviewer notes are excluded.
- New PG report or user review: moderation alert to active admins.
- Report status update: generic status update to the authenticated reporter.
- Review moderation: generic publication/status update to its author.
- Stale availability reminder: owner-only reminder created by the scheduled
  command described below.

Notifications contain no passwords, tokens, private document URLs, identity
document contents, or internal moderation reasons. All event notifications are
created in the same SQL transaction as their triggering listing/review/report
change. A persistence failure aborts that transaction instead of silently
leaving a moderation/listing change without its corresponding notification.

The `dedupe_key` has a unique constraint. Event notifications use the related
review/audit entity identity, so retrying the same persisted event does not
create a second notification. Availability reminder keys include the listing
ID and last-confirmation timestamp (or `never`), so rerunning the command does
not produce repeat reminders until the owner confirms availability again.

## Availability reminder scheduling

There is no scheduler or background loop in the API. Run the reusable
management command daily from the backend directory, or schedule it using
Windows Task Scheduler:

```powershell
Set-Location C:\ChezPG\backend
.\.venv\Scripts\python.exe -m app.services.availability_reminders
```

The command finds active PGs that have no confirmation or whose confirmation
is older than `AVAILABILITY_STALE_HOURS` (default 168), and notifies the linked
active owner account. It does not update availability timestamps or listing
status. Managers are only recipients if they are represented by the listing's
authorized `owner_id`; the current schema has no separate PG-manager grant.

## Migration and delivery

After migrations 008, 009, and 010 are present, back up the existing database
and apply additive migration 011 from the project root:

```powershell
docker cp .\backend\app\db\migrations\011_in_app_notifications.sql chezpg-postgres:/tmp/011_in_app_notifications.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/011_in_app_notifications.sql
```

Migration 011 creates the notification table, a unique idempotency key, and
recipient/read/time indexes. It preserves all existing records and does not
reset the database or Docker volume or change host port 5433.

Only in-app persistence and APIs are implemented. The notification creation
service is deliberately independent of delivery. A future push/email/SMS
integration needs a configured provider, credential management, delivery
retries, and explicit consent/preferences; none is currently configured or
claimed to work.
