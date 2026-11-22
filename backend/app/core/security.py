from datetime import datetime, timedelta, timezone
import secrets

import jwt
from pwdlib import PasswordHash

from app.core.config import settings


password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash(secrets.token_urlsafe(32))
TOKEN_ISSUER = "chezpg-api"
ACCESS_TOKEN_MINUTES = 30


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)


def create_access_token(owner_id: int, token_version: int = 0) -> str:
    secret = settings.owner_token_secret
    if secret is None or len(secret) < 32:
        raise ValueError("Owner token signing secret is not configured securely")

    now = datetime.now(timezone.utc)
    expiry_minutes = settings.access_token_expiry_minutes
    return jwt.encode(
        {
            "sub": str(owner_id),
            "iat": now,
            "exp": now + timedelta(minutes=expiry_minutes),
            "iss": TOKEN_ISSUER,
            "ver": token_version,
        },
        secret,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> int:
    return decode_access_token_with_version(token)[0]


def decode_access_token_with_version(token: str) -> tuple[int, int]:
    secret = settings.owner_token_secret
    if secret is None or len(secret) < 32:
        raise ValueError("Owner token signing secret is not configured securely")

    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=TOKEN_ISSUER,
    )
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("Invalid token subject")
    try:
        owner_id = int(subject)
    except ValueError as exc:
        raise jwt.InvalidTokenError("Invalid token subject") from exc
    if owner_id < 1:
        raise jwt.InvalidTokenError("Invalid token subject")
    token_version = payload.get("ver", 0)
    if type(token_version) is not int or token_version < 0:
        raise jwt.InvalidTokenError("Invalid token version")
    return owner_id, token_version
