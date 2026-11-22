from datetime import datetime, timezone
from decimal import Decimal
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import require_owner
from app.core.config import settings
from app.db.database import get_db
from app.models import (
    Owner,
    PG,
    PGAvailabilityEvent,
    Room,
    RoomAvailabilityHistory,
)
from app.schemas.room import (
    RoomAvailabilityHistoryOut,
    RoomCreate,
    RoomOut,
    RoomUpdate,
)


router = APIRouter(prefix="/owners/me", tags=["Room Inventory"])


def _is_stale(updated_at: datetime, now: datetime) -> bool:
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (now - updated_at).total_seconds() > (
        settings.availability_stale_hours * 3600
    )


def _room_response(room: Room) -> RoomOut:
    response = RoomOut.model_validate(room)
    return response.model_copy(
        update={"is_stale": _is_stale(room.updated_at, datetime.now(timezone.utc))}
    )


def _owned_pg(
    db: Session,
    owner: Owner,
    pg_id: int,
    *,
    lock: bool = False,
) -> PG:
    statement = select(PG).where(PG.id == pg_id, PG.owner_id == owner.id)
    if lock:
        statement = statement.with_for_update()
    pg = db.scalar(statement)
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return pg


def _owned_room(db: Session, owner: Owner, room_id: int) -> Room:
    pg = db.scalar(
        select(PG)
        .join(Room, PG.id == Room.pg_id)
        .where(Room.id == room_id, PG.owner_id == owner.id)
        .with_for_update()
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    room = db.scalar(
        select(Room)
        .where(Room.id == room_id, Room.pg_id == pg.id)
        .with_for_update()
    )
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    return room


def _pg_available_beds(db: Session, pg_id: int) -> int:
    return int(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(Room.total_beds - Room.occupied_beds),
                    0,
                )
            ).where(Room.pg_id == pg_id, Room.is_active.is_(True))
        )
        or 0
    )


def _pg_status(pg: PG, available_beds: int) -> str:
    if pg.is_temporarily_unavailable:
        return "temporarily_unavailable"
    return "full" if available_beds == 0 else "available"


def _record_pg_availability_event(
    db: Session,
    pg: PG,
    owner: Owner,
    *,
    previous_available: int,
    previous_status: str,
    now: datetime,
) -> None:
    available = _pg_available_beds(db, pg.id)
    new_status = _pg_status(pg, available)
    if available == previous_available and new_status == previous_status:
        return
    db.add(
        PGAvailabilityEvent(
            pg_id=pg.id,
            event_type="updated",
            previous_available_beds=previous_available,
            new_available_beds=available,
            previous_status=previous_status,
            new_status=new_status,
            actor_owner_id=owner.id,
            created_at=now,
        )
    )


def _add_history(
    db: Session,
    room: Room,
    owner: Owner,
    *,
    previous_occupied_beds: int | None,
    previous_rent: Decimal | None,
    updated_at: datetime,
) -> None:
    db.add(
        RoomAvailabilityHistory(
            pg_id=room.pg_id,
            room_id=room.id,
            previous_occupied_beds=previous_occupied_beds,
            new_occupied_beds=room.occupied_beds,
            previous_monthly_rent_per_person=previous_rent,
            new_monthly_rent_per_person=room.monthly_rent_per_person,
            actor_owner_id=owner.id,
            updated_at=updated_at,
        )
    )


@router.post(
    "/pgs/{pg_id}/rooms",
    response_model=RoomOut,
    status_code=status.HTTP_201_CREATED,
)
def create_room(
    pg_id: int,
    payload: RoomCreate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        pg = _owned_pg(db, owner, pg_id, lock=True)
        previous_available = _pg_available_beds(db, pg.id)
        previous_status = _pg_status(pg, previous_available)
        now = datetime.now(timezone.utc)
        room = Room(
            pg_id=pg_id,
            label=payload.label,
            sharing_type=payload.sharing_type,
            monthly_rent_per_person=payload.monthly_rent_per_person,
            total_beds=payload.total_beds,
            occupied_beds=payload.occupied_beds,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(room)
        db.flush()
        _add_history(
            db,
            room,
            owner,
            previous_occupied_beds=None,
            previous_rent=None,
            updated_at=now,
        )
        _record_pg_availability_event(
            db,
            pg,
            owner,
            previous_available=previous_available,
            previous_status=previous_status,
            now=now,
        )
        db.commit()
        db.refresh(room)
        return _room_response(room)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get(
    "/pgs/{pg_id}/rooms",
    response_model=list[RoomOut],
)
def list_rooms(
    pg_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owned_pg(db, owner, pg_id)
    rooms = db.scalars(
        select(Room).where(Room.pg_id == pg_id).order_by(Room.id)
    ).all()
    return [_room_response(room) for room in rooms]


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomOut,
)
def update_room(
    room_id: int,
    payload: RoomUpdate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        room = _owned_room(db, owner, room_id)
        pg = db.get(PG, room.pg_id)
        previous_available = _pg_available_beds(db, pg.id)
        previous_status = _pg_status(pg, previous_available)
        changes = payload.model_dump(exclude_unset=True)
        new_total_beds = changes.get("total_beds", room.total_beds)
        new_occupied_beds = changes.get("occupied_beds", room.occupied_beds)
        if new_occupied_beds > new_total_beds:
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail="Occupied beds cannot exceed total beds",
            )

        previous_occupied_beds = room.occupied_beds
        previous_rent = room.monthly_rent_per_person
        for field_name, value in changes.items():
            setattr(room, field_name, value)
        now = datetime.now(timezone.utc)
        room.updated_at = now
        if (
            previous_occupied_beds != room.occupied_beds
            or previous_rent != room.monthly_rent_per_person
        ):
            _add_history(
                db,
                room,
                owner,
                previous_occupied_beds=previous_occupied_beds,
                previous_rent=previous_rent,
                updated_at=now,
            )
        _record_pg_availability_event(
            db,
            pg,
            owner,
            previous_available=previous_available,
            previous_status=previous_status,
            now=now,
        )
        db.commit()
        db.refresh(room)
        return _room_response(room)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room inventory changed concurrently; reload and retry",
        ) from None
    except Exception:
        db.rollback()
        raise


@router.get(
    "/rooms/{room_id}/availability-history",
    response_model=list[RoomAvailabilityHistoryOut],
)
def get_room_availability_history(
    room_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    room = db.scalar(
        select(Room)
        .join(PG, PG.id == Room.pg_id)
        .where(Room.id == room_id, PG.owner_id == owner.id)
    )
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    return db.scalars(
        select(RoomAvailabilityHistory)
        .where(RoomAvailabilityHistory.room_id == room_id)
        .order_by(
            RoomAvailabilityHistory.updated_at.desc(),
            RoomAvailabilityHistory.id.desc(),
        )
    ).all()
