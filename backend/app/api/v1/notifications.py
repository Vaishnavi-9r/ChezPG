from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_authenticated_account
from app.db.database import get_db
from app.models import Notification, Owner
from app.schemas.notification import (
    NotificationOut,
    NotificationReadAllOut,
    NotificationUnreadCountOut,
)


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    recipient: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    base = select(Notification).where(
        Notification.recipient_user_id == recipient.id
    )
    total = db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return db.scalars(
        base.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/unread-count", response_model=NotificationUnreadCountOut)
def get_unread_notification_count(
    recipient: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_user_id == recipient.id,
            Notification.is_read.is_(False),
        )
    ) or 0
    return NotificationUnreadCountOut(unread_count=count)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: int,
    recipient: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == recipient.id,
        )
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/read-all", response_model=NotificationReadAllOut)
def mark_all_notifications_read(
    recipient: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Notification)
        .where(
            Notification.recipient_user_id == recipient.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=now)
    )
    db.commit()
    return NotificationReadAllOut(updated_count=result.rowcount or 0)
