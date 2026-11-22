from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


SharingType = Literal[
    "single",
    "double",
    "triple",
    "four_sharing",
    "five_plus_sharing",
]


class RoomCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    sharing_type: SharingType
    monthly_rent_per_person: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=2,
    )
    total_beds: int = Field(gt=0, le=1000)
    occupied_beds: int = Field(default=0, ge=0, le=1000)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Room label cannot be blank")
        return value

    @model_validator(mode="after")
    def occupied_beds_within_capacity(self):
        if self.occupied_beds > self.total_beds:
            raise ValueError("Occupied beds cannot exceed total beds")
        return self

    model_config = ConfigDict(extra="forbid")


class RoomUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    sharing_type: SharingType | None = None
    monthly_rent_per_person: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )
    total_beds: int | None = Field(default=None, gt=0, le=1000)
    occupied_beds: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Room label cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one room field must be provided")
        required_fields = {
            "label",
            "sharing_type",
            "monthly_rent_per_person",
            "total_beds",
            "occupied_beds",
            "is_active",
        }
        for field_name in required_fields.intersection(self.model_fields_set):
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    model_config = ConfigDict(extra="forbid")


class RoomOut(BaseModel):
    id: int
    pg_id: int
    label: str
    sharing_type: SharingType
    monthly_rent_per_person: Decimal
    total_beds: int
    occupied_beds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    is_stale: bool = False

    @computed_field
    @property
    def available_beds(self) -> int:
        return self.total_beds - self.occupied_beds

    model_config = ConfigDict(from_attributes=True)


class RoomAvailabilityHistoryOut(BaseModel):
    id: int
    pg_id: int
    room_id: int
    previous_occupied_beds: int | None
    new_occupied_beds: int
    previous_monthly_rent_per_person: Decimal | None
    new_monthly_rent_per_person: Decimal
    actor_owner_id: int | None
    updated_at: datetime
    change_notes: str | None

    model_config = ConfigDict(from_attributes=True)
