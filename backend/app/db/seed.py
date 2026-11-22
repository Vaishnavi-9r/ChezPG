from sqlalchemy import select

from app.db.database import SessionLocal
from app.models import City, Area


HYDERABAD_AREAS = [
    "Madhapur",
    "Kondapur",
    "Gachibowli",
    "HITEC City",
    "Kukatpally",
    "Miyapur",
    "Ameerpet",
]


def main():
    with SessionLocal() as db:
        city = db.scalar(
            select(City).where(City.name == "Hyderabad")
        )

        if city is None:
            city = City(
                name="Hyderabad",
                state="Telangana",
                country="India",
                is_active=True,
            )
            db.add(city)
            db.flush()

        existing_areas = set(
            db.scalars(
                select(Area.name).where(
                    Area.city_id == city.id
                )
            ).all()
        )

        for area_name in HYDERABAD_AREAS:
            if area_name not in existing_areas:
                db.add(
                    Area(
                        city_id=city.id,
                        name=area_name,
                        is_active=True,
                    )
                )

        db.commit()

    print("Hyderabad and starter areas added successfully.")


if __name__ == "__main__":
    main()