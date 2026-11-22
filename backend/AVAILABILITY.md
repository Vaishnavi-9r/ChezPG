# Availability confirmation and freshness

Bed counts remain room-based. For each active room, available beds are
`total_beds - occupied_beds`; a PG's displayed totals are calculated from its
active rooms. Owners update available-bed counts per room through
`PATCH /api/v1/owner/pgs/{pg_id}/availability`. Sending a room's current count
does not create a room history record.

The availability status is `full` when active rooms have zero available beds,
`available` when at least one active bed is available, or
`temporarily_unavailable` when the owner has explicitly paused availability.
Setting `full` requires zero available beds; setting `available` requires at
least one. Availability status does not change listing moderation or public
visibility.

`POST /api/v1/owner/pgs/{pg_id}/confirm-availability` is the explicit
confirmation action. It records the current availability confirmation time and
an audit event. Set `confirm_rent: true` to also confirm the listing's rent.
Reads and ordinary inventory changes do not update these confirmation times.
Existing listings receive null confirmation timestamps; no historical date is
fabricated. The public `availability_is_stale` and owner
`availability_needs_update` labels are based on the confirmation timestamp,
not on actual availability or verification status.

`AVAILABILITY_STALE_HOURS` configures the freshness threshold and defaults to
168 hours (7 days). The local `backend\.env` sets it to 168.

## Database migration

Apply the additive migration from the project root using the existing
PostgreSQL container. This adds nullable confirmation columns, a default-false
temporary-unavailability flag, and an audit-event table; it does not drop or
rewrite existing records:

```powershell
Set-Location C:\ChezPG
docker cp .\backend\app\db\migrations\007_pg_availability_confirmation.sql chezpg-postgres:/tmp/007_pg_availability_confirmation.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/007_pg_availability_confirmation.sql
```

The migration intentionally leaves existing confirmation timestamps null.
Room availability history remains in `room_availability_history`; new
PG-level changes and explicit confirmations are recorded in
`pg_availability_events`.

## API examples

All management examples require a bearer token for an active owner of the
listing or an active administrator:

```powershell
$BaseUrl = "http://127.0.0.1:8000/api/v1"
$Headers = @{ Authorization = "Bearer <access-token>" }

Invoke-RestMethod -Uri "$BaseUrl/owner/pgs/1/availability" -Headers $Headers

$Update = @{
    rooms = @(
        @{ room_id = 3; available_beds = 2 },
        @{ room_id = 4; available_beds = 0 }
    )
    availability_status = "available"
} | ConvertTo-Json
Invoke-RestMethod -Method Patch `
    -Uri "$BaseUrl/owner/pgs/1/availability" `
    -Headers $Headers -ContentType "application/json" -Body $Update

$Confirmation = @{ confirm_rent = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post `
    -Uri "$BaseUrl/owner/pgs/1/confirm-availability" `
    -Headers $Headers -ContentType "application/json" -Body $Confirmation

Invoke-RestMethod `
    -Uri "$BaseUrl/owner/pgs/1/availability-history?limit=50&offset=0" `
    -Headers $Headers
```
