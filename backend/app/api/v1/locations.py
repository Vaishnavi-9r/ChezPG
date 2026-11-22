from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Area, City
from app.schemas.location import AreaOut, CityOut

router = APIRouter(tags=["Locations"])


@router.get("/cities", response_model=list[CityOut])
def get_cities(db: Session = Depends(get_db)):
    statement = (
        select(City)
        .where(City.is_active.is_(True))
        .order_by(City.name)
    )
    return db.scalars(statement).all()


@router.get(
    "/cities/{city_id}/areas",
    response_model=list[AreaOut],
)
def get_areas(
    city_id: int,
    db: Session = Depends(get_db),
):
    city = db.get(City, city_id)

    if city is None or not city.is_active:
        raise HTTPException(
            status_code=404,
            detail="City not found",
        )

    statement = (
        select(Area)
        .where(
            Area.city_id == city_id,
            Area.is_active.is_(True),
        )
        .order_by(Area.name)
    )

    return db.scalars(statement).all()