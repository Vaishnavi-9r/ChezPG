from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

NearbyPlaceCategory = Literal[
    "tech_park",
    "college",
    "university",
    "coaching_center",
    "hospital",
    "metro_station",
]


class NearbyPlaceCreate(BaseModel):
    city_id: int = Field(gt=0)
    area_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=2, max_length=150)
    category: NearbyPlaceCategory
    address: str | None = Field(default=None, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("name", "address")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value and value is not None:
            raise ValueError("This field cannot be blank")
        return value

    model_config = ConfigDict(extra="forbid")


class NearbyPlaceUpdate(BaseModel):
    area_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=150)
    category: NearbyPlaceCategory | None = None
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool | None = None

    @field_validator("name", "address")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        supplied = {"latitude", "longitude"}.intersection(self.model_fields_set)
        if supplied and supplied != {"latitude", "longitude"}:
            raise ValueError("latitude and longitude must be updated together")
        if supplied and (self.latitude is None or self.longitude is None):
            raise ValueError("latitude and longitude must both be provided")
        return self

    @field_validator("name", "category", "is_active")
    @classmethod
    def reject_null_non_nullable(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        return value

    model_config = ConfigDict(extra="forbid")


class NearbyPlaceOut(BaseModel):
    id: int
    city_id: int
    area_id: int | None
    name: str
    category: NearbyPlaceCategory
    address: str | None
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
