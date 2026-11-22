
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.room import RoomOut
from app.schemas.photo import PhotoOut, AmenityOut
from app.schemas.availability import AvailabilityStatus

StayType = Literal["men", "women", "co_living"]


class PGCreate(BaseModel):
    city_id: int = Field(gt=0)
    area_id: int = Field(gt=0)

    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=3000)
    address: str = Field(min_length=5, max_length=1000)

    stay_type: StayType

    monthly_rent: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    security_deposit: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )

    electricity_included: bool = False
    food_available: bool = False
    contact_phone: str | None = Field(default=None, max_length=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "address")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("description", "contact_phone")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PGOut(BaseModel):
    id: int
    city_id: int
    area_id: int
    name: str
    description: str | None
    address: str
    stay_type: StayType
    monthly_rent: Decimal
    security_deposit: Decimal | None
    electricity_included: bool
    food_available: bool
    contact_phone: str | None
    verification_status: str

    model_config = ConfigDict(from_attributes=True)


class PGSearchOut(PGOut):
    area_name: str | None = None
    distance_km: float | None = None
    rooms: list[RoomOut] = Field(default_factory=list)
    photos: list[PhotoOut] = Field(default_factory=list)
    cover_photo: PhotoOut | None = None
    amenities: list[AmenityOut] = Field(default_factory=list)
    total_available_beds: int = 0
    availability_status: AvailabilityStatus = "full"
    availability_updated_at: datetime | None = None
    availability_confirmed_at: datetime | None = None
    availability_is_stale: bool = True
    average_rating: Decimal | None = None
    published_review_count: int = 0

    model_config = ConfigDict(from_attributes=True)
