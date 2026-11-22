from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PGPhoto(Base):
    __tablename__ = "pg_photos"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_pg_photos_review_status",
        ),
        CheckConstraint("display_order >= 0", name="ck_pg_photos_order_nonnegative"),
        UniqueConstraint("storage_key", name="uq_pg_photos_storage_key"),
        Index(
            "uq_pg_photos_one_cover_per_pg",
            "pg_id",
            unique=True,
            postgresql_where=text("is_cover"),
            sqlite_where=text("is_cover = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
    )
    storage_key: Mapped[str] = mapped_column(String(100))
    media_type: Mapped[str] = mapped_column(String(30))
    caption: Mapped[str | None] = mapped_column(String(300), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_cover: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
    )
    moderation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    pg: Mapped["PG"] = relationship(back_populates="photos")
