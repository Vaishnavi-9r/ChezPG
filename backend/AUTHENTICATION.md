# Account authentication and authorization

## Authentication

ChezPG uses the existing `owners` table as its account table. Passwords are
hashed with `pwdlib` Argon2; passwords and access tokens are never returned in
account profiles. Phone numbers are normalized to `+` followed by 7-15 digits.
Provide the country calling code explicitly, for example `+919876543210`.
Formatting spaces, parentheses, and hyphens are ignored.

The access token signing secret is `OWNER_TOKEN_SECRET` in `backend\.env` and
must contain at least 32 characters. `ACCESS_TOKEN_EXPIRY_MINUTES` configures
the expiry (default 30; allowed range 1-1440). Password changes increment the
account token version, invalidating previously issued tokens.

Phone authentication does not verify control of the phone number. New accounts
have `phone_verified=false`; no SMS/OTP provider is integrated. Owner identity
review and PG listing review remain independent from login and phone status.

## Endpoints

- `POST /api/v1/auth/register`: accepts `account_type` `owner` or `user`.
  Owners must provide `relationship_type`. Role, active state, phone verification,
  and owner verification cannot be supplied by the client.
- `POST /api/v1/auth/login`: phone number and password; returns a short-lived
  bearer token with a generic invalid-credentials response.
- `GET /api/v1/auth/me`: safe profile for the authenticated account.
- `POST /api/v1/auth/change-password`: verifies the current password and
  revokes existing tokens after a successful change.
- Existing `/api/v1/owners/register`, `/login`, and `/me` routes remain for
  compatibility. The old owner login route accepts email; new integrations
  should use phone-based `/auth/login`.

PG creation/editing, room inventory, owner verification submission, photo
management, and amenity management use the existing owner dependency. It now
requires an active account with the server-assigned `owner` role and checks
listing ownership. Admin APIs require an active account with the server-side
`admin` role. Public registration accepts neither `admin` nor arbitrary role
values.

## Existing records and migration

From the project root, run the additive migration against the existing
container/database:

```powershell
docker cp .\backend\app\db\migrations\006_account_roles_and_phone_auth.sql chezpg-postgres:/tmp/006_account_roles_and_phone_auth.sql
docker exec chezpg-postgres psql -U chezpg -d chezpg -v ON_ERROR_STOP=1 -f /tmp/006_account_roles_and_phone_auth.sql
```

The migration does not drop accounts or listings. It normalizes existing phone
numbers and aborts transactionally if a number is malformed or normalization
would produce duplicates. Review and resolve such entries before retrying.
Existing owner records retain the `owner` role by default. Existing PG records
with a null `owner_id` are deliberately not assigned automatically; register
the responsible owner, confirm ownership out of band, and associate only the
confirmed listing:

```sql
UPDATE pgs SET owner_id = <confirmed_owner_id> WHERE id = <confirmed_pg_id> AND owner_id IS NULL;
```

No administrator is created by migration or public API. To promote an already
verified, controlled account through a trusted DBA connection:

```sql
UPDATE owners SET role = 'admin' WHERE id = <reviewed_account_id>;
```

Never expose database administrator credentials in the application or client.
The former `ADMIN_API_KEY` shared-key gate is not accepted for admin APIs;
administrator routes now require bearer authentication for a database account
whose role is `admin`.

## Deployment notes

Browser development is allowed from `http://localhost:8081` and
`http://127.0.0.1:8081` for the Expo web app. Configure additional trusted
origins with `CORS_ORIGINS` in `backend\.env` as a JSON array, for example:
`CORS_ORIGINS=["https://app.example.com"]`. Do not use wildcard origins with
credentials. Native mobile requests do not use browser CORS. The app has no
shared rate-limiting backend. Apply login and registration limits at a reverse
proxy/API gateway before internet exposure rather than relying on process-local
limits that fail across workers.
