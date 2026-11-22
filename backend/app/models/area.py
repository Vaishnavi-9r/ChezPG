from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Area(Base):
    __tablename__ = "areas"

    __table_args__ = (
        UniqueConstraint(
            "city_id",
            "name",
            name="uq_area_city_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    city = relationship("City", back_populates="areas")
    pgs = relationship("PG", back_populates="area")