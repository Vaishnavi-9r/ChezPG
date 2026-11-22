# ChezPG Mobile

Initial Expo + React Native + TypeScript app for **“Moving Cities? Come Chez Us.”**

## Run locally

From `C:\ChezPG\mobile` in PowerShell:

```powershell
npm install
Copy-Item .env.example .env
# Edit .env and set EXPO_PUBLIC_API_URL for the device running the app.
npm run typecheck
npm test
npx expo start
```

In another PowerShell terminal, start FastAPI from the repository root,
`C:\ChezPG`. The backend package is under `backend`, so `--app-dir backend`
is required when launching from the repository root. Install the backend
requirements into the active environment first:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m uvicorn app.main:app --reload --app-dir backend --host 0.0.0.0 --port 8000
```

The backend must be reachable on the development computer at port 8000. This is separate from
PostgreSQL's Docker host port 5433.

## Backend URL by device

Set `EXPO_PUBLIC_API_URL` in `mobile\.env` (the value is public app configuration, not a secret):

- Android emulator: `http://10.0.2.2:8000/api/v1`
- iOS simulator: `http://localhost:8000/api/v1`
- Physical phone: `http://<computer-LAN-IP>:8000/api/v1`, for example
  `http://192.168.1.25:8000/api/v1`

For a physical device, connect both devices to the same network and allow inbound TCP port 8000
through Windows Firewall. Do not use `localhost` on a phone; it refers to the phone itself. Android
allows cleartext HTTP only in development builds; production Expo config disables it. Use HTTPS
for deployed environments.

Expo reads `EXPO_PUBLIC_*` environment variables at bundle time. Restart Expo after changing `.env`.

## App structure and API coverage

- Expo Router stack: Welcome (`/`), City Selection (`/city-select`), Home (`/home`), and an
  owner-information screen (`/owner`). The owner screen is a transparent placeholder; owner
  registration/login is not part of this first mobile foundation.
- The selected city is kept in app state and persisted locally. The city picker loads
  `GET /api/v1/cities`; Hyderabad is a clearly marked temporary choice if that endpoint fails or
  returns no cities. PG searches are disabled for the temporary choice because it has no verified
  backend city ID.
- PG browsing uses `GET /api/v1/pgs` and supported backend filters: `city_id`, `min_rent`,
  `max_rent`, `stay_type`, and `food_available`. A search term filters the currently fetched
  listings by PG name, area, and address; the backend currently has no PG text-search parameter.
  Nearby-place matching uses `GET /api/v1/nearby-places` with `city_id` and `q`.
- The backend has no public amenity catalog endpoint, so the Amenities filter explains why it
  cannot yet issue a verified amenity filter request. No fake IDs or listing data are supplied.
- City/area and public PG/nearby-place schemas are typed from the existing FastAPI response
  schemas. No authentication or privileged backend credentials are embedded in the mobile app.
