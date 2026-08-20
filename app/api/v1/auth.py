from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session
from fastapi import Depends

from app.api.deps import SessionDep, CurrentUser
from app.schemas.user import UserCreate, UserRead, UserLogin
from app.schemas.token import TokenPair, RefreshRequest
from app.repositories import user as user_repo
from app.repositories import token as token_repo
from app.core.security import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, session: SessionDep):
    if user_repo.get_user_by_email(session, data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if user_repo.get_user_by_username(session, data.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    return user_repo.create_user(session, data)


@router.post("/login", response_model=TokenPair)
def login(data: UserLogin, session: SessionDep):
    user = user_repo.get_user_by_email(session, data.email)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    access = create_access_token(subject=user.email, role=user.role)
    refresh = token_repo.issue_refresh_token(session, user.id)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshRequest, session: SessionDep):
    record = token_repo.get_valid_token(session, data.refresh_token)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = session.get(__import__("app.models.user", fromlist=["User"]).User, record.user_id)
    new_refresh = token_repo.rotate_token(session, record)
    access = create_access_token(subject=user.email, role=user.role)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshRequest, session: SessionDep):

    record = token_repo.get_valid_token(
        session,
        data.refresh_token
    )

    if not record:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    token_repo.revoke_token(session, record)    


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser):
    return current_user