from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, Owner


def create_notification(
    db: Session,
    *,
    recipient_user_id: int,
    notification_type: str,
    title: str,
    message: str,
    dedupe_key: str,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> Notification | None:
    existing = db.scalar(
        select(Notification.id).where(Notification.dedupe_key == dedupe_key)
    )
    if existing is not None:
        return None
    notification = Notification(
        recipient_user_id=recipient_user_id,
        type=notification_type,
        title=title,
        message=message,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    db.flush()
    return notification


def notify_admins(
    db: Session,
    *,
    notification_type: str,
    title: str,
    message: str,
    dedupe_key: str,
    related_entity_type: str,
    related_entity_id: int,
) -> int:
    admin_ids = db.scalars(
        select(Owner.id).where(
            Owner.role == "admin",
            Owner.is_active.is_(True),
            Owner.account_status == "active",
        )
    ).all()
    created = 0
    for admin_id in admin_ids:
        notification = create_notification(
            db,
            recipient_user_id=admin_id,
            notification_type=notification_type,
            title=title,
            message=message,
            dedupe_key=f"{dedupe_key}:admin:{admin_id}",
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        created += notification is not None
    return created


def availability_reminder_key(pg_id: int, confirmed_at: datetime | None) -> str:
    confirmation_key = confirmed_at.isoformat() if confirmed_at is not None else "never"
    return f"availability-stale:{pg_id}:{confirmation_key}"
