from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Area, City, Owner, PG
from app.schemas.pg import PGCreate
from app.services.notifications import create_notification, notify_admins


def create_pg_listing(payload: PGCreate, owner: Owner, db: Session) -> PG:
    city = db.get(City, payload.city_id)
    if city is None or not city.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="City not found or inactive",
        )

    area = db.get(Area, payload.area_id)
    if area is None or not area.is_active or area.city_id != payload.city_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected area does not belong to this city or is inactive",
        )

    pg = PG(
        **payload.model_dump(),
        owner_id=owner.id,
        verification_status="pending",
        is_active=False,
    )
    try:
        db.add(pg)
        db.flush()
        create_notification(
            db,
            recipient_user_id=owner.id,
            notification_type="pg_submitted",
            title="PG listing submitted",
            message=f"{pg.name} was submitted for review.",
            dedupe_key=f"pg-submitted:{pg.id}:owner:{owner.id}",
            related_entity_type="pg",
            related_entity_id=pg.id,
        )
        notify_admins(
            db,
            notification_type="pg_submitted_for_review",
            title="PG listing needs review",
            message=f"A new PG listing, {pg.name}, is awaiting review.",
            dedupe_key=f"pg-submitted:{pg.id}",
            related_entity_type="pg",
            related_entity_id=pg.id,
        )
        db.commit()
        db.refresh(pg)
        return pg
    except Exception:
        db.rollback()
        raise
