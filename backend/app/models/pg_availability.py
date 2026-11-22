from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PGAvailabilityEvent(Base):
    __tablename__ = "pg_availability_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('updated', 'confirmed')",
            name="ck_pg_availability_events_type",
        ),
        CheckConstraint(
            "previous_available_beds IS NULL OR previous_available_beds >= 0",
            name="ck_pg_availability_events_previous_beds",
        ),
        CheckConstraint(
            "new_available_beds >= 0",
            name="ck_pg_availability_events_new_beds",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('available', 'full', 'temporarily_unavailable')",
            name="ck_pg_availability_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('available', 'full', 'temporarily_unavailable')",
            name="ck_pg_availability_events_new_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(20))
    previous_available_beds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    new_available_beds: Mapped[int] = mapped_column(Integer)
    previous_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    new_status: Mapped[str] = mapped_column(String(32))
    actor_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    pg: Mapped["PG"] = relationship(back_populates="availability_events")
