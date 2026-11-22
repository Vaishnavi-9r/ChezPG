import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.database import SessionLocal
from app.integrations.photo_storage import LocalPrivatePhotoStorage
from app.models import PGPhoto
from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find or remove unreferenced private photo files."
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete unreferenced files older than 24 hours.",
    )
    args = parser.parse_args()
    storage = LocalPrivatePhotoStorage(settings.photo_storage_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with SessionLocal() as db:
        referenced = set(db.scalars(select(PGPhoto.storage_key)).all())
        orphaned = []
        for key in storage.iter_keys():
            path = storage.get_path(key)
            modified_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            )
            if key not in referenced and modified_at < cutoff:
                orphaned.append(key)

    if args.delete:
        for key in orphaned:
            storage.delete(key)
        operation = "Deleted"
    else:
        operation = "Found"

    print(f"{operation} {len(orphaned)} orphaned photo file(s).")
    if not args.delete:
        print("Dry run only. Re-run with --delete to remove files older than 24 hours.")


if __name__ == "__main__":
    main()
