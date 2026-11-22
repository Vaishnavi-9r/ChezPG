from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.pg import PGOut

class PGReviewRequest(BaseModel):
    action: Literal["approve", "reject", "request_corrections"]
    reason: str | None = Field(default=None, min_length=3, max_length=1000)

    @model_validator(mode="after")
    def require_reason_for_non_approval(self):
        if self.action != "approve" and not self.reason:
            raise ValueError("A concise reason is required for this decision")
        if self.reason is not None:
            self.reason = self.reason.strip()
            if not self.reason:
                raise ValueError("Reason cannot be blank")
        return self

    model_config = ConfigDict(extra="forbid")


class PGReviewDetailOut(BaseModel):
    listing: PGOut
    owner_id: int | None
    owner_identity_status: str | None
    management_authority_status: str | None
    legal_name: str | None
    identity_document_type: str | None
    has_identity_document: bool
    authority_document_type: str | None
    has_authority_document: bool
    review_required: bool


class PGReviewAuditOut(BaseModel):
    id: int
    pg_id: int
    reviewer_owner_id: int | None
    action: Literal["approved", "rejected", "needs_resubmission"]
    previous_status: str
    new_status: str
    reason: str
    details: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminDashboardOut(BaseModel):
    total_listings: int
    active_listings: int
    inactive_listings: int
    pending_listings: int
    approved_listings: int
    rejected_listings: int
    resubmission_required_listings: int
    pending_owner_identity_reviews: int
    pending_management_authority_reviews: int
    stale_availability_listings: int
    zero_available_bed_listings: int
    unreviewed_reports: int


class AdminPGListingOut(BaseModel):
    id: int
    owner_id: int | None
    city_id: int
    area_id: int
    name: str
    description: str | None
    address: str
    stay_type: str
    monthly_rent: Decimal
    security_deposit: Decimal | None
    food_available: bool
    electricity_included: bool
    contact_phone: str | None
    verification_status: str
    is_active: bool
    availability_confirmed_at: datetime | None
    created_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AdminPGModerationDetailOut(BaseModel):
    listing: AdminPGListingOut
    owner_full_name: str | None
    owner_identity_status: str | None
    management_authority_status: str | None
    owner_legal_name: str | None
    identity_document_type: str | None
    has_identity_document: bool
    authority_document_type: str | None
    has_authority_document: bool
    review_required: bool


class PGReportCreate(BaseModel):
    category: Literal[
        "incorrect_price",
        "no_beds_available",
        "incorrect_address",
        "duplicate_listing",
        "misleading_photos",
        "incorrect_details",
        "misleading_photos_or_details",
        "suspected_fraud",
        "other",
    ]
    details: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def normalize_details(self):
        if self.details is not None:
            self.details = self.details.strip() or None
        return self

    model_config = ConfigDict(extra="forbid")


class PGReportReceiptOut(BaseModel):
    id: int
    status: Literal["submitted"]


class AdminPGReportOut(BaseModel):
    id: int
    pg_id: int
    reporter_owner_id: int | None
    category: str
    details: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPGReportDetailOut(BaseModel):
    report: AdminPGReportOut
    listing: AdminPGListingOut


class PGReportReviewRequest(BaseModel):
    status: Literal["under_review", "resolved", "dismissed"]
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def normalize_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A concise reason is required")
        return self

    model_config = ConfigDict(extra="forbid")


class PGReviewReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def normalize_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A concise reason is required")
        return self

    model_config = ConfigDict(extra="forbid")


class PGReportEventOut(BaseModel):
    id: int
    report_id: int
    reviewer_owner_id: int | None
    action: str
    previous_status: str
    new_status: str
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPGReviewOut(BaseModel):
    id: int
    pg_id: int
    author_id: int
    rating: int
    text: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PGReviewModerationRequest(BaseModel):
    action: Literal["approve", "reject", "hide", "restore"]
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def normalize_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A concise moderation reason is required")
        return self

    model_config = ConfigDict(extra="forbid")


class PGReviewEventOut(BaseModel):
    id: int
    review_id: int
    actor_owner_id: int | None
    action: str
    previous_status: str | None
    new_status: str
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
