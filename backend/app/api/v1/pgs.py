
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Query, Response
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.v1.dependencies import get_authenticated_account, require_owner
from app.core.config import DEVELOPMENT_SAMPLE_MARKER_PREFIX, settings
from app.db.database import get_db
from app.models import City, NearbyPlace, Owner, PG, PGReport, PGUserReview, Room
from app.models.amenity import pg_amenities
from app.schemas.pg import PGCreate, PGOut, PGSearchOut
from app.schemas.admin import PGReportCreate, PGReportReceiptOut
from app.schemas.photo import AmenityOut, PhotoOut
from app.schemas.room import RoomOut, SharingType
from app.services.distance import database_distance_km
from app.services.listing_visibility import public_owner_eligibility
from app.services.notifications import notify_admins
from app.services.owner_listings import create_pg_listing

router = APIRouter(prefix="/pgs", tags=["PG Listings"])


@router.post(
    "/{pg_id}/reports",
    response_model=PGReportReceiptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report an issue with a public PG listing",
)
def create_pg_report(
    pg_id: int,
    payload: PGReportCreate,
    reporter: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    pg = db.scalar(
        select(PG).where(
            PG.id == pg_id,
            PG.is_active.is_(True),
            PG.verification_status == "verified",
            public_owner_eligibility(),
        )
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    if pg.owner_id == reporter.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Listing owners cannot report their own listing",
        )
    existing = db.scalar(
        select(PGReport.id).where(
            PGReport.pg_id == pg_id,
            PGReport.reporter_owner_id == reporter.id,
            PGReport.status.in_(("submitted", "under_review")),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open report for this listing",
        )
    report = PGReport(
        pg_id=pg_id,
        reporter_owner_id=reporter.id,
        category=payload.category,
        details=payload.details,
    )
    try:
        db.add(report)
        db.flush()
        notify_admins(
            db,
            notification_type="pg_report_submitted",
            title="PG report needs review",
            message="A user submitted a report about a PG listing.",
            dedupe_key=f"pg-report-submitted:{report.id}",
            related_entity_type="pg_report",
            related_entity_id=report.id,
        )
        db.commit()
        db.refresh(report)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open report for this listing",
        ) from None
    except Exception:
        db.rollback()
        raise
    return PGReportReceiptOut(id=report.id, status="submitted")


@router.post(
    "",
    response_model=PGOut,
    status_code=status.HTTP_201_CREATED,
)
def create_pg(
    payload: PGCreate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return create_pg_listing(payload, owner, db)


def is_loopback_request(request: Request) -> bool:
    return (
        request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
    )


@router.get(
    "",
    response_model=list[PGSearchOut],
    summary="Search public PG listings",
    description=(
        "Search active, verified PGs using location, rent, amenities, and "
        "availability filters. Supply nearby_place_id to return distances; "
        "combine it with max_distance_km to apply a radius. Distance is "
        "straight-line Haversine distance. Repeat amenity_ids to require every listed "
        "amenity, for example ?amenity_ids=1&amenity_ids=3. Pagination totals "
        "are returned in X-Total-Count, X-Limit, and X-Offset response headers."
    ),
    responses={
        200: {
            "headers": {
                "X-Total-Count": {
                    "description": "Total number of matching listings before pagination.",
                    "schema": {"type": "integer"},
                },
                "X-Limit": {
                    "description": "Maximum listings returned in this page.",
                    "schema": {"type": "integer"},
                },
                "X-Offset": {
                    "description": "Number of matching listings skipped.",
                    "schema": {"type": "integer"},
                },
            }
        }
    },
)
def get_pgs(
    request_is_local: bool = Depends(is_loopback_request),
    city_id: Annotated[int | None, Query(gt=0)] = None,
    area_id: Annotated[int | None, Query(gt=0)] = None,
    stay_type: Annotated[
        str | None,
        Query(
        pattern="^(men|women|co_living)$",
        description="Accepted values: men, women, co_living.",
        ),
    ] = None,
    min_rent: Annotated[
        Decimal | None,
        Query(
            ge=0,
            max_digits=10,
            decimal_places=2,
            description="Minimum monthly PG rent, inclusive.",
        ),
    ] = None,
    max_rent: Annotated[
        Decimal | None,
        Query(
            ge=0,
            max_digits=10,
            decimal_places=2,
            description="Maximum monthly PG rent, inclusive.",
        ),
    ] = None,
    food_available: Annotated[
        bool | None, Query(description="Filter by food availability.")
    ] = None,
    electricity_included: Annotated[
        bool | None, Query(description="Filter by whether electricity is included.")
    ] = None,
    verified_only: Annotated[
        bool, Query(description="Restrict results to verified PG listings.")
    ] = False,
    available_only: Annotated[
        bool,
        Query(description="Restrict results to PGs with at least one available bed."),
    ] = False,
    min_available_beds: Annotated[
        int | None,
        Query(ge=0, description="Minimum total available beds across active rooms."),
    ] = None,
    max_monthly_rent_per_person: Annotated[
        Decimal | None,
        Query(ge=0, max_digits=10, decimal_places=2),
    ] = None,
    sharing_type: SharingType | None = None,
    amenity_ids: Annotated[
        list[int] | None,
        Query(
            description=(
                "Repeat to require all amenity IDs, e.g. "
                "?amenity_ids=1&amenity_ids=3."
            )
        ),
    ] = None,
    availability_updated_within_hours: Annotated[
        int | None, Query(gt=0, le=8760)
    ] = None,
    nearby_place_id: Annotated[
        int | None,
        Query(gt=0, description="Active nearby place used as the distance reference."),
    ] = None,
    max_distance_km: Annotated[
        Decimal | None,
        Query(ge=0, le=20040, max_digits=8, decimal_places=3),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    if min_rent is not None and max_rent is not None and min_rent > max_rent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="min_rent must be less than or equal to max_rent",
        )
    if city_id is not None and city_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="city_id must be greater than zero",
        )
    if area_id is not None and area_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="area_id must be greater than zero",
        )
    if amenity_ids is not None and (
        any(amenity_id <= 0 for amenity_id in amenity_ids)
        or len(set(amenity_ids)) != len(amenity_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="amenity_ids must contain distinct positive IDs",
        )
    if max_distance_km is not None and nearby_place_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="nearby_place_id is required when max_distance_km is provided",
        )
    if nearby_place_id is not None and nearby_place_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="nearby_place_id must be greater than zero",
        )
    if (
        max_distance_km is not None
        and not Decimal(0) <= max_distance_km <= Decimal(20040)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="max_distance_km must be between 0 and 20040",
        )

    reference_place = None
    distance_expression = None
    if nearby_place_id is not None:
        reference_place = db.scalar(
            select(NearbyPlace).where(
                NearbyPlace.id == nearby_place_id,
                NearbyPlace.is_active.is_(True),
                NearbyPlace.city.has(City.is_active.is_(True)),
            )
        )
        if reference_place is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active nearby place not found",
            )
        if city_id is not None and city_id != reference_place.city_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="city_id must match the nearby place's city",
            )
        city_id = reference_place.city_id
        distance_expression = database_distance_km(
            PG.latitude,
            PG.longitude,
            reference_place.latitude,
            reference_place.longitude,
        )

    public_listing = and_(
        PG.is_active.is_(True),
        PG.verification_status == "verified",
        public_owner_eligibility(),
    )
    if settings.development_sample_search_enabled and request_is_local is True:
        development_sample = and_(
            PG.owner_id.is_(None),
            PG.is_active.is_(False),
            PG.verification_status == "pending",
            PG.name.like("ChezPG Sample %"),
            PG.description.like(f"{DEVELOPMENT_SAMPLE_MARKER_PREFIX}%"),
        )
        visibility_filter = or_(public_listing, development_sample)
    else:
        visibility_filter = public_listing
    statement = select(PG).where(visibility_filter)
    matching_room_filters = [
        Room.pg_id == PG.id,
        Room.is_active.is_(True),
    ]
    if max_monthly_rent_per_person is not None:
        matching_room_filters.append(
            Room.monthly_rent_per_person <= max_monthly_rent_per_person
        )
    if sharing_type is not None:
        matching_room_filters.append(Room.sharing_type == sharing_type)

    matching_available_beds = (
        select(
            func.coalesce(
                func.sum(Room.total_beds - Room.occupied_beds),
                0,
            )
        )
        .where(*matching_room_filters)
        .correlate(PG)
        .scalar_subquery()
    )
    latest_availability = (
        select(func.max(Room.updated_at))
        .where(Room.pg_id == PG.id, Room.is_active.is_(True))
        .correlate(PG)
        .scalar_subquery()
    )

    if city_id is not None:
        statement = statement.where(PG.city_id == city_id)

    if area_id is not None:
        statement = statement.where(PG.area_id == area_id)

    if stay_type is not None:
        statement = statement.where(PG.stay_type == stay_type)

    if min_rent is not None:
        statement = statement.where(PG.monthly_rent >= min_rent)

    if max_rent is not None:
        statement = statement.where(PG.monthly_rent <= max_rent)

    if food_available is not None:
        statement = statement.where(PG.food_available.is_(food_available))

    if electricity_included is not None:
        statement = statement.where(
            PG.electricity_included.is_(electricity_included)
        )

    if verified_only:
        statement = statement.where(PG.verification_status == "verified")

    if min_available_beds is not None:
        statement = statement.where(
            matching_available_beds >= min_available_beds
        )

    if available_only:
        statement = statement.where(
            matching_available_beds > 0,
            PG.is_temporarily_unavailable.is_(False),
        )

    if amenity_ids:
        matching_amenity_pgs = (
            select(pg_amenities.c.pg_id)
            .where(pg_amenities.c.amenity_id.in_(amenity_ids))
            .group_by(pg_amenities.c.pg_id)
            .            having(
                func.count(func.distinct(pg_amenities.c.amenity_id))
                == len(amenity_ids)
            )
        )
        statement = statement.where(PG.id.in_(matching_amenity_pgs))

    if (
        max_monthly_rent_per_person is not None
        or sharing_type is not None
    ):
        statement = statement.where(
            exists(select(1).where(*matching_room_filters))
        )

    if availability_updated_within_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=availability_updated_within_hours
        )
        statement = statement.where(PG.availability_confirmed_at >= cutoff)

    if max_distance_km is not None:
        statement = statement.where(
            PG.latitude.is_not(None),
            PG.longitude.is_not(None),
            distance_expression <= float(max_distance_km),
        )

    if distance_expression is not None:
        statement = statement.add_columns(
            distance_expression.label("distance_km")
        )

    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0

    # PG has no listing-updated timestamp yet; room inventory freshness is the
    # closest existing update signal, with PG ID as a stable tie-breaker.
    if distance_expression is not None:
        statement = statement.order_by(
            distance_expression.asc().nulls_last(),
            PG.id.desc(),
        )
    else:
        statement = statement.order_by(
            latest_availability.desc().nulls_last(),
            PG.id.desc(),
        )
    statement = statement.limit(limit).offset(offset)

    rows = db.execute(
        statement.options(
            selectinload(PG.rooms),
            selectinload(PG.photos),
            selectinload(PG.amenities),
            selectinload(PG.area),
        )
    ).all()
    page_pg_ids = [row[0].id for row in rows]
    rating_summaries = {}
    if page_pg_ids:
        rating_summaries = {
            pg_id: (average_rating, review_count)
            for pg_id, average_rating, review_count in db.execute(
                select(
                    PGUserReview.pg_id,
                    func.avg(PGUserReview.rating),
                    func.count(PGUserReview.id),
                )
                .where(
                    PGUserReview.pg_id.in_(page_pg_ids),
                    PGUserReview.status == "approved",
                )
                .group_by(PGUserReview.pg_id)
            ).all()
        }
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=settings.availability_stale_hours)
    results = []
    for row in rows:
        pg = row[0]
        distance_km = row[1] if distance_expression is not None else None
        average_rating, published_review_count = rating_summaries.get(
            pg.id,
            (None, 0),
        )
        active_rooms = [room for room in pg.rooms if room.is_active]
        room_responses = []
        for room in active_rooms:
            updated_at = room.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            room_response = RoomOut.model_validate(room).model_copy(
                update={"is_stale": updated_at < stale_cutoff}
            )
            room_responses.append(room_response)

        updated_times = [room.updated_at for room in active_rooms]
        updated_times = [
            timestamp.replace(tzinfo=timezone.utc)
            if timestamp.tzinfo is None
            else timestamp
            for timestamp in updated_times
        ]
        latest_updated_at = max(updated_times) if updated_times else None
        public_photos = sorted(
            (
                photo
                for photo in pg.photos
                if photo.review_status == "approved"
            ),
            key=lambda photo: (photo.display_order, photo.id),
        )
        photo_responses = [
            PhotoOut(
                id=photo.id,
                pg_id=photo.pg_id,
                url=f"{settings.api_v1_prefix}/photos/{photo.id}/content",
                caption=photo.caption,
                display_order=photo.display_order,
                is_cover=photo.is_cover,
                created_at=photo.created_at,
            )
            for photo in public_photos
        ]
        pg_response = PGSearchOut.model_validate(
            {
                "id": pg.id,
                "city_id": pg.city_id,
                "area_id": pg.area_id,
                "area_name": pg.area.name if pg.area is not None else None,
                "distance_km": distance_km,
                "name": pg.name,
                "description": pg.description,
                "address": pg.address,
                "stay_type": pg.stay_type,
                "monthly_rent": pg.monthly_rent,
                "security_deposit": pg.security_deposit,
                "electricity_included": pg.electricity_included,
                "food_available": pg.food_available,
                "contact_phone": pg.contact_phone,
                "verification_status": pg.verification_status,
                "average_rating": average_rating,
                "published_review_count": published_review_count,
                "rooms": room_responses,
                "photos": photo_responses,
                "cover_photo": next(
                    (photo for photo in photo_responses if photo.is_cover),
                    None,
                ),
                "amenities": [
                    AmenityOut.model_validate(amenity)
                    for amenity in sorted(
                        (
                            amenity
                            for amenity in pg.amenities
                            if amenity.is_active
                        ),
                        key=lambda amenity: amenity.id,
                    )
                ],
                "total_available_beds": sum(
                    room.available_beds for room in active_rooms
                ),
                "availability_status": (
                    "temporarily_unavailable"
                    if pg.is_temporarily_unavailable
                    else "full"
                    if not any(room.available_beds > 0 for room in active_rooms)
                    else "available"
                ),
                "availability_updated_at": latest_updated_at,
                "availability_confirmed_at": pg.availability_confirmed_at,
                "availability_is_stale": (
                    pg.availability_confirmed_at is None
                    or (
                        (
                            pg.availability_confirmed_at.replace(
                                tzinfo=timezone.utc
                            )
                            if pg.availability_confirmed_at.tzinfo is None
                            else pg.availability_confirmed_at
                        )
                        < stale_cutoff
                    )
                ),
            }
        )
        results.append(pg_response)
    return results
