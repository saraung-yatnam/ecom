import hashlib
from datetime import datetime, timedelta, timezone
import uuid

from sqlmodel import Session, select
from app.models.refresh_token import RefreshToken
from app.core.config import settings
from app.core.security import create_refresh_token_value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(session: Session, user_id: uuid.UUID) -> str:
    raw = create_refresh_token_value()
    record = RefreshToken(
        user_id=user_id,
        token_hash=_hash(raw),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    session.add(record)
    session.commit()
    return raw  # only the raw value is ever sent to the client


def get_valid_token(session: Session, raw_token: str) -> RefreshToken | None:
    record = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(raw_token))
    ).first()
    if not record or record.revoked or record.expires_at < datetime.now(timezone.utc):
        return None
    return record


def revoke_token(session: Session, record: RefreshToken) -> None:
    record.revoked = True
    session.add(record)
    session.commit()


def rotate_token(session: Session, old_record: RefreshToken) -> str:
    """Revoke old refresh token, issue a new one. Prevents replay of stolen tokens."""
    revoke_token(session, old_record)
    return issue_refresh_token(session, old_record.user_id)