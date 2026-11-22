# Room inventory and availability

Owners manage room inventory through their authenticated account. A room's
available-bed count is calculated as `total_beds - occupied_beds`; it is not
stored independently. PostgreSQL check constraints enforce positive capacity,
non-negative rent, supported sharing types, and occupied beds within capacity.

Each room creation and successful update writes an availability-history row in
the same transaction as the room change. Updates lock the room and its PG row
before validating and saving, so concurrent writes serialize on PostgreSQL.
The database capacity check is an additional safeguard.

Public PG search returns only active, verified PGs. It includes active room
inventory and calculated available beds. Availability is owner-reported, not
real-time. `AVAILABILITY_STALE_HOURS` controls the stale threshold (default 24);
stale inventory is flagged in responses, not removed. Search can restrict
results to rooms updated within a requested number of hours.

The additive migration is `backend/app/db/migrations/002_room_inventory.sql`.
Existing PG rows are not changed. Apply it after the owner migration has been
applied.
