from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.pg import PGOut
from app.schemas.availability import AvailabilityStatus


class OwnerPGOut(PGOut):
    area_name: str
    is_active: bool
    total_available_beds: int
    total_beds: int
    availability_status: AvailabilityStatus
    availability_updated_at: datetime | None
    availability_confirmed_at: datetime | None
    availability_is_stale: bool

    model_config = ConfigDict(from_attributes=True)


class OwnerDashboardOut(BaseModel):
    total_listings: int
    active_listings: int
    pending_verification: int
    approved_listings: int
    rejected_listings: int
    needs_availability_update: int
    zero_available_beds: int
    full_listings: int
    listings_with_available_beds: int
