# Development sample PG listings

The development sample seed creates eight clearly fictional Hyderabad PG
records, rooms, and associations to the existing amenity catalog. Sample
identity is stored in a stable marker in each listing description. Re-running
the seed skips marked records and refuses to overwrite a listing with a
colliding name but no marker.

The seed is deliberately restricted to a local `chezpg` PostgreSQL database on
host port `5433`, and requires `APP_ENV=development` in the current PowerShell
session. It does not create owners, reviews, verification documents, photos, or
geographic coordinates. New samples remain `pending` and inactive with no
owner, so public search correctly excludes them until real owners and
administrators complete the verification and review workflows. The seed never
changes the existing `ChezPG Demo Stay`.

To preview the samples in public search for local development only, enable
`DEVELOPMENT_SAMPLE_SEARCH_ENABLED=true` while running the API with
`APP_ENV=development`. Settings validation refuses this mode unless the
configured database is the local `chezpg` PostgreSQL database on port 5433.
The search exception is served only to loopback clients and includes only
ownerless, inactive, pending listings whose name and stable description marker
identify them as development samples.
Responses continue to show their actual `pending` verification status; normal
public listing visibility and all admin approval checks remain unchanged when
the opt-in is disabled.

From `C:\ChezPG\backend`:

```powershell
.\.venv\Scripts\Activate.ps1
$env:APP_ENV = "development"
$env:DEVELOPMENT_SAMPLE_SEARCH_ENABLED = "true"
python -m app.db.seed_dev_pgs
```

Start the backend in that same PowerShell session to display development
samples in public search:

```powershell
python -m uvicorn app.main:app --reload --app-dir . --host 127.0.0.1 --port 8000
```

In the repository-root launch workflow, run these commands from `C:\ChezPG`
instead and use `--app-dir backend`.

The seed reports added versus existing sample counts. Verify development
records with:

```powershell
python -c "from sqlalchemy import create_engine, select; from sqlalchemy.orm import Session; from app.core.config import settings; from app.models import Area, City, PG; e=create_engine(settings.database_url); s=Session(e); rows=s.execute(select(PG.name, Area.name, PG.monthly_rent, PG.stay_type, PG.is_active, PG.verification_status).join(Area, Area.id == PG.area_id).where(PG.description.contains('[chezpg-dev-sample:v1:')).order_by(PG.name)).all(); [print(row) for row in rows]; print('sample count:', len(rows)); s.close(); e.dispose()"
```

With development sample search enabled in the backend process, sample listings
appear with `verification_status: "pending"`. Without that opt-in they remain
hidden from public results.

```powershell
curl.exe "http://localhost:8000/api/v1/pgs"
curl.exe "http://localhost:8000/api/v1/pgs?city_id=1&max_rent=10000"
curl.exe "http://localhost:8000/api/v1/pgs?city_id=1&stay_type=women"
curl.exe "http://localhost:8000/api/v1/pgs?city_id=1&area_id=1"
curl.exe "http://localhost:8000/api/v1/pgs?city_id=1&area_id=1&max_rent=10000&stay_type=men"
```

To try the interactive mobile search screen, complete the proper owner
assignment, document submission, owner review, and admin listing approval
process described in `VERIFICATION.md` and `AUTHENTICATION.md`. Never set
approval or activation fields directly to make sample data public.
