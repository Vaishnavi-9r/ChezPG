# Nearby places and distance search

## Database migration

ChezPG uses additive SQL migration files. From the project root, apply the
nearby-place schema to the existing PostgreSQL container without resetting the
database:

```powershell
docker cp .\backend\app\db\migrations\005_nearby_places_and_coordinates.sql chezpg-postgres:/tmp/005_nearby_places_and_coordinates.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/005_nearby_places_and_coordinates.sql
```

The migration adds nullable PG coordinates and a `nearby_places` table. Existing
PG rows keep their data and have no coordinates until their owners or
administrators provide them. It does not insert sample or guessed real-world
places.

## API

- `GET /api/v1/nearby-places` supports `city_id`, `area_id`, `category`, `q`,
  `limit`, and `offset`.
- `GET /api/v1/nearby-places/{place_id}` returns one active place.
- `POST /api/v1/admin/nearby-places` creates a place.
- `PATCH /api/v1/admin/nearby-places/{place_id}` updates a place or deactivates
  it with `{"is_active": false}`.

Admin create/edit routes use the existing development `x-admin-key` gate.
Nearby-place coordinates are curated input; provide coordinates only when
verified from a trusted source. Supported categories are `tech_park`, `college`,
`university`, `coaching_center`, `hospital`, and `metro_station`.

PG owners can provide both `latitude` and `longitude` when creating or updating
their listing. Both values are optional, but must be supplied together. Public
search does not return the PG's raw coordinates.

Search example:

```text
GET /api/v1/pgs?nearby_place_id=12&max_distance_km=5&min_rent=8000&stay_type=women
```

`nearby_place_id` must refer to an active nearby place. `max_distance_km` is
optional with a reference ID and required only when applying a radius. Search
calculates straight-line Haversine distances in SQL using a mean Earth radius
of 6371.0088 km. With a radius, PGs without coordinates are excluded. Without a
radius, they can remain in results but their `distance_km` is `null`.

No Google Maps API integration or credential is required. Distances are
straight-line distances, not driving or walking routes.
