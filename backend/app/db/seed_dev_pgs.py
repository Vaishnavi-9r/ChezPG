from dataclasses import dataclass
from decimal import Decimal
import os

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import DEVELOPMENT_SAMPLE_MARKER_PREFIX, settings
from app.db.database import SessionLocal
from app.models import Amenity, Area, City, PG, Room


@dataclass(frozen=True)
class SamplePG:
    key: str
    name: str
    area: str
    rent: Decimal
    stay_type: str
    food_available: bool
    electricity_included: bool
    total_beds: int
    occupied_beds: int
    sharing_type: str
    amenities: tuple[str, ...]


SAMPLE_PGS = (
    SamplePG(
        "madhapur-men",
        "ChezPG Sample Men's Stay - Madhapur",
        "Madhapur",
        Decimal("8500"),
        "men",
        True,
        False,
        4,
        1,
        "double",
        ("Wi-Fi", "Laundry"),
    ),
    SamplePG(
        "kondapur-women",
        "ChezPG Sample Women's Residence - Kondapur",
        "Kondapur",
        Decimal("14500"),
        "women",
        True,
        True,
        4,
        2,
        "double",
        ("Wi-Fi", "Air conditioning", "Attached bathroom"),
    ),
    SamplePG(
        "gachibowli-coliving",
        "ChezPG Sample Co-living House - Gachibowli",
        "Gachibowli",
        Decimal("18000"),
        "co_living",
        False,
        False,
        6,
        3,
        "triple",
        ("Wi-Fi", "Parking", "Washing machine"),
    ),
    SamplePG(
        "kukatpally-budget",
        "ChezPG Sample Budget Stay - Kukatpally",
        "Kukatpally",
        Decimal("7000"),
        "men",
        False,
        False,
        6,
        4,
        "triple",
        ("Wi-Fi", "TV"),
    ),
    SamplePG(
        "ameerpet-metro",
        "ChezPG Sample Metro Stay - Ameerpet",
        "Ameerpet",
        Decimal("11000"),
        "women",
        True,
        False,
        3,
        1,
        "triple",
        ("Wi-Fi", "Housekeeping"),
    ),
    SamplePG(
        "hitec-city-tech",
        "ChezPG Sample Tech Stay - HITEC City",
        "HITEC City",
        Decimal("22000"),
        "men",
        True,
        True,
        2,
        0,
        "double",
        ("Wi-Fi", "Air conditioning", "Attached bathroom", "Parking"),
    ),
    SamplePG(
        "miyapur-coliving",
        "ChezPG Sample Co-living Nook - Miyapur",
        "Miyapur",
        Decimal("9000"),
        "co_living",
        False,
        True,
        5,
        2,
        "five_plus_sharing",
        ("Wi-Fi", "Laundry", "Washing machine"),
    ),
    SamplePG(
        "madhapur-women",
        "ChezPG Sample Women's Budget Stay - Madhapur",
        "Madhapur",
        Decimal("12500"),
        "women",
        False,
        True,
        3,
        1,
        "triple",
        ("Wi-Fi", "Housekeeping", "Attached bathroom"),
    ),
)


def validate_development_database(database_url: str, app_environment: str) -> None:
    if app_environment.strip().lower() != "development":
        raise RuntimeError(
            "Development sample seeding requires APP_ENV=development."
        )

    url = make_url(database_url)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.port != 5433
        or url.database != "chezpg"
    ):
        raise RuntimeError(
            "Development sample seeding is restricted to the local chezpg "
            "PostgreSQL database on host port 5433."
        )


def seed_development_pgs(db: Session) -> tuple[int, int]:
    city = db.scalar(select(City).where(City.name == "Hyderabad"))
    if city is None or not city.is_active:
        raise RuntimeError("An active Hyderabad city record is required.")

    areas = {
        area.name: area
        for area in db.scalars(
            select(Area).where(
                Area.city_id == city.id,
                Area.is_active.is_(True),
            )
        ).all()
    }
    amenity_names = {
        amenity.name
        for amenity in db.scalars(
            select(Amenity).where(Amenity.is_active.is_(True))
        ).all()
    }
    required_areas = {sample.area for sample in SAMPLE_PGS}
    missing_areas = required_areas - areas.keys()
    if missing_areas:
        raise RuntimeError(
            "Missing active Hyderabad areas: " + ", ".join(sorted(missing_areas))
        )
    required_amenities = {
        name for sample in SAMPLE_PGS for name in sample.amenities
    }
    missing_amenities = required_amenities - amenity_names
    if missing_amenities:
        raise RuntimeError(
            "Missing active amenities: " + ", ".join(sorted(missing_amenities))
        )

    added = 0
    existing = 0
    for sample in SAMPLE_PGS:
        marker = f"{DEVELOPMENT_SAMPLE_MARKER_PREFIX}{sample.key}]"
        marked = db.scalars(
            select(PG).where(PG.description.contains(marker))
        ).all()
        if len(marked) > 1:
            raise RuntimeError(
                f"Multiple listings use development sample marker {sample.key}."
            )
        if marked:
            existing += 1
            continue

        name_collision = db.scalar(
            select(PG.id).where(PG.name == sample.name).limit(1)
        )
        if name_collision is not None:
            raise RuntimeError(
                f"Listing name already exists without the seed marker: "
                f"{sample.name} (PG ID {name_collision}). No data was changed."
            )

        pg = PG(
            city_id=city.id,
            area_id=areas[sample.area].id,
            owner_id=None,
            name=sample.name,
            description=(
                f"{marker} Fictional development/test listing; not a real "
                "accommodation business."
            ),
            address=f"Fictional development sample address, {sample.area}, Hyderabad",
            stay_type=sample.stay_type,
            monthly_rent=sample.rent,
            security_deposit=None,
            electricity_included=sample.electricity_included,
            food_available=sample.food_available,
            verification_status="pending",
            is_active=False,
        )
        pg.rooms.append(
            Room(
                label="Development sample room",
                sharing_type=sample.sharing_type,
                monthly_rent_per_person=sample.rent,
                total_beds=sample.total_beds,
                occupied_beds=sample.occupied_beds,
                is_active=True,
            )
        )
        pg.amenities = list(
            db.scalars(
                select(Amenity).where(
                    Amenity.name.in_(sample.amenities),
                    Amenity.is_active.is_(True),
                )
            ).all()
        )
        db.add(pg)
        added += 1

    return added, existing


def main() -> None:
    validate_development_database(
        settings.database_url,
        os.environ.get("APP_ENV", ""),
    )
    with SessionLocal() as db:
        try:
            added, existing = seed_development_pgs(db)
            db.commit()
        except Exception:
            db.rollback()
            raise

    print(f"Development sample PGs added: {added}; already present: {existing}.")
    print("All samples remain pending and inactive until legitimate review.")


if __name__ == "__main__":
    main()
