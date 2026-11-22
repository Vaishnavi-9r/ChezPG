from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PhotoCaptionUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=300)

    model_config = ConfigDict(extra="forbid")


class PhotoOrderRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")


class PhotoCoverRequest(BaseModel):
    is_cover: bool = True

    model_config = ConfigDict(extra="forbid")


class PhotoReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    moderation_notes: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class PhotoOut(BaseModel):
    id: int
    pg_id: int
    url: str
    caption: str | None
    display_order: int
    is_cover: bool
    created_at: datetime


class OwnerPhotoOut(PhotoOut):
    review_status: str


class PendingPhotoOut(BaseModel):
    id: int
    pg_id: int
    url: str
    caption: str | None
    display_order: int
    created_at: datetime
    review_status: str


class AdminPhotoOut(BaseModel):
    id: int
    pg_id: int
    url: str
    caption: str | None
    display_order: int
    is_cover: bool
    review_status: str
    created_at: datetime


class AmenityOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class AmenityIdsRequest(BaseModel):
    amenity_ids: list[int] = Field(max_length=100)

    model_config = ConfigDict(extra="forbid")


class PGMediaOut(BaseModel):
    pg_id: int
    photos: list[PhotoOut]
    cover_photo: PhotoOut | None
    amenities: list[AmenityOut]
