from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        Index(
            "ix_notifications_recipient_read_created",
            "recipient_user_id",
            "is_read",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"),
        index=True,
    )
    type: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    related_entity_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    related_entity_id: Mapped[int | None] = mapped_column(nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    is_read: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
