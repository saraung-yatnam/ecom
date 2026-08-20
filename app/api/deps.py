from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.security import decode_access_token
from app.db.database import get_session
from app.models.user import User, UserRole
from app.repositories.user import get_user_by_email


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)


SessionDep = Annotated[
    Session,
    Depends(get_session),
]


def get_current_user(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={
            "WWW-Authenticate": "Bearer"
        },
    )

    payload = decode_access_token(token)

    if payload is None:
        raise credentials_error

    email = payload.get("sub")

    if not email:
        raise credentials_error

    user = get_user_by_email(
        session,
        email,
    )

    if user is None or not user.is_active:
        raise credentials_error

    return user


CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]


def require_role(*allowed: UserRole):

    def checker(
        user: CurrentUser,
    ) -> User:

        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return user

    return checker