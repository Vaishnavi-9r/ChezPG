from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Owner, PG
from app.services.notifications import availability_reminder_key, create_notification


def create_stale_availability_reminders(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    stale_before = current_time - timedelta(hours=settings.availability_stale_hours)
    listings = db.execute(
        select(PG.id, PG.owner_id, PG.name, PG.availability_confirmed_at)
        .join(Owner, Owner.id == PG.owner_id)
        .where(
            PG.is_active.is_(True),
            Owner.role == "owner",
            Owner.is_active.is_(True),
            Owner.account_status == "active",
            or_(
                PG.availability_confirmed_at.is_(None),
                PG.availability_confirmed_at < stale_before,
            ),
        )
        .order_by(PG.id)
    ).all()

    created = 0
    for pg_id, owner_id, pg_name, confirmed_at in listings:
        dedupe_key = availability_reminder_key(pg_id, confirmed_at)
        notification = create_notification(
            db,
            recipient_user_id=owner_id,
            notification_type="availability_stale",
            title="Confirm PG availability",
            message=(
                f"Availability for {pg_name} needs reconfirmation. "
                "Review the current beds and confirm availability."
            ),
            dedupe_key=dedupe_key,
            related_entity_type="pg",
            related_entity_id=pg_id,
        )
        created += notification is not None
    return created


def main() -> None:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        created = create_stale_availability_reminders(db)
        db.commit()
        print(f"Created {created} stale-availability reminder(s).")


if __name__ == "__main__":
    main()
