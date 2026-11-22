from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import warnings

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_authenticated_account, require_owner
from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    verify_password,
)
from app.db.database import get_db
from app.models import (
    Area,
    City,
    Owner,
    OwnerVerificationAuditEvent,
    OwnerVerification,
    PG,
    PGReviewEvent,
    PGAvailabilityEvent,
    Room,
    RoomAvailabilityHistory,
)
from app.schemas.availability import (
    PGAvailabilityConfirmation,
    PGAvailabilityEventOut,
    PGAvailabilityOut,
    PGAvailabilityUpdate,
)
from app.schemas.owner import (
    OwnerLoginRequest,
    OwnerOut,
    OwnerPGUpdate,
    OwnerRegistration,
    OwnerTokenOut,
    OwnerVerificationOut,
    OwnerVerificationSubmission,
    OwnerVerificationDocumentSubmission,
)
from app.schemas.owner import OwnerVerificationDocumentSubmission
from app.schemas.owner_admin import OwnerVerificationDocumentMetadataOut
from app.schemas.pg import PGCreate, PGOut
from app.schemas.owner_dashboard import OwnerDashboardOut, OwnerPGOut
from app.services.accounts import owner_response, register_account
from app.services.owner_listings import create_pg_listing
from app.integrations.verification_storage import (
    LocalPrivateVerificationStorage,
    VerificationStorage,
)


router = APIRouter(prefix="/owners", tags=["Owners"])
management_router = APIRouter(prefix="/owner", tags=["Owner Dashboard"])
verification_storage: VerificationStorage = LocalPrivateVerificationStorage(
    settings.verification_storage_dir
)
_VERIFICATION_IMAGE_TYPES = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
_VERIFICATION_DOCUMENT_TYPES = {
    "application/pdf": ("pdf", "application/pdf"),
    "image/jpeg": ("jpg", "image/jpeg"),
    "image/png": ("png", "image/png"),
    "image/webp": ("webp", "image/webp"),
}
_VERIFICATION_IMAGE_MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = _VERIFICATION_IMAGE_MAX_PIXELS


def _validate_verification_document(content: bytes) -> tuple[str, str]:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Verification document is empty",
        )
    if content.startswith(b"%PDF-") and b"%%EOF" in content[-2048:]:
        return "pdf", "application/pdf"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                if image_format not in _VERIFICATION_IMAGE_TYPES:
                    raise ValueError("Unsupported image type")
                if image.width * image.height > _VERIFICATION_IMAGE_MAX_PIXELS:
                    raise ValueError("Image too large")
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document must contain a valid PDF, JPEG, PNG, or WebP file",
        ) from None
    extension, media_type = _VERIFICATION_IMAGE_TYPES[image_format]
    return extension, media_type


async def _read_verification_upload(upload: UploadFile) -> tuple[bytes, str, str]:
    content = bytearray()
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > settings.verification_max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Verification document exceeds the configured size limit",
            )
    extension, media_type = _validate_verification_document(bytes(content))
    return bytes(content), extension, media_type


def _verification_document_response(
    storage_key: str | None,
    media_type: str | None,
    document_kind: str,
) -> FileResponse:
    if storage_key is None or media_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        )
    try:
        path = verification_storage.get_path(storage_key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        ) from None
    extension = _VERIFICATION_DOCUMENT_TYPES[media_type][0]
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{document_kind}-verification.{extension}",
        headers={"Cache-Control": "private, no-store"},
    )


def _room_summary():
    return (
        select(
            Room.pg_id.label("pg_id"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Room.is_active.is_(True),
                            Room.total_beds - Room.occupied_beds,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("available_beds"),
            func.coalesce(
                func.sum(
                    case(
                        (Room.is_active.is_(True), Room.total_beds),
                        else_=0,
                    )
                ),
                0,
            ).label("total_beds"),
            func.max(
                case(
                    (Room.is_active.is_(True), Room.updated_at),
                    else_=None,
                )
            ).label("availability_updated_at"),
        )
        .group_by(Room.pg_id)
        .subquery()
    )


def _owner_pg_statement(owner_id: int):
    room_summary = _room_summary()
    return (
        select(
            PG,
            Area.name.label("area_name"),
            func.coalesce(room_summary.c.available_beds, 0).label(
                "available_beds"
            ),
            room_summary.c.availability_updated_at,
            func.coalesce(room_summary.c.total_beds, 0).label("total_beds"),
            PG.availability_confirmed_at,
            PG.is_temporarily_unavailable,
        )
        .join(Area, Area.id == PG.area_id)
        .outerjoin(room_summary, room_summary.c.pg_id == PG.id)
        .where(PG.owner_id == owner_id)
    )


def _owner_pg_response(row) -> OwnerPGOut:
    (
        pg,
        area_name,
        available_beds,
        availability_updated_at,
        total_beds,
        availability_confirmed_at,
        is_temporarily_unavailable,
    ) = row
    now = datetime.now(timezone.utc)
    confirmed_at = availability_confirmed_at
    if confirmed_at is not None and confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
    stale_cutoff = now - timedelta(hours=settings.availability_stale_hours)
    availability_status = (
        "temporarily_unavailable"
        if is_temporarily_unavailable
        else "full"
        if available_beds == 0
        else "available"
    )
    return OwnerPGOut.model_validate(
        {
            **{
                field_name: getattr(pg, field_name)
                for field_name in PGOut.model_fields
            },
            "area_name": area_name,
            "is_active": pg.is_active,
            "total_available_beds": int(available_beds),
            "total_beds": int(total_beds),
            "availability_status": availability_status,
            "availability_updated_at": availability_updated_at,
            "availability_confirmed_at": availability_confirmed_at,
            "availability_is_stale": (
                confirmed_at is None or confirmed_at < stale_cutoff
            ),
        }
    )


def _get_owned_pg(pg_id: int, owner: Owner, db: Session):
    row = db.execute(
        _owner_pg_statement(owner.id).where(PG.id == pg_id)
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return row


def _save_owner_pg_update(
    pg: PG,
    payload: OwnerPGUpdate,
    db: Session,
) -> PG:
    changes = payload.model_dump(exclude_unset=True)
    if "city_id" in changes:
        city = db.get(City, changes["city_id"])
        area = db.get(Area, changes["area_id"])
        if city is None or not city.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="City not found or inactive",
            )
        if area is None or not area.is_active or area.city_id != city.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected area does not belong to this city or is inactive",
            )

    previous_status = pg.verification_status
    review_details = {}
    for field_name, value in changes.items():
        old_value = getattr(pg, field_name)
        if isinstance(old_value, Decimal):
            old_value = str(old_value)
        if isinstance(value, Decimal):
            value = str(value)
        review_details[field_name] = {"previous": old_value, "new": value}
        setattr(pg, field_name, value)
    pg.verification_status = "pending"
    pg.is_active = False
    if changes:
        db.add(
            PGReviewEvent(
                pg_id=pg.id,
                reviewer_owner_id=None,
                action="needs_resubmission",
                previous_status=previous_status,
                new_status="pending",
                reason="Owner changed listing details; administrator re-review required",
                details=review_details,
                created_at=datetime.now(timezone.utc),
            )
        )

    try:
        db.commit()
        db.refresh(pg)
        return pg
    except Exception:
        db.rollback()
        raise


@management_router.get(
    "/dashboard",
    response_model=OwnerDashboardOut,
    summary="Get the authenticated owner's listing dashboard",
)
def get_owner_dashboard(
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    room_summary = _room_summary()
    available_beds = func.coalesce(room_summary.c.available_beds, 0)
    stale_before = datetime.now(timezone.utc) - timedelta(
        hours=settings.availability_stale_hours
    )
    is_full = (available_beds == 0) & PG.is_temporarily_unavailable.is_(False)
    has_available_beds = (available_beds > 0) & PG.is_temporarily_unavailable.is_(
        False
    )
    counts = db.execute(
        select(
            func.count(PG.id),
            func.coalesce(
                func.sum(case((PG.is_active.is_(True), 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((PG.verification_status == "pending", 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((PG.verification_status == "verified", 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((PG.verification_status == "rejected", 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (PG.availability_confirmed_at.is_(None))
                            | (PG.availability_confirmed_at < stale_before),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((available_beds == 0, 1), else_=0)),
                0,
            ),
            func.coalesce(func.sum(case((is_full, 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((has_available_beds, 1), else_=0)),
                0,
            ),
        )
        .select_from(PG)
        .outerjoin(room_summary, room_summary.c.pg_id == PG.id)
        .where(PG.owner_id == owner.id)
    ).one()
    return OwnerDashboardOut(
        total_listings=int(counts[0]),
        active_listings=int(counts[1]),
        pending_verification=int(counts[2]),
        approved_listings=int(counts[3]),
        rejected_listings=int(counts[4]),
        needs_availability_update=int(counts[5]),
        zero_available_beds=int(counts[6]),
        full_listings=int(counts[7]),
        listings_with_available_beds=int(counts[8]),
    )


def _availability_counts(db: Session, pg_id: int) -> tuple[int, int, datetime | None]:
    row = db.execute(
        select(
            func.coalesce(func.sum(Room.total_beds), 0),
            func.coalesce(
                func.sum(Room.total_beds - Room.occupied_beds),
                0,
            ),
            func.max(Room.updated_at),
        ).where(Room.pg_id == pg_id, Room.is_active.is_(True))
    ).one()
    return int(row[0]), int(row[1]), row[2]


def _availability_status(pg: PG, available_beds: int) -> str:
    if pg.is_temporarily_unavailable:
        return "temporarily_unavailable"
    return "full" if available_beds == 0 else "available"


def _availability_response(db: Session, pg: PG) -> PGAvailabilityOut:
    total_beds, available_beds, updated_at = _availability_counts(db, pg.id)
    confirmed_at = pg.availability_confirmed_at
    if confirmed_at is not None and confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.availability_stale_hours
    )
    return PGAvailabilityOut(
        pg_id=pg.id,
        total_beds=total_beds,
        available_beds=available_beds,
        availability_status=_availability_status(pg, available_beds),
        monthly_rent=pg.monthly_rent,
        security_deposit=pg.security_deposit,
        availability_updated_at=updated_at,
        availability_confirmed_at=pg.availability_confirmed_at,
        rent_confirmed_at=pg.rent_confirmed_at,
        availability_needs_update=confirmed_at is None or confirmed_at < cutoff,
    )


def _get_availability_pg(
    pg_id: int,
    account: Owner,
    db: Session,
    *,
    lock: bool = False,
) -> PG:
    if account.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or administrator privileges are required",
        )
    statement = select(PG).where(PG.id == pg_id)
    if account.role == "owner":
        statement = statement.where(PG.owner_id == account.id)
    if lock:
        statement = statement.with_for_update()
    pg = db.scalar(statement)
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return pg


@management_router.get(
    "/pgs/{pg_id}/availability",
    response_model=PGAvailabilityOut,
)
def get_pg_availability(
    pg_id: int,
    account: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    pg = _get_availability_pg(pg_id, account, db)
    return _availability_response(db, pg)


@management_router.patch(
    "/pgs/{pg_id}/availability",
    response_model=PGAvailabilityOut,
)
def update_pg_availability(
    pg_id: int,
    payload: PGAvailabilityUpdate,
    account: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    try:
        pg = _get_availability_pg(pg_id, account, db, lock=True)
        rooms = db.scalars(
            select(Room)
            .where(
                Room.pg_id == pg.id,
                Room.is_active.is_(True),
            )
            .order_by(Room.id)
            .with_for_update()
        ).all()
        rooms_by_id = {room.id: room for room in rooms}
        requested_room_ids = {item.room_id for item in payload.rooms}
        if not requested_room_ids.issubset(rooms_by_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more active rooms were not found",
            )

        _, previous_available, _ = _availability_counts(db, pg.id)
        previous_status = _availability_status(pg, previous_available)
        now = datetime.now(timezone.utc)
        changed = False
        for item in payload.rooms:
            room = rooms_by_id[item.room_id]
            if item.available_beds > room.total_beds:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Available beds cannot exceed the room's total beds",
                )
            new_occupied = room.total_beds - item.available_beds
            if new_occupied == room.occupied_beds:
                continue
            changed = True
            previous_occupied = room.occupied_beds
            previous_rent = room.monthly_rent_per_person
            room.occupied_beds = new_occupied
            room.updated_at = now
            db.add(
                RoomAvailabilityHistory(
                    pg_id=pg.id,
                    room_id=room.id,
                    previous_occupied_beds=previous_occupied,
                    new_occupied_beds=new_occupied,
                    previous_monthly_rent_per_person=previous_rent,
                    new_monthly_rent_per_person=room.monthly_rent_per_person,
                    actor_owner_id=account.id,
                    updated_at=now,
                )
            )

        new_available = sum(room.total_beds - room.occupied_beds for room in rooms)
        if (
            payload.availability_status == "full"
            and new_available != 0
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A full PG must have zero available beds",
            )
        if (
            payload.availability_status == "available"
            and new_available == 0
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An available PG must have at least one available bed",
            )

        previous_temporary = pg.is_temporarily_unavailable
        pg.is_temporarily_unavailable = (
            payload.availability_status == "temporarily_unavailable"
        )
        new_status = _availability_status(pg, new_available)
        if changed or previous_status != new_status or (
            previous_temporary != pg.is_temporarily_unavailable
        ):
            db.add(
                PGAvailabilityEvent(
                    pg_id=pg.id,
                    event_type="updated",
                    previous_available_beds=previous_available,
                    new_available_beds=new_available,
                    previous_status=previous_status,
                    new_status=new_status,
                    actor_owner_id=account.id,
                    created_at=now,
                )
            )
        db.commit()
        db.refresh(pg)
        return _availability_response(db, pg)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@management_router.post(
    "/pgs/{pg_id}/confirm-availability",
    response_model=PGAvailabilityOut,
)
def confirm_pg_availability(
    pg_id: int,
    payload: PGAvailabilityConfirmation,
    account: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    try:
        pg = _get_availability_pg(pg_id, account, db, lock=True)
        _, available_beds, _ = _availability_counts(db, pg.id)
        now = datetime.now(timezone.utc)
        current_status = _availability_status(pg, available_beds)
        pg.availability_confirmed_at = now
        if payload.confirm_rent:
            pg.rent_confirmed_at = now
        db.add(
            PGAvailabilityEvent(
                pg_id=pg.id,
                event_type="confirmed",
                previous_available_beds=available_beds,
                new_available_beds=available_beds,
                previous_status=current_status,
                new_status=current_status,
                actor_owner_id=account.id,
                created_at=now,
            )
        )
        db.commit()
        db.refresh(pg)
        return _availability_response(db, pg)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@management_router.get(
    "/pgs/{pg_id}/availability-history",
    response_model=list[PGAvailabilityEventOut],
)
def get_pg_availability_history(
    pg_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    pg = _get_availability_pg(pg_id, account, db)
    return db.scalars(
        select(PGAvailabilityEvent)
        .where(PGAvailabilityEvent.pg_id == pg.id)
        .order_by(
            PGAvailabilityEvent.created_at.desc(),
            PGAvailabilityEvent.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()


@management_router.get(
    "/pgs",
    response_model=list[OwnerPGOut],
    summary="List the authenticated owner's PG listings",
    description=(
        "Includes pending and rejected listings. Results are ordered by "
        "descending PG ID and paginated with limit and offset."
    ),
)
def list_managed_pgs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    response: Response = None,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    total = db.scalar(
        select(func.count(PG.id)).where(PG.owner_id == owner.id)
    ) or 0
    rows = db.execute(
        _owner_pg_statement(owner.id)
        .order_by(PG.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return [_owner_pg_response(row) for row in rows]


@management_router.post(
    "/pgs",
    response_model=OwnerPGOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a PG listing for the authenticated owner",
    description=(
        "The owner ID is assigned from the bearer token. New listings remain "
        "inactive and pending until an administrator reviews them."
    ),
)
def create_managed_pg(
    payload: PGCreate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    pg = create_pg_listing(payload, owner, db)
    return _owner_pg_response(_get_owned_pg(pg.id, owner, db))


@management_router.get("/pgs/{pg_id}", response_model=OwnerPGOut)
def get_managed_pg(
    pg_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _owner_pg_response(_get_owned_pg(pg_id, owner, db))


@management_router.patch(
    "/pgs/{pg_id}",
    response_model=OwnerPGOut,
    summary="Update an owned PG listing",
    description=(
        "Listing changes reset moderation to pending and make the listing "
        "inactive until administrator review."
    ),
)
def update_managed_pg(
    pg_id: int,
    payload: OwnerPGUpdate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    row = _get_owned_pg(pg_id, owner, db)
    pg = row[0]
    _save_owner_pg_update(pg, payload, db)
    return _owner_pg_response(_get_owned_pg(pg.id, owner, db))


@management_router.post(
    "/pgs/{pg_id}/deactivate",
    response_model=OwnerPGOut,
    summary="Deactivate an owned PG listing",
)
def deactivate_managed_pg(
    pg_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    row = _get_owned_pg(pg_id, owner, db)
    pg = row[0]
    pg.is_active = False
    try:
        db.commit()
        db.refresh(pg)
    except Exception:
        db.rollback()
        raise
    return _owner_pg_response(_get_owned_pg(pg.id, owner, db))


@management_router.post(
    "/pgs/{pg_id}/reactivate",
    response_model=OwnerPGOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request reactivation of an owned PG listing",
    description=(
        "Submitting a reactivation request leaves the listing inactive and "
        "pending. Only administrator review can approve and reactivate it."
    ),
)
def request_managed_pg_reactivation(
    pg_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    row = _get_owned_pg(pg_id, owner, db)
    pg = row[0]
    if pg.is_active or pg.verification_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Listing is active or already awaiting review",
        )

    pg.is_active = False
    pg.verification_status = "pending"
    try:
        db.commit()
        db.refresh(pg)
    except Exception:
        db.rollback()
        raise
    return _owner_pg_response(_get_owned_pg(pg.id, owner, db))


@router.post(
    "/register",
    response_model=OwnerOut,
    status_code=status.HTTP_201_CREATED,
)
def register_owner(
    payload: OwnerRegistration,
    db: Session = Depends(get_db),
):
    if payload.account_type != "owner":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The owners registration endpoint only creates owner accounts",
        )
    return register_account(payload, db)


@router.post("/login", response_model=OwnerTokenOut)
def login_owner(
    payload: OwnerLoginRequest,
    db: Session = Depends(get_db),
):
    if (
        settings.owner_token_secret is None
        or len(settings.owner_token_secret) < 32
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner authentication is not configured",
        )

    owner = db.scalar(select(Owner).where(Owner.email == payload.email))
    password_matches = verify_password(
        payload.password,
        owner.password_hash if owner is not None else DUMMY_PASSWORD_HASH,
    )
    if (
        owner is None
        or not password_matches
        or owner.role != "owner"
        or owner.account_status != "active"
        or not owner.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token = create_access_token(owner.id, owner.token_version)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner authentication is not configured",
        ) from None
    return OwnerTokenOut(
        access_token=access_token,
        expires_in=settings.access_token_expiry_minutes * 60,
    )


@router.get("/me", response_model=OwnerOut)
def get_owner_profile(owner: Owner = Depends(require_owner)):
    return owner_response(owner)


@router.post(
    "/me/verification",
    response_model=OwnerVerificationOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_owner_verification(
    payload: OwnerVerificationSubmission,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        verification = db.scalar(
            select(OwnerVerification)
            .where(OwnerVerification.owner_id == owner.id)
            .with_for_update()
        )
        if verification is not None:
            if verification.verification_status not in {
                "rejected",
                "needs_resubmission",
            }:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Owner verification is already pending or complete",
                )
            verification.verification_status = "pending"
            verification.management_authority_status = "pending"
            verification.submission_notes = payload.submission_notes
            verification.review_notes = None
            verification.authority_review_notes = None
            verification.identity_reviewer_id = None
            verification.authority_reviewer_id = None
            verification.reviewed_at = None
            verification.submitted_at = datetime.now(timezone.utc)
        else:
            verification = OwnerVerification(
                owner_id=owner.id,
                verification_status="pending",
                management_authority_status="pending",
                submission_notes=payload.submission_notes,
            )
            db.add(verification)

        db.commit()
        db.refresh(verification)
        return OwnerVerificationOut(
            owner_id=owner.id,
            identity_verification_status=verification.verification_status,
            verification_status=verification.verification_status,
            management_authority_status=verification.management_authority_status,
            submitted_at=verification.submitted_at,
        )
    except Exception:
        db.rollback()
        raise


@router.post(
    "/me/verification/submit",
    response_model=OwnerVerificationOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_owner_verification_documents(
    legal_name: str = Form(min_length=2, max_length=200),
    identity_document_type: str = Form(),
    authority_document_type: str = Form(),
    submission_notes: str | None = Form(default=None, max_length=3000),
    identity_document: UploadFile = File(),
    authority_document: UploadFile = File(),
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    submission = OwnerVerificationDocumentSubmission(
        legal_name=legal_name,
        identity_document_type=identity_document_type,
        authority_document_type=authority_document_type,
        submission_notes=submission_notes,
    )
    allowed_authority_evidence = {
        "property_owner": {"ownership_deed"},
        "pg_operator": {
            "lease_agreement",
            "management_contract",
            "business_license",
        },
        "property_manager": {"authorization_letter", "management_contract"},
        "authorized_representative": {"authorization_letter"},
    }
    if (
        owner.relationship_type is None
        or submission.authority_document_type
        not in allowed_authority_evidence.get(owner.relationship_type, set())
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Evidence type does not match the account's owner relationship",
        )

    identity_content, identity_extension, identity_media_type = (
        await _read_verification_upload(identity_document)
    )
    authority_content, authority_extension, authority_media_type = (
        await _read_verification_upload(authority_document)
    )

    identity_key = None
    authority_key = None
    try:
        identity_key = verification_storage.store(
            identity_content,
            identity_extension,
        )
        authority_key = verification_storage.store(
            authority_content,
            authority_extension,
        )
        verification = db.scalar(
            select(OwnerVerification)
            .where(OwnerVerification.owner_id == owner.id)
            .with_for_update()
        )
        old_keys = []
        if verification is None:
            verification = OwnerVerification(
                owner_id=owner.id,
                verification_status="pending",
                management_authority_status="pending",
            )
            db.add(verification)
        else:
            old_keys = [
                key
                for key in (
                    verification.identity_document_key,
                    verification.authority_document_key,
                )
                if key is not None
            ]

        now = datetime.now(timezone.utc)
        verification.legal_name = submission.legal_name
        verification.identity_document_type = submission.identity_document_type
        verification.identity_document_key = identity_key
        verification.identity_document_media_type = identity_media_type
        verification.authority_document_type = submission.authority_document_type
        verification.authority_document_key = authority_key
        verification.authority_document_media_type = authority_media_type
        verification.submission_notes = submission.submission_notes
        verification.verification_status = "pending"
        verification.management_authority_status = "pending"
        verification.review_notes = None
        verification.authority_review_notes = None
        verification.identity_reviewer_id = None
        verification.authority_reviewer_id = None
        verification.reviewed_at = None
        verification.submitted_at = now
        db.commit()
        db.refresh(verification)
    except Exception:
        db.rollback()
        for key in (identity_key, authority_key):
            if key is not None:
                verification_storage.delete(key)
        raise

    for key in old_keys:
        verification_storage.delete(key)
    return OwnerVerificationOut(
        owner_id=owner.id,
        identity_verification_status=verification.verification_status,
        verification_status=verification.verification_status,
        management_authority_status=verification.management_authority_status,
        submitted_at=verification.submitted_at,
    )


@router.get(
    "/me/verification/documents/{document_kind}",
    response_class=FileResponse,
)
def get_my_verification_document(
    document_kind: str,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if document_kind not in {"identity", "management_authority"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        )
    verification = db.scalar(
        select(OwnerVerification).where(OwnerVerification.owner_id == owner.id)
    )
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        )
    prefix = "identity" if document_kind == "identity" else "authority"
    return _verification_document_response(
        getattr(verification, f"{prefix}_document_key"),
        getattr(verification, f"{prefix}_document_media_type"),
        document_kind,
    )


@router.delete(
    "/me/verification/documents/{document_kind}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_my_verification_document(
    document_kind: str,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if document_kind not in {"identity", "management_authority"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        )
    try:
        verification = db.scalar(
            select(OwnerVerification)
            .where(OwnerVerification.owner_id == owner.id)
            .with_for_update()
        )
        if verification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification document not found",
            )
        prefix = "identity" if document_kind == "identity" else "authority"
        key_attr = f"{prefix}_document_key"
        media_attr = f"{prefix}_document_media_type"
        old_key = getattr(verification, key_attr)
        setattr(verification, key_attr, None)
        setattr(verification, media_attr, None)
        verification.verification_status = "pending"
        verification.management_authority_status = "pending"
        verification.review_notes = None
        verification.authority_review_notes = None
        verification.identity_reviewer_id = None
        verification.authority_reviewer_id = None
        verification.reviewed_at = None
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    if old_key is not None:
        verification_storage.delete(old_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/pgs", response_model=list[PGOut])
def get_owner_pgs(
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(PG)
        .where(PG.owner_id == owner.id)
        .order_by(PG.id)
    ).all()


@router.patch("/me/pgs/{pg_id}", response_model=PGOut)
def update_owner_pg(
    pg_id: int,
    payload: OwnerPGUpdate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    pg = db.scalar(
        select(PG).where(PG.id == pg_id, PG.owner_id == owner.id)
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )

    return _save_owner_pg_update(pg, payload, db)
