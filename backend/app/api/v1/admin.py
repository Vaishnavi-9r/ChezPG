from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.v1.dependencies import require_admin_account
from app.core.config import settings
from app.db.database import get_db
from app.models import (
    Area,
    City,
    NearbyPlace,
    Owner,
    OwnerVerification,
    OwnerVerificationAuditEvent,
    PG,
    PGReport,
    PGReportEvent,
    PGReviewEvent,
    PGUserReview,
    PGUserReviewEvent,
    Room,
)
from app.schemas.admin import (
    AdminDashboardOut,
    AdminPGListingOut,
    AdminPGModerationDetailOut,
    AdminPGReportDetailOut,
    AdminPGReportOut,
    PGReviewAuditOut,
    PGReviewDetailOut,
    PGReviewRequest,
    PGReviewReasonRequest,
    PGReportEventOut,
    PGReportReviewRequest,
    AdminPGReviewOut,
    PGReviewModerationRequest,
    PGReviewEventOut,
)
from app.schemas.owner_admin import (
    OwnerVerificationDocumentMetadataOut,
    OwnerVerificationReviewOut,
    OwnerVerificationReviewRequest,
    PendingOwnerVerificationOut,
    VerificationAuditOut,
)
from app.schemas.pg import PGOut
from app.schemas.nearby_place import (
    NearbyPlaceCreate,
    NearbyPlaceOut,
    NearbyPlaceUpdate,
)
from app.api.v1.owners import _verification_document_response
from app.services.notifications import create_notification


require_admin = require_admin_account


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


def _validate_place_location(db: Session, city_id: int, area_id: int | None):
    city = db.get(City, city_id)
    if city is None or not city.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="city_id must refer to an active city",
        )
    if area_id is not None:
        area = db.get(Area, area_id)
        if area is None or not area.is_active or area.city_id != city_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="area_id must refer to an active area in the selected city",
            )


@router.get("/dashboard", response_model=AdminDashboardOut)
def get_admin_dashboard(db: Session = Depends(get_db)):
    listing_counts = db.execute(
        select(
            func.count(PG.id),
            func.count(PG.id).filter(PG.is_active.is_(True)),
            func.count(PG.id).filter(PG.is_active.is_(False)),
            func.count(PG.id).filter(PG.verification_status == "pending"),
            func.count(PG.id).filter(PG.verification_status == "verified"),
            func.count(PG.id).filter(PG.verification_status == "rejected"),
            func.count(PG.id).filter(
                PG.verification_status == "needs_resubmission"
            ),
        )
    ).one()
    verification_counts = db.execute(
        select(
            func.count(OwnerVerification.id).filter(
                OwnerVerification.verification_status.in_(
                    ("pending", "needs_resubmission")
                )
            ),
            func.count(OwnerVerification.id).filter(
                OwnerVerification.management_authority_status.in_(
                    ("pending", "needs_resubmission")
                )
            ),
        )
    ).one()

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(hours=settings.availability_stale_hours)
    stale_availability = db.scalar(
        select(func.count(PG.id)).where(
            PG.is_active.is_(True),
            or_(
                PG.availability_confirmed_at.is_(None),
                PG.availability_confirmed_at < stale_before,
            ),
        )
    ) or 0
    active_room_exists = exists(
        select(1).where(Room.pg_id == PG.id, Room.is_active.is_(True))
    )
    available_beds = (
        select(func.coalesce(func.sum(Room.total_beds - Room.occupied_beds), 0))
        .where(Room.pg_id == PG.id, Room.is_active.is_(True))
        .correlate(PG)
        .scalar_subquery()
    )
    zero_available_beds = db.scalar(
        select(func.count(PG.id)).where(
            PG.is_active.is_(True),
            active_room_exists,
            available_beds == 0,
        )
    ) or 0
    unreviewed_reports = db.scalar(
        select(func.count(PGReport.id)).where(PGReport.status == "submitted")
    ) or 0
    return AdminDashboardOut(
        total_listings=listing_counts[0] or 0,
        active_listings=listing_counts[1] or 0,
        inactive_listings=listing_counts[2] or 0,
        pending_listings=listing_counts[3] or 0,
        approved_listings=listing_counts[4] or 0,
        rejected_listings=listing_counts[5] or 0,
        resubmission_required_listings=listing_counts[6] or 0,
        pending_owner_identity_reviews=verification_counts[0] or 0,
        pending_management_authority_reviews=verification_counts[1] or 0,
        stale_availability_listings=stale_availability,
        zero_available_bed_listings=zero_available_beds,
        unreviewed_reports=unreviewed_reports,
    )


@router.get(
    "/pgs/pending",
    response_model=list[PGOut],
    summary="List pending or correction-requested PG listings",
)
def get_pending_pgs(db: Session = Depends(get_db)):
    statement = (
        select(PG)
        .where(
            PG.verification_status.in_(("pending", "needs_resubmission")),
            PG.is_active.is_(False),
        )
        .order_by(PG.id)
    )
    return db.scalars(statement).all()


@router.get("/pgs", response_model=list[AdminPGListingOut])
def list_admin_pgs(
    verification_status: Literal[
        "pending", "approved", "verified", "rejected", "needs_resubmission"
    ] | None = None,
    city_id: int | None = Query(default=None, gt=0),
    area_id: int | None = Query(default=None, gt=0),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    if created_from is not None and created_from.tzinfo is None:
        created_from = created_from.replace(tzinfo=timezone.utc)
    if created_to is not None and created_to.tzinfo is None:
        created_to = created_to.replace(tzinfo=timezone.utc)
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="created_from must be earlier than or equal to created_to",
        )
    statement = select(PG)
    if verification_status is not None:
        db_status = (
            "verified" if verification_status == "approved" else verification_status
        )
        statement = statement.where(PG.verification_status == db_status)
    if city_id is not None:
        statement = statement.where(PG.city_id == city_id)
    if area_id is not None:
        statement = statement.where(PG.area_id == area_id)
    if created_from is not None:
        statement = statement.where(PG.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(PG.created_at <= created_to)

    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return db.scalars(
        statement.order_by(PG.created_at.desc().nulls_last(), PG.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/pgs/{pg_id}", response_model=AdminPGModerationDetailOut)
def get_admin_pg_detail(pg_id: int, db: Session = Depends(get_db)):
    pg = db.scalar(
        select(PG)
        .where(PG.id == pg_id)
        .options(selectinload(PG.owner).selectinload(Owner.verification))
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    verification = pg.owner.verification if pg.owner is not None else None
    return AdminPGModerationDetailOut(
        listing=AdminPGListingOut.model_validate(pg),
        owner_full_name=pg.owner.full_name if pg.owner is not None else None,
        owner_identity_status=(
            verification.verification_status if verification is not None else None
        ),
        management_authority_status=(
            verification.management_authority_status
            if verification is not None
            else None
        ),
        owner_legal_name=verification.legal_name if verification is not None else None,
        identity_document_type=(
            verification.identity_document_type
            if verification is not None
            else None
        ),
        has_identity_document=bool(
            verification is not None and verification.identity_document_key
        ),
        authority_document_type=(
            verification.authority_document_type
            if verification is not None
            else None
        ),
        has_authority_document=bool(
            verification is not None and verification.authority_document_key
        ),
        review_required=pg.verification_status
        in {"pending", "needs_resubmission"},
    )

@router.post(
    "/nearby-places",
    response_model=NearbyPlaceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_nearby_place(
    payload: NearbyPlaceCreate,
    db: Session = Depends(get_db),
):
    _validate_place_location(db, payload.city_id, payload.area_id)
    place = NearbyPlace(**payload.model_dump())
    try:
        db.add(place)
        db.commit()
        db.refresh(place)
        return place
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A nearby place with this name and category already exists in the city",
        ) from None
    except Exception:
        db.rollback()
        raise


@router.patch(
    "/nearby-places/{place_id}",
    response_model=NearbyPlaceOut,
)
def update_nearby_place(
    place_id: int,
    payload: NearbyPlaceUpdate,
    db: Session = Depends(get_db),
):
    try:
        place = db.scalar(
            select(NearbyPlace)
            .where(NearbyPlace.id == place_id)
            .with_for_update()
        )
        if place is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nearby place not found",
            )
        changes = payload.model_dump(exclude_unset=True)
        if "area_id" in changes:
            _validate_place_location(db, place.city_id, changes["area_id"])
        for field_name, value in changes.items():
            setattr(place, field_name, value)
        db.commit()
        db.refresh(place)
        return place
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A nearby place with this name and category already exists in the city",
        ) from None
    except Exception:
        db.rollback()
        raise


@router.post("/pgs/{pg_id}/approve", response_model=PGOut)
def approve_pg(
    pg_id: int,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    return review_pg(
        pg_id,
        PGReviewRequest(action="approve"),
        db,
        admin,
    )


@router.post("/pgs/{pg_id}/reject", response_model=PGOut)
def reject_pg(
    pg_id: int,
    payload: PGReviewReasonRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    return review_pg(
        pg_id,
        PGReviewRequest(action="reject", reason=payload.reason),
        db,
        admin,
    )


@router.post("/pgs/{pg_id}/request-corrections", response_model=PGOut)
def request_pg_corrections(
    pg_id: int,
    payload: PGReviewReasonRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    return review_pg(
        pg_id,
        PGReviewRequest(action="request_corrections", reason=payload.reason),
        db,
        admin,
    )


@router.get(
    "/pgs/{pg_id}/review",
    response_model=PGReviewDetailOut,
)
def get_pg_review_detail(
    pg_id: int,
    db: Session = Depends(get_db),
):
    pg = db.scalar(
        select(PG)
        .where(PG.id == pg_id)
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    verification = (
        db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == pg.owner_id
            )
        )
        if pg.owner_id is not None
        else None
    )
    return PGReviewDetailOut(
        listing=PGOut.model_validate(pg),
        owner_id=pg.owner_id,
        owner_identity_status=(
            verification.verification_status if verification else None
        ),
        management_authority_status=(
            verification.management_authority_status if verification else None
        ),
        legal_name=verification.legal_name if verification else None,
        identity_document_type=(
            verification.identity_document_type if verification else None
        ),
        has_identity_document=bool(
            verification and verification.identity_document_key
        ),
        authority_document_type=(
            verification.authority_document_type if verification else None
        ),
        has_authority_document=bool(
            verification and verification.authority_document_key
        ),
        review_required=(
            pg.verification_status in {"pending", "needs_resubmission"}
        ),
    )


@router.patch(
    "/pgs/{pg_id}/review",
    response_model=PGOut,
)
def review_pg(
    pg_id: int,
    payload: PGReviewRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    try:
        pg = db.scalar(
            select(PG).where(PG.id == pg_id).with_for_update()
        )
        if pg is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PG listing not found",
            )

        if payload.action == "approve" and pg.owner_id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrators cannot approve their own PG listings",
            )

        if pg.verification_status not in {"pending", "needs_resubmission"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PG listing is no longer pending review",
            )

        if payload.action == "approve":
            owner_verification = (
                db.scalar(
                    select(OwnerVerification)
                    .where(OwnerVerification.owner_id == pg.owner_id)
                    .with_for_update()
                )
                if pg.owner_id is not None
                else None
            )
            if (
                pg.owner is None
                or pg.owner.account_status != "active"
                or owner_verification is None
                or owner_verification.verification_status != "approved"
                or owner_verification.management_authority_status != "approved"
                or owner_verification.identity_document_key is None
                or owner_verification.authority_document_key is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "PG listing requires an active owner with approved "
                        "identity and management authority evidence"
                    ),
                )
            new_status = "verified"
            pg.is_active = True
            action = "approved"
            reason = payload.reason or "Approved after manual listing review"
        elif payload.action == "reject":
            new_status = "rejected"
            pg.is_active = False
            action = "rejected"
            reason = payload.reason
        else:
            new_status = "needs_resubmission"
            pg.is_active = False
            action = "needs_resubmission"
            reason = payload.reason

        previous_status = pg.verification_status
        pg.verification_status = new_status
        review_event = PGReviewEvent(
                pg_id=pg.id,
                reviewer_owner_id=admin.id,
                action=action,
                previous_status=previous_status,
                new_status=new_status,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            )
        db.add(review_event)
        db.flush()
        if pg.owner_id is not None:
            owner_message = {
                "approved": "Your PG listing has been approved.",
                "rejected": "Your PG listing was not approved. Review the owner dashboard for next steps.",
                "needs_resubmission": "Changes or additional information are needed for your PG listing. Review the owner dashboard.",
            }[action]
            create_notification(
                db,
                recipient_user_id=pg.owner_id,
                notification_type=f"pg_{action}",
                title="PG listing review update",
                message=owner_message,
                dedupe_key=f"pg-review-event:{review_event.id}:owner:{pg.owner_id}",
                related_entity_type="pg",
                related_entity_id=pg.id,
            )

        db.commit()
        db.refresh(pg)
        return pg
    except Exception:
        db.rollback()
        raise


@router.get(
    "/pgs/{pg_id}/review-history",
    response_model=list[PGReviewAuditOut],
)
def get_pg_review_history(
    pg_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be 1-100 and offset must be non-negative",
        )
    if db.get(PG, pg_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return db.scalars(
        select(PGReviewEvent)
        .where(PGReviewEvent.pg_id == pg_id)
        .order_by(PGReviewEvent.created_at.desc(), PGReviewEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get(
    "/owners/verification/pending",
    response_model=list[PendingOwnerVerificationOut],
)
def get_pending_owner_verifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    pending_filter = (
        (OwnerVerification.verification_status.in_(("pending", "needs_resubmission")))
        | (
            OwnerVerification.management_authority_status.in_(
                ("pending", "needs_resubmission")
            )
        )
    )
    total = db.scalar(
        select(func.count(OwnerVerification.id)).where(pending_filter)
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    verifications = db.scalars(
        select(OwnerVerification)
        .where(pending_filter)
        .order_by(
            OwnerVerification.submitted_at.desc(),
            OwnerVerification.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        PendingOwnerVerificationOut(
            owner_id=verification.owner.id,
            full_name=verification.owner.full_name,
            email=verification.owner.email,
            phone_number=verification.owner.phone_number,
            relationship_type=verification.owner.relationship_type,
            legal_name=verification.legal_name,
            identity_document_type=verification.identity_document_type,
            has_identity_document=bool(verification.identity_document_key),
            authority_document_type=verification.authority_document_type,
            has_authority_document=bool(verification.authority_document_key),
            identity_verification_status=verification.verification_status,
            management_authority_status=verification.management_authority_status,
            submission_notes=verification.submission_notes,
            submitted_at=verification.submitted_at,
        )
        for verification in verifications
    ]


@router.patch(
    "/owners/{owner_id}/verification",
    response_model=OwnerVerificationReviewOut,
)
def review_owner_verification(
    owner_id: int,
    payload: OwnerVerificationReviewRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    try:
        verification = db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == owner_id
            ).with_for_update()
        )
        if verification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Owner verification not found",
            )
        if owner_id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrators cannot review their own verification",
            )
        status_attribute = (
            "verification_status"
            if payload.verification_type == "identity"
            else "management_authority_status"
        )
        current_status = getattr(verification, status_attribute)
        if current_status not in {"pending", "needs_resubmission"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Owner verification is no longer pending review",
            )

        if payload.action == "approve":
            has_evidence = (
                verification.identity_document_key is not None
                and verification.legal_name is not None
                if payload.verification_type == "identity"
                else verification.authority_document_key is not None
            )
            if not has_evidence:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Required verification evidence has not been submitted",
                )
            new_status = "approved"
            audit_action = "approved"
        elif payload.action == "reject":
            new_status = "rejected"
            audit_action = "rejected"
        else:
            new_status = "needs_resubmission"
            audit_action = "needs_resubmission"
        setattr(verification, status_attribute, new_status)
        now = datetime.now(timezone.utc)
        if payload.verification_type == "identity":
            verification.review_notes = payload.review_notes
            verification.identity_reviewer_id = admin.id
        else:
            verification.authority_review_notes = payload.review_notes
            verification.authority_reviewer_id = admin.id
        verification.reviewed_at = now
        verification_event = OwnerVerificationAuditEvent(
                verification_id=verification.id,
                reviewer_owner_id=admin.id,
                verification_type=payload.verification_type,
                action=audit_action,
                previous_status=current_status,
                new_status=new_status,
                reason=payload.review_notes
                or "Approved after manual document review",
                created_at=now,
            )
        db.add(verification_event)
        db.flush()
        status_message = {
            "approved": "Your owner verification review was approved.",
            "rejected": "Your owner verification review was not approved.",
            "needs_resubmission": "More information is needed for your owner verification.",
        }[new_status]
        create_notification(
            db,
            recipient_user_id=verification.owner_id,
            notification_type=f"owner_verification_{payload.verification_type}_{new_status}",
            title="Owner verification update",
            message=status_message,
            dedupe_key=(
                f"owner-verification-event:{verification_event.id}:"
                f"owner:{verification.owner_id}"
            ),
            related_entity_type="owner_verification",
            related_entity_id=verification.id,
        )
        db.commit()
        db.refresh(verification)
        return OwnerVerificationReviewOut(
            owner_id=verification.owner.id,
            verification_type=payload.verification_type,
            status=new_status,
            reviewer_owner_id=admin.id,
            reviewed_at=now,
        )
    except Exception:
        db.rollback()
        raise


@router.get("/reports", response_model=list[AdminPGReportOut])
def list_pg_reports(
    report_status: Literal[
        "submitted", "under_review", "resolved", "dismissed"
    ] | None = None,
    category: Literal[
        "incorrect_price",
        "no_beds_available",
        "incorrect_address",
        "duplicate_listing",
        "misleading_photos",
        "incorrect_details",
        "misleading_photos_or_details",
        "suspected_fraud",
        "other",
    ]
    | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    statement = select(PGReport)
    if report_status is not None:
        statement = statement.where(PGReport.status == report_status)
    if category is not None:
        statement = statement.where(PGReport.category == category)
    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return db.scalars(
        statement.order_by(PGReport.created_at.desc(), PGReport.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/reviews", response_model=list[AdminPGReviewOut])
def list_pg_user_reviews(
    review_status: Literal[
        "pending", "approved", "rejected", "hidden", "removed"
    ]
    | None = None,
    pg_id: int | None = Query(default=None, gt=0),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    statement = select(PGUserReview)
    if review_status is not None:
        statement = statement.where(PGUserReview.status == review_status)
    if pg_id is not None:
        statement = statement.where(PGUserReview.pg_id == pg_id)
    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return db.scalars(
        statement.order_by(
            PGUserReview.created_at.desc(),
            PGUserReview.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()


@router.patch(
    "/reviews/{review_id}",
    response_model=AdminPGReviewOut,
)
def moderate_pg_user_review(
    review_id: int,
    payload: PGReviewModerationRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    try:
        review = db.scalar(
            select(PGUserReview)
            .where(PGUserReview.id == review_id)
            .with_for_update()
        )
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found",
            )
        if review.author_id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrators cannot moderate their own reviews",
            )
        transitions = {
            "approve": ("pending", "approved"),
            "reject": ("pending", "rejected"),
            "hide": ("approved", "hidden"),
            "restore": ("hidden", "approved"),
        }
        expected_status, new_status = transitions[payload.action]
        if review.status != expected_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Review cannot be {payload.action}d from its current status",
            )
        previous_status = review.status
        review.status = new_status
        now = datetime.now(timezone.utc)
        review.updated_at = now
        audit_action = {
            "approve": "approved",
            "reject": "rejected",
            "hide": "hidden",
            "restore": "restored",
        }[payload.action]
        review_event = PGUserReviewEvent(
            review_id=review.id,
            actor_owner_id=admin.id,
            action=audit_action,
            previous_status=previous_status,
            new_status=new_status,
            reason=payload.reason,
            created_at=now,
        )
        db.add(review_event)
        db.flush()
        message = {
            "approved": "Your PG review has been published.",
            "rejected": "Your PG review was not approved for publication.",
            "hidden": "Your PG review is temporarily hidden.",
            "restored": "Your PG review has been restored.",
        }[audit_action]
        create_notification(
            db,
            recipient_user_id=review.author_id,
            notification_type=f"pg_review_{audit_action}",
            title="PG review update",
            message=message,
            dedupe_key=f"pg-user-review-event:{review_event.id}:author:{review.author_id}",
            related_entity_type="pg_review",
            related_entity_id=review.id,
        )
        db.commit()
        db.refresh(review)
        return review
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get(
    "/reviews/{review_id}/history",
    response_model=list[PGReviewEventOut],
)
def get_pg_user_review_history(
    review_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    if db.get(PGUserReview, review_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )
    return db.scalars(
        select(PGUserReviewEvent)
        .where(PGUserReviewEvent.review_id == review_id)
        .order_by(PGUserReviewEvent.created_at.desc(), PGUserReviewEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/reports/{report_id}", response_model=AdminPGReportDetailOut)
def get_pg_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(PGReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG report not found",
        )
    listing = db.get(PG, report.pg_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return AdminPGReportDetailOut(
        report=AdminPGReportOut.model_validate(report),
        listing=AdminPGListingOut.model_validate(listing),
    )


@router.patch("/reports/{report_id}", response_model=AdminPGReportOut)
def review_pg_report(
    report_id: int,
    payload: PGReportReviewRequest,
    db: Session = Depends(get_db),
    admin: Owner = Depends(require_admin),
):
    try:
        report = db.scalar(
            select(PGReport).where(PGReport.id == report_id).with_for_update()
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PG report not found",
            )
        if payload.status == "dismissed":
            listing = db.get(PG, report.pg_id)
            if listing is not None and listing.owner_id == admin.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Listing owners cannot dismiss reports against their PG",
                )
        allowed_transitions = {
            "submitted": {"under_review", "resolved", "dismissed"},
            "under_review": {"resolved", "dismissed"},
        }
        if payload.status not in allowed_transitions.get(report.status, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PG report is already in a terminal state or transition is invalid",
            )
        previous_status = report.status
        report.status = payload.status
        report.updated_at = datetime.now(timezone.utc)
        report_event = PGReportEvent(
                report_id=report.id,
                reviewer_owner_id=admin.id,
                action=payload.status,
                previous_status=previous_status,
                new_status=payload.status,
                reason=payload.reason,
                created_at=report.updated_at,
            )
        db.add(report_event)
        db.flush()
        if report.reporter_owner_id is not None:
            create_notification(
                db,
                recipient_user_id=report.reporter_owner_id,
                notification_type=f"pg_report_{payload.status}",
                title="PG report update",
                message={
                    "under_review": "Your PG report is being reviewed.",
                    "resolved": "Your PG report has been resolved.",
                    "dismissed": "Your PG report has been closed.",
                }[payload.status],
                dedupe_key=(
                    f"pg-report-event:{report_event.id}:"
                    f"reporter:{report.reporter_owner_id}"
                ),
                related_entity_type="pg_report",
                related_entity_id=report.id,
            )
        db.commit()
        db.refresh(report)
        return report
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get(
    "/reports/{report_id}/history",
    response_model=list[PGReportEventOut],
)
def get_pg_report_history(
    report_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    if db.get(PGReport, report_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG report not found",
        )
    return db.scalars(
        select(PGReportEvent)
        .where(PGReportEvent.report_id == report_id)
        .order_by(PGReportEvent.created_at.desc(), PGReportEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get(
    "/owners/{owner_id}/verification/documents/{document_kind}",
    response_class=FileResponse,
)
def get_owner_verification_document(
    owner_id: int,
    document_kind: str,
    db: Session = Depends(get_db),
):
    if document_kind not in {"identity", "management_authority"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification document not found",
        )
    verification = db.scalar(
        select(OwnerVerification).where(
            OwnerVerification.owner_id == owner_id
        )
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


@router.get(
    "/owners/{owner_id}/verification/audit",
    response_model=list[VerificationAuditOut],
)
def get_owner_verification_audit(
    owner_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be 1-100 and offset must be non-negative",
        )
    verification = db.scalar(
        select(OwnerVerification).where(
            OwnerVerification.owner_id == owner_id
        )
    )
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Owner verification not found",
        )
    return db.scalars(
        select(OwnerVerificationAuditEvent)
        .where(OwnerVerificationAuditEvent.verification_id == verification.id)
        .order_by(
            OwnerVerificationAuditEvent.created_at.desc(),
            OwnerVerificationAuditEvent.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
