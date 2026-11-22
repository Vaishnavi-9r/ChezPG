from sqlalchemy import Boolean, Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


pg_amenities = Table(
    "pg_amenities",
    Base.metadata,
    Column(
        "pg_id",
        ForeignKey("pgs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "amenity_id",
        ForeignKey("amenities.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Amenity(Base):
    __tablename__ = "amenities"
    __table_args__ = (
        UniqueConstraint("name", name="uq_amenities_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )

    pgs: Mapped[list["PG"]] = relationship(
        secondary=pg_amenities,
        back_populates="amenities",
    )
