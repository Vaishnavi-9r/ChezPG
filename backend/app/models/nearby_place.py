from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

NearbyPlaceCategory = Literal[
    "tech_park",
    "college",
    "university",
    "coaching_center",
    "hospital",
    "metro_station",
]


class NearbyPlace(Base):
    __tablename__ = "nearby_places"
    __table_args__ = (
        CheckConstraint(
            "category IN ('tech_park', 'college', 'university', "
            "'coaching_center', 'hospital', 'metro_station')",
            name="ck_nearby_places_category",
        ),
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_nearby_places_latitude_range",
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_nearby_places_longitude_range",
        ),
        UniqueConstraint(
            "city_id",
            "name",
            "category",
            name="uq_nearby_places_city_name_category",
        ),
        Index("ix_nearby_places_city_category", "city_id", "category"),
        Index("ix_nearby_places_area_category", "area_id", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id", ondelete="CASCADE"),
    )
    area_id: Mapped[int | None] = mapped_column(
        ForeignKey("areas.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float] = mapped_column()
    longitude: Mapped[float] = mapped_column()
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    city = relationship("City")
    area = relationship("Area")
