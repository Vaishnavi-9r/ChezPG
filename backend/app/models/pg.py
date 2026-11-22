from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PG(Base):
    __tablename__ = "pgs"
    __table_args__ = (
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL AND "
            "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="ck_pgs_coordinates_pair_and_range",
        ),
        Index("ix_pgs_owner_id", "owner_id"),
        Index(
            "ix_pgs_public_rent",
            "is_active",
            "verification_status",
            "monthly_rent",
        ),
        Index(
            "ix_pgs_food_electricity",
            "food_available",
            "electricity_included",
        ),
        Index("ix_pgs_city_coordinates", "city_id", "latitude", "longitude"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )

    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id"),
        index=True,
    )
    area_id: Mapped[int] = mapped_column(
        ForeignKey("areas.id"),
        index=True,
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "owners.id",
            ondelete="RESTRICT",
            name="fk_pgs_owner_id_owners",
        ),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(150), index=True)
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    address: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)

    # Expected values: men, women, co_living
    stay_type: Mapped[str] = mapped_column(String(20), index=True)

    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    security_deposit: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )

    electricity_included: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    food_available: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    contact_phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # Listings start pending and inactive until reviewed.
    verification_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )
    is_temporarily_unavailable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    availability_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rent_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    city = relationship("City", back_populates="pgs")
    area = relationship("Area", back_populates="pgs")
    owner = relationship("Owner", back_populates="pgs")
    rooms = relationship(
        "Room",
        back_populates="pg",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    photos = relationship(
        "PGPhoto",
        back_populates="pg",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    amenities = relationship(
        "Amenity",
        secondary="pg_amenities",
        back_populates="pgs",
    )
    availability_events: Mapped[list["PGAvailabilityEvent"]] = relationship(
        back_populates="pg",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PGAvailabilityEvent.created_at.desc()",
    )
    review_events: Mapped[list["PGReviewEvent"]] = relationship(
        back_populates="pg",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PGReviewEvent.created_at.desc()",
    )
    reviews: Mapped[list["PGUserReview"]] = relationship(
        back_populates="pg",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PGReviewEvent(Base):
    __tablename__ = "pg_review_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('approved', 'rejected', 'needs_resubmission')",
            name="ck_pg_review_events_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(24))
    previous_status: Mapped[str] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(1000))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    pg: Mapped[PG] = relationship(back_populates="review_events")


class PGUserReview(Base):
    __tablename__ = "pg_user_reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_pg_user_reviews_rating"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'hidden', 'removed')",
            name="ck_pg_user_reviews_status",
        ),
        Index("uq_pg_user_reviews_pg_author", "pg_id", "author_id", unique=True),
        Index("ix_pg_user_reviews_public", "pg_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"),
        index=True,
    )
    rating: Mapped[int] = mapped_column()
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        default="pending",
        server_default="pending",
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

    pg: Mapped[PG] = relationship(back_populates="reviews")


class PGUserReviewEvent(Base):
    __tablename__ = "pg_user_review_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('submitted', 'edited', 'author_removed', "
            "'approved', 'rejected', 'hidden', 'restored')",
            name="ck_pg_user_review_events_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("pg_user_reviews.id", ondelete="CASCADE"),
        index=True,
    )
    actor_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(24))
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class PGReport(Base):
    __tablename__ = "pg_reports"
    __table_args__ = (
        CheckConstraint(
            "category IN ('incorrect_price', 'no_beds_available', "
            "'incorrect_address', 'duplicate_listing', "
            "'misleading_photos', 'incorrect_details', "
            "'misleading_photos_or_details', 'suspected_fraud', 'other')",
            name="ck_pg_reports_category",
        ),
        CheckConstraint(
            "status IN ('submitted', 'under_review', 'resolved', 'dismissed')",
            name="ck_pg_reports_status",
        ),
        Index(
            "uq_pg_reports_open_reporter_listing",
            "pg_id",
            "reporter_owner_id",
            unique=True,
            postgresql_where=text("status IN ('submitted', 'under_review')"),
            sqlite_where=text("status IN ('submitted', 'under_review')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_id: Mapped[int] = mapped_column(
        ForeignKey("pgs.id", ondelete="CASCADE"),
        index=True,
    )
    reporter_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(String(32))
    details: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        default="submitted",
        server_default="submitted",
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


class PGReportEvent(Base):
    __tablename__ = "pg_report_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('under_review', 'resolved', 'dismissed')",
            name="ck_pg_report_events_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("pg_reports.id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(24))
    previous_status: Mapped[str] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )