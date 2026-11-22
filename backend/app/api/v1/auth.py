from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    get_authenticated_account,
)
from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models import Owner
from app.schemas.auth import AuthMessageOut
from app.schemas.owner import (
    AuthLoginRequest,
    ChangePasswordRequest,
    OwnerOut,
    OwnerRegistration,
    OwnerTokenOut,
)
from app.services.accounts import owner_response, register_account

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=OwnerOut,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: OwnerRegistration,
    db: Session = Depends(get_db),
):
    return register_account(payload, db)


@router.post("/login", response_model=OwnerTokenOut)
def login(
    payload: AuthLoginRequest,
    db: Session = Depends(get_db),
):
    if settings.owner_token_secret is None or len(settings.owner_token_secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )

    account = db.scalar(
        select(Owner).where(Owner.phone_number == payload.phone_number)
    )
    password_matches = verify_password(
        payload.password,
        account.password_hash if account is not None else DUMMY_PASSWORD_HASH,
    )
    if (
        account is None
        or not password_matches
        or account.account_status != "active"
        or not account.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone number or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = create_access_token(account.id, account.token_version)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from None
    return OwnerTokenOut(
        access_token=token,
        expires_in=settings.access_token_expiry_minutes * 60,
    )


@router.get("/me", response_model=OwnerOut)
def me(account: Owner = Depends(get_authenticated_account)):
    return owner_response(account)


@router.post("/change-password", response_model=AuthMessageOut)
def change_password(
    payload: ChangePasswordRequest,
    account: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if verify_password(payload.new_password, account.password_hash):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must differ from the current password",
        )

    try:
        account.password_hash = hash_password(payload.new_password)
        account.token_version += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AuthMessageOut(message="Password updated; sign in again")
