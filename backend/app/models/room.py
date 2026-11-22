from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("total_beds > 0", name="ck_rooms_total_beds_positive"),
        CheckConstraint(
            "occupied_beds >= 0 AND occupied_beds <= total_beds",
            name="ck_rooms_occupied_beds_capacity",
        ),
        CheckConstraint(
            "monthly_rent_per_person >= 0",
            name="ck_rooms_rent_nonnegative",
        ),
        CheckConstraint(
            "sharing_type IN "
            "('single', 'double', 'triple', 'four_sharing', "
            "'five_plus_sharing')",
            name="ck_rooms_sharing_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    label: Mapped[str] = mapped_column(String(100))
    sharing_type: Mapped[str] = mapped_column(String(24))
    monthly_rent_per_person: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
    )
    total_beds: Mapped[int] = mapped_column(Integer)
    occupied_beds: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
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

    pg: Mapped["PG"] = relationship(back_populates="rooms")
    history: Mapped[list["RoomAvailabilityHistory"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RoomAvailabilityHistory.updated_at",
    )

    @property
    def available_beds(self) -> int:
        return self.total_beds - self.occupied_beds


class RoomAvailabilityHistory(Base):
    __tablename__ = "room_availability_history"
    __table_args__ = (
        CheckConstraint(
            "previous_occupied_beds IS NULL OR previous_occupied_beds >= 0",
            name="ck_room_history_previous_occupied_nonnegative",
        ),
        CheckConstraint(
            "new_occupied_beds >= 0",
            name="ck_room_history_new_occupied_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"),
        index=True,
    )
    previous_occupied_beds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    new_occupied_beds: Mapped[int] = mapped_column(Integer)
    previous_monthly_rent_per_person: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    new_monthly_rent_per_person: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
    )
    actor_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    room: Mapped[Room] = relationship(back_populates="history")
