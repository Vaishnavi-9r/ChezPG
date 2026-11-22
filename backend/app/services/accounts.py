from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Owner
from app.schemas.owner import OwnerOut, OwnerRegistration


def owner_response(owner: Owner) -> OwnerOut:
    verification_status = (
        owner.verification.verification_status
        if owner.verification is not None
        else "unverified"
    )
    management_authority_status = (
        owner.verification.management_authority_status
        if owner.verification is not None
        else "unverified"
    )
    return OwnerOut(
        id=owner.id,
        full_name=owner.full_name,
        email=owner.email,
        phone_number=owner.phone_number,
        relationship_type=owner.relationship_type,
        account_status=owner.account_status,
        role=owner.role,
        is_active=owner.is_active,
        phone_verified=owner.phone_verified,
        verification_status=verification_status,
        identity_verification_status=verification_status,
        management_authority_status=management_authority_status,
        created_at=owner.created_at,
        updated_at=owner.updated_at,
    )


def register_account(
    payload: OwnerRegistration,
    db: Session,
) -> OwnerOut:
    owner = Owner(
        full_name=payload.full_name,
        email=payload.email,
        phone_number=payload.phone_number,
        relationship_type=payload.relationship_type,
        password_hash=hash_password(payload.password),
        role=payload.account_type,
        account_status="active",
        is_active=True,
        phone_verified=False,
    )
    try:
        db.add(owner)
        db.commit()
        db.refresh(owner)
        return owner_response(owner)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this phone number or email already exists",
        ) from None
    except Exception:
        db.rollback()
        raise
