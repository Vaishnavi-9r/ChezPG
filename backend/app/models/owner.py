from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Owner(Base):
    __tablename__ = "owners"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN "
            "('property_owner', 'pg_operator', 'property_manager', "
            "'authorized_representative')",
            name="ck_owners_relationship_type",
        ),
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'disabled')",
            name="ck_owners_account_status",
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'user')",
            name="ck_owners_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True)
    relationship_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(20),
        default="owner",
        server_default="owner",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
    )
    phone_verified: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
    )
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")
    account_status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        server_default="active",
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

    verification: Mapped["OwnerVerification | None"] = relationship(
        back_populates="owner",
        foreign_keys="OwnerVerification.owner_id",
        cascade="all, delete-orphan",
        uselist=False,
    )
    pgs: Mapped[list["PG"]] = relationship(back_populates="owner")


class OwnerVerification(Base):
    __tablename__ = "owner_verifications"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN "
            "('pending', 'approved', 'rejected', 'needs_resubmission')",
            name="ck_owner_verifications_status",
        ),
        CheckConstraint(
            "management_authority_status IN "
            "('pending', 'approved', 'rejected', 'needs_resubmission')",
            name="ck_owner_verifications_authority_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey(
            "owners.id",
            ondelete="CASCADE",
            name="fk_owner_verifications_owner_id_owners",
        ),
        unique=True,
    )
    verification_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
    )
    submission_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    identity_document_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    identity_document_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    identity_document_media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authority_document_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    authority_document_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authority_document_media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    management_authority_status: Mapped[str] = mapped_column(
        String(24),
        default="pending",
        server_default="pending",
    )
    identity_reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    authority_reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    authority_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    owner: Mapped[Owner] = relationship(
        back_populates="verification",
        foreign_keys=[owner_id],
    )
    audit_events: Mapped[list["OwnerVerificationAuditEvent"]] = relationship(
        back_populates="verification",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OwnerVerificationAuditEvent.created_at.desc()",
    )


class OwnerVerificationAuditEvent(Base):
    __tablename__ = "owner_verification_audit_events"
    __table_args__ = (
        CheckConstraint(
            "verification_type IN ('identity', 'management_authority')",
            name="ck_owner_verification_audit_type",
        ),
        CheckConstraint(
            "action IN ('approved', 'rejected', 'needs_resubmission')",
            name="ck_owner_verification_audit_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    verification_id: Mapped[int] = mapped_column(
        ForeignKey("owner_verifications.id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"),
        nullable=True,
    )
    verification_type: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(24))
    previous_status: Mapped[str] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    verification: Mapped[OwnerVerification] = relationship(
        back_populates="audit_events"
    )
