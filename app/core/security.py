from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
import secrets

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str,
    role: str,
    permissions: list[str] | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "role": role,
        "permissions": permissions or [],
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# OTP step-up for privileged logins: the challenge token proves "password OK,
# OTP pending". Short-lived, single-purpose — it can only be exchanged at
# POST /auth/login/verify-otp, never used as an API credential.
CHALLENGE_TOKEN_EXPIRE_MINUTES = 5


def create_login_challenge(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=CHALLENGE_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, "type": "challenge"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_login_challenge(token: str) -> str | None:
    """Return the challenged email, or None if invalid/expired/wrong type."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "challenge":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_refresh_token_value() -> str:
    # Opaque random string — NOT a JWT. Stored + hashed in DB, so it can be
    # revoked server-side (a self-contained JWT refresh token can't be revoked
    # without a blocklist, which is just this table anyway).
    return uuid.uuid4().hex + uuid.uuid4().hex


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


# ========== Password Reset Token Functions ==========

def generate_reset_token() -> str:
    """
    Generate a secure random token for password reset.
    Uses secrets.token_urlsafe for cryptographically secure random tokens.
    Returns a 32-byte (256-bit) URL-safe token.
    """
    return secrets.token_urlsafe(32)


def create_reset_jwt_token(email: str) -> str:
    """
    Create JWT token for password reset.
    Alternative to random token if you prefer JWT-based tokens.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
    payload = {"sub": email, "exp": expire, "type": "reset"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_reset_jwt_token(token: str) -> str | None:
    """
    Verify JWT reset token and return email.
    Returns email if valid, None otherwise.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def verify_reset_token(token: str) -> dict[str, Any] | None:
    """
    Verify a reset token (JWT-based).
    Returns user data if valid, None otherwise.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "reset":
            return None
        return {"email": payload.get("sub")}
    except JWTError:
        return None