from datetime import datetime
from decimal import Decimal
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.pg import PGOut, StayType


OwnerRelationship = Literal[
    "property_owner",
    "pg_operator",
    "property_manager",
    "authorized_representative",
]
AccountType = Literal["owner", "user"]


class OwnerRegistration(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr | None = None
    phone_number: str = Field(min_length=7, max_length=20)
    account_type: AccountType = "owner"
    relationship_type: OwnerRelationship | None = None
    password: str = Field(min_length=12, max_length=128)

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Full name cannot be blank")
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        compact = re.sub(r"[ ()-]", "", value.strip())
        if compact.startswith("00"):
            compact = f"+{compact[2:]}"
        digits = compact[1:] if compact.startswith("+") else compact
        if not digits.isdigit() or not 7 <= len(digits) <= 15 or digits[0] == "0":
            raise ValueError(
                "Use an international phone number with country code, "
                "such as +919876543210"
            )
        return f"+{digits}"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value is not None else None

    @model_validator(mode="after")
    def validate_account_type(self):
        if self.account_type == "owner" and self.relationship_type is None:
            raise ValueError("relationship_type is required for owner accounts")
        if self.account_type == "user" and self.relationship_type is not None:
            raise ValueError("relationship_type is only valid for owner accounts")
        return self

    model_config = ConfigDict(extra="forbid")


class OwnerLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    model_config = ConfigDict(extra="forbid")


class AuthLoginRequest(BaseModel):
    phone_number: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        return OwnerRegistration.validate_phone_number(value)

    model_config = ConfigDict(extra="forbid")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    model_config = ConfigDict(extra="forbid")


class OwnerOut(BaseModel):
    id: int
    full_name: str
    email: EmailStr | None
    phone_number: str
    relationship_type: OwnerRelationship | None
    account_status: str
    role: Literal["owner", "admin", "user"]
    is_active: bool
    phone_verified: bool
    verification_status: Literal[
        "unverified",
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    identity_verification_status: Literal[
        "unverified",
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    management_authority_status: Literal[
        "unverified",
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    created_at: datetime
    updated_at: datetime


class OwnerTokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class OwnerVerificationSubmission(BaseModel):
    submission_notes: str | None = Field(default=None, max_length=3000)

    @field_validator("submission_notes")
    @classmethod
    def strip_submission_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    model_config = ConfigDict(extra="forbid")


class OwnerVerificationDocumentSubmission(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    identity_document_type: Literal[
        "national_id",
        "passport",
        "drivers_license",
        "other",
    ]
    authority_document_type: Literal[
        "ownership_deed",
        "lease_agreement",
        "authorization_letter",
        "management_contract",
        "business_license",
        "other",
    ]
    submission_notes: str | None = Field(default=None, max_length=3000)

    @field_validator("legal_name")
    @classmethod
    def strip_legal_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Legal name cannot be blank")
        return value

    model_config = ConfigDict(extra="forbid")


class OwnerVerificationOut(BaseModel):
    owner_id: int
    identity_verification_status: Literal[
        "pending",
        "approved",
        "rejected",
        "needs_resubmission",
    ]
    verification_status: Literal[
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
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OwnerPGUpdate(BaseModel):
    city_id: int | None = Field(default=None, gt=0)
    area_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=3000)
    address: str | None = Field(default=None, min_length=5, max_length=1000)
    stay_type: StayType | None = None
    monthly_rent: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=10,
        decimal_places=2,
    )
    security_deposit: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )
    electricity_included: bool | None = None
    food_available: bool | None = None
    contact_phone: str | None = Field(default=None, max_length=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def require_non_nullable_values(self):
        non_nullable = {
            "city_id",
            "area_id",
            "name",
            "address",
            "stay_type",
            "monthly_rent",
            "electricity_included",
            "food_available",
        }
        for field_name in non_nullable.intersection(self.model_fields_set):
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    @model_validator(mode="after")
    def validate_location_pair(self):
        location_fields = {"city_id", "area_id"}
        supplied = location_fields.intersection(self.model_fields_set)
        if supplied and supplied != location_fields:
            raise ValueError("city_id and area_id must be updated together")
        return self

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        coordinate_fields = {"latitude", "longitude"}
        supplied = coordinate_fields.intersection(self.model_fields_set)
        if supplied and supplied != coordinate_fields:
            raise ValueError("latitude and longitude must be updated together")
        if supplied and ((self.latitude is None) != (self.longitude is None)):
            raise ValueError("latitude and longitude must be provided together")
        return self

    @field_validator("name", "address")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
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

    model_config = ConfigDict(extra="forbid")
