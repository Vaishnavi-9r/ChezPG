from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.owner import OwnerRelationship


class OwnerVerificationReviewRequest(BaseModel):
    verification_type: Literal["identity", "management_authority"]
    action: Literal["approve", "reject", "request_corrections"]
    review_notes: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def require_reason_for_non_approval(self):
        if self.action != "approve" and not self.review_notes:
            raise ValueError("A concise reason is required for this decision")
        if self.review_notes is not None:
            self.review_notes = self.review_notes.strip()
            if not self.review_notes:
                raise ValueError("Review notes cannot be blank")
        return self

    model_config = ConfigDict(extra="forbid")


class PendingOwnerVerificationOut(BaseModel):
    owner_id: int
    full_name: str
    email: EmailStr | None
    phone_number: str
    relationship_type: OwnerRelationship
    legal_name: str | None
    identity_document_type: str | None
    has_identity_document: bool
    authority_document_type: str | None
    has_authority_document: bool
    identity_verification_status: Literal[
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    management_authority_status: Literal[
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    submission_notes: str | None
    submitted_at: datetime


class OwnerVerificationReviewOut(BaseModel):
    owner_id: int
    verification_type: Literal["identity", "management_authority"]
    status: Literal[
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    reviewer_owner_id: int
    reviewed_at: datetime


class OwnerVerificationDocumentMetadataOut(BaseModel):
    owner_id: int
    document_type: Literal["identity", "management_authority"]
    media_type: str


class VerificationAuditOut(BaseModel):
    id: int
    verification_type: Literal["identity", "management_authority"]
    action: Literal["approved", "rejected", "needs_resubmission"]
    previous_status: str
    new_status: str
    reason: str
    reviewer_owner_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
