from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AvailabilityStatus = Literal[
    "available",
    "full",
    "temporarily_unavailable",
]


class RoomBedAvailabilityUpdate(BaseModel):
    room_id: int = Field(gt=0)
    available_beds: int = Field(ge=0, le=1000)

    model_config = ConfigDict(extra="forbid")


class PGAvailabilityUpdate(BaseModel):
    rooms: list[RoomBedAvailabilityUpdate] = Field(min_length=1, max_length=100)
    availability_status: AvailabilityStatus

    @model_validator(mode="after")
    def room_ids_are_unique(self):
        room_ids = [room.room_id for room in self.rooms]
        if len(room_ids) != len(set(room_ids)):
            raise ValueError("Each room may appear only once")
        return self

    model_config = ConfigDict(extra="forbid")


class PGAvailabilityConfirmation(BaseModel):
    confirm_rent: bool = False

    model_config = ConfigDict(extra="forbid")


class PGAvailabilityOut(BaseModel):
    pg_id: int
    total_beds: int
    available_beds: int
    availability_status: AvailabilityStatus
    monthly_rent: Decimal
    security_deposit: Decimal | None
    availability_updated_at: datetime | None
    availability_confirmed_at: datetime | None
    rent_confirmed_at: datetime | None
    availability_needs_update: bool


class PGAvailabilityEventOut(BaseModel):
    id: int
    pg_id: int
    event_type: Literal["updated", "confirmed"]
    previous_available_beds: int | None
    new_available_beds: int
    previous_status: AvailabilityStatus | None
    new_status: AvailabilityStatus
    actor_owner_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
