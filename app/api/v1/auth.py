import uuid

from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session
from fastapi import Depends

from app.api.deps import SessionDep, CurrentUser, get_current_user
from app.schemas.google_auth import GoogleAuthRequest
from app.schemas.user import UserCreate, UserRead, UserLogin, SetPasswordRequest, UserUpdateProfile
from app.schemas.token import TokenPair, RefreshRequest
from app.repositories import user as user_repo
from app.repositories import token as token_repo
from app.core.security import verify_password, create_access_token, hash_password
from app.services.email_service import email_service
from app.services.google_auth_service import google_auth_service
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, session: SessionDep):
    if user_repo.get_user_by_email(session, data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if user_repo.get_user_by_username(session, data.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user = user_repo.create_user(session, data)
    
    # Send welcome email
    if settings.SENDGRID_API_KEY:
        try:
            email_service.send_welcome_email(user)
            print(f"Welcome email sent to {user.email}")
        except Exception as e:
            print(f"Failed to send welcome email: {str(e)}")
    
    return user


@router.post("/login", response_model=TokenPair)
def login(data: UserLogin, session: SessionDep):
    user = user_repo.get_user_by_email(session, data.email)
    
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    # Check if user is Google-only (no password set)
    if user.auth_provider == "google" and not user.password_hash:
        raise HTTPException(
            status_code=400, 
            detail="This account was created with Google. Please sign in with Google."
        )
    
    # Verify password
    if not verify_password(data.password, user.password_hash):
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

    user = session.get(User, record.user_id)
    new_refresh = token_repo.rotate_token(session, record)
    access = create_access_token(subject=user.email, role=user.role)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshRequest, session: SessionDep):
    record = token_repo.get_valid_token(session, data.refresh_token)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    token_repo.revoke_token(session, record)    


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser):
    return current_user


@router.put("/profile", response_model=UserRead)
def update_profile(
    profile_data: UserUpdateProfile,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """
    Update user profile (full_name, phone, username).
    """
    # Username uniqueness check
    if profile_data.username:
        if profile_data.username != current_user.username:
            existing = user_repo.get_user_by_username(session, profile_data.username)
            if existing and existing.id != current_user.id:
                raise HTTPException(
                    status_code=400,
                    detail="Username already taken"
                )
            current_user.username = profile_data.username
    
    # Update other fields
    if profile_data.full_name is not None:
        current_user.full_name = profile_data.full_name
    
    if profile_data.phone is not None:
        current_user.phone = profile_data.phone
    
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    
    return current_user


@router.post("/google", response_model=TokenPair)
def google_auth(
    request: GoogleAuthRequest,
    session: SessionDep,
):
    """
    Authenticate with Google ID token.
    """
    # Verify Google token
    google_user = google_auth_service.verify_id_token(request.id_token)
    if not google_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token or Google Auth not configured"
        )
    
    # Check if user exists by email
    user = user_repo.get_user_by_email(session, google_user.email)
    
    if not user:
        # Create new user (Google only)
        username = google_user.email.split('@')[0]
        # Remove special characters for username
        username = ''.join(c for c in username if c.isalnum())
        
        existing = user_repo.get_user_by_username(session, username)
        if existing:
            username = f"{username}_{uuid.uuid4().hex[:6]}"
        
        user = User(
            email=google_user.email,
            username=username,
            full_name=google_user.name,
            email_verified=google_user.verified_email,
            auth_provider="google",
            google_id=google_user.id,
            is_active=True,
            password_hash=None,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        
        if settings.SENDGRID_API_KEY:
            try:
                email_service.send_welcome_email(user)
                print(f"Welcome email sent to {user.email}")
            except Exception as e:
                print(f"Failed to send welcome email: {str(e)}")
    
    else:
        # User exists - link Google account if not already
        if not user.google_id:
            user.google_id = google_user.id
            user.auth_provider = "both" if user.password_hash else "google"
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"✅ Linked Google account to existing user: {user.email}")
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled"
            )
    
    # Generate tokens
    access = create_access_token(subject=user.email, role=user.role)
    refresh = token_repo.issue_refresh_token(session, user.id)
    
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/set-password", response_model=dict)
def set_password(
    data: SetPasswordRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """
    Set password for Google users (so they can also login with email/password).
    """
    # Only Google-only users can set password
    if current_user.auth_provider == "email":
        raise HTTPException(
            status_code=400,
            detail="You already have a password. Use 'change-password' instead."
        )
    
    if current_user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="You already have a password set."
        )
    
    current_user.password_hash = hash_password(data.password)
    current_user.auth_provider = "both"
    session.add(current_user)
    session.commit()
    
    return {"message": "Password set successfully. You can now login with email/password."}