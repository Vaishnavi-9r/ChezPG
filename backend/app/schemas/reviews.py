from datetime import datetime
from typing import Literal
from html import escape

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PGReviewCreate(BaseModel):
    rating: int = Field(strict=True, ge=1, le=5)
    text: str | None = Field(default=None, max_length=3000)

    @field_validator("text")
    @classmethod
    def normalize_review_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return escape(value, quote=False) or None

    model_config = ConfigDict(extra="forbid")


class PGReviewUpdate(PGReviewCreate):
    pass


class PGReviewOut(BaseModel):
    id: int
    pg_id: int
    rating: int
    text: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PGReviewReceiptOut(PGReviewOut):
    status: Literal["pending", "approved", "rejected", "hidden", "removed"]


class AdminPGReviewOut(PGReviewReceiptOut):
    author_id: int


class PGReviewModerationRequest(BaseModel):
    action: Literal["approve", "reject", "hide", "restore"]
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A concise moderation reason is required")
        return value

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
