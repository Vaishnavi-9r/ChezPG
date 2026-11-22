from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(
        String(100),
        default="India",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    areas = relationship(
        "Area",
        back_populates="city",
        cascade="all, delete-orphan",
    )
    pgs = relationship("PG", back_populates="city")