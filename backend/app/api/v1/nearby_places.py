from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import City, NearbyPlace
from app.schemas.nearby_place import NearbyPlaceCategory, NearbyPlaceOut

router = APIRouter(prefix="/nearby-places", tags=["Nearby Places"])


@router.get(
    "",
    response_model=list[NearbyPlaceOut],
    summary="Search nearby places",
    description="Lists active, curated nearby places; coordinates are supplied by administrators.",
)
def list_nearby_places(
    city_id: Annotated[int | None, Query(gt=0)] = None,
    area_id: Annotated[int | None, Query(gt=0)] = None,
    category: NearbyPlaceCategory | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    statement = (
        select(NearbyPlace)
        .join(City, City.id == NearbyPlace.city_id)
        .where(
            NearbyPlace.is_active.is_(True),
            City.is_active.is_(True),
        )
    )
    if city_id is not None:
        statement = statement.where(NearbyPlace.city_id == city_id)
    if area_id is not None:
        statement = statement.where(NearbyPlace.area_id == area_id)
    if category is not None:
        statement = statement.where(NearbyPlace.category == category)
    if q is not None:
        search_text = q.strip()
        if not search_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="q must contain non-whitespace characters",
            )
        search_pattern = f"%{search_text}%"
        statement = statement.where(
            or_(
                NearbyPlace.name.ilike(search_pattern),
                NearbyPlace.address.ilike(search_pattern),
            )
        )

    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    places = db.scalars(
        statement.order_by(NearbyPlace.name, NearbyPlace.id)
        .limit(limit)
        .offset(offset)
    ).all()
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return places


@router.get("/{place_id}", response_model=NearbyPlaceOut)
def get_nearby_place(
    place_id: int,
    db: Session = Depends(get_db),
):
    place = db.scalar(
        select(NearbyPlace).where(
            NearbyPlace.id == place_id,
            NearbyPlace.is_active.is_(True),
            NearbyPlace.city.has(City.is_active.is_(True)),
        )
    )
    if place is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nearby place not found",
        )
    return place
