import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from sqlmodel import Session,select
from pydantic import BaseModel, EmailStr

from app.api.deps import SessionDep, CurrentUser, CurrentUser
from app.schemas.google_auth import GoogleAuthRequest
from app.schemas.user import UserCreate, UserRead, UserLogin, SetPasswordRequest, UserUpdateProfile
from app.schemas.token import TokenPair, RefreshRequest
from app.schemas.otp import OTPInitiateRequest,OTPVerifyRequest
from app.repositories import user as user_repo
from app.repositories import token as token_repo
from app.core.security import verify_password, create_access_token, hash_password, generate_reset_token
from app.services.email_service import email_service
from app.services.google_auth_service import google_auth_service
from app.services.otp_service import create_otp,verify_otp,increment_otp_attempts,get_otp_attempts
from app.core.config import settings
from app.models.user import User
from app.models.otp import OTP
from app.models.password_reset import PasswordResetToken

router = APIRouter(prefix="/auth", tags=["auth"])


# ========== Request Schemas ==========

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ========== Authentication Endpoints ==========

# @router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
# def register(data: UserCreate, session: SessionDep):
#     if user_repo.get_user_by_email(session, data.email):
#         raise HTTPException(status_code=400, detail="Email already registered")
#     if user_repo.get_user_by_username(session, data.username):
#         raise HTTPException(status_code=400, detail="Username already taken")
    
#     user = user_repo.create_user(session, data)
    
#     # Send welcome email
#     if settings.SENDGRID_API_KEY:
#         try:
#             email_service.send_welcome_email(user)
#             print(f"✅ Welcome email sent to {user.email}")
#         except Exception as e:
#             print(f"❌ Failed to send welcome email: {str(e)}")
    
#     return user

@router.post("/register/initiate")
def initiate_registration(
    request: OTPInitiateRequest,
    session: SessionDep,
):
    """
    Step 1: Send OTP to user's email for verification.
    """
    # ✅ Check if email already registered
    existing_user = user_repo.get_user_by_email(session, request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # ✅ Check rate limiting (max 3 attempts per hour)
    from datetime import datetime, timedelta
    statement = select(OTP).where(
        OTP.email == request.email,
        OTP.created_at > datetime.now() - timedelta(hours=1)
    )
    recent_otps = session.exec(statement).all()
    if len(recent_otps) >= 3:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests. Please wait 1 hour."
        )
    
    # ✅ Generate and send OTP
    create_otp(session, request.email, "signup")
    
    return {
        "message": "OTP sent to your email",
        "email": request.email,
        "expires_in": "10 minutes"
    }


@router.post("/register/verify")
def verify_registration(
    request: OTPVerifyRequest,
    session: SessionDep,
):
    """
    Step 2: Verify OTP and create user account.
    """
    # ✅ Check if email already registered (double-check)
    existing_user = user_repo.get_user_by_email(session, request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # ✅ Check if username is taken
    existing_username = user_repo.get_user_by_username(session, request.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
    
    # ✅ Verify OTP
    is_valid = verify_otp(session, request.email, request.otp_code, "signup")
    if not is_valid:
        # ✅ Increment failed attempts
        increment_otp_attempts(session, request.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP"
        )
    
    # ✅ OTP verified - Create user
    user_data = UserCreate(
        email=request.email,
        username=request.username,
        password=request.password,
        full_name=request.full_name,
        phone=request.phone,
    )
    
    user = user_repo.create_user(session, user_data)
    
    # ✅ Send welcome email
    if settings.SENDGRID_API_KEY:
        try:
            email_service.send_welcome_email(user)
            print(f"✅ Welcome email sent to {user.email}")
        except Exception as e:
            print(f"❌ Failed to send welcome email: {str(e)}")
    
    return {
        "message": "Account created successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
        }
    }


@router.post("/register/resend-otp")
def resend_otp(
    request: OTPInitiateRequest,
    session: SessionDep,
):
    """
    Resend OTP for registration.
    """
    # ✅ Check if email already registered
    existing_user = user_repo.get_user_by_email(session, request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # ✅ Generate and send new OTP
    create_otp(session, request.email, "signup")
    
    return {
        "message": "OTP resent to your email",
        "email": request.email,
        "expires_in": "10 minutes"
    }


    
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
    current_user: CurrentUser,
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
    
    if profile_data.push_notifications_enabled is not None:
        current_user.push_notifications_enabled = profile_data.push_notifications_enabled
    
    if profile_data.email_notifications_enabled is not None:
        current_user.email_notifications_enabled = profile_data.email_notifications_enabled
    
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
                print(f"✅ Welcome email sent to {user.email}")
            except Exception as e:
                print(f"❌ Failed to send welcome email: {str(e)}")
    
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
    current_user: CurrentUser,
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


# ========== Password Reset Endpoints ==========

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    request: ForgotPasswordRequest,
    session: SessionDep,
    background_tasks: BackgroundTasks, 
):
    """
    Request password reset link.
    If email exists, send reset link. Always return 200 OK for security.
    """
    # Find user by email
    user = user_repo.get_user_by_email(session, request.email)
    
    # Always return 200 OK (security: don't reveal if email exists)
    if not user:
        print(f"⚠️ Password reset requested for non-existent email: {request.email}")
        return {"message": "If an account with this email exists, a reset link has been sent."}
    
    # Check if user has a password (Google-only users can't reset password)
    if not user.password_hash:
        print(f"⚠️ Password reset requested for Google-only user: {user.email}")
        return {"message": "If an account with this email exists, a reset link has been sent."}
    
    # Delete any existing reset tokens for this user
    session.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id
    ).delete()
    session.commit()
    
    # Generate reset token (valid for 1 hour)
    token = generate_reset_token()
    expires_at = datetime.utcnow() + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
    
    # Store token in database
    reset_token = PasswordResetToken(
        token=token,
        user_id=user.id,
        expires_at=expires_at,
        used=False,
    )
    session.add(reset_token)
    session.commit()
    
    # Send email in background
    background_tasks.add_task(
        email_service.send_password_reset_email,
        user_email=user.email,
        user_name=user.full_name or user.username,
        reset_token=token,
    )
    
    print(f"✅ Password reset token generated for {user.email}")
    return {"message": "If an account with this email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    request: ResetPasswordRequest,
    session: SessionDep,
):
    """
    Reset password using token.
    """
    # Get token from database
    reset_token = session.query(PasswordResetToken).filter(
        PasswordResetToken.token == request.token,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()
    
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    
    # Get user
    user = session.get(User, reset_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Update password
    user.password_hash = hash_password(request.new_password)
    user.auth_provider = "both" if user.google_id else "email"
    
    # Mark token as used
    reset_token.used = True
    
    session.add(user)
    session.add(reset_token)
    session.commit()
    
    print(f"✅ Password reset successful for {user.email}")
    return {"message": "Password reset successfully. You can now login with your new password."}


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    request: ChangePasswordRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    """
    Change password for logged-in user.
    Requires current password for verification.
    """
    # Check if user has a password (Google-only users can't change password via this endpoint)
    if not current_user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You don't have a password set. Use 'set-password' endpoint.",
        )
    
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    
    # Update password
    current_user.password_hash = hash_password(request.new_password)
    session.add(current_user)
    session.commit()
    
    print(f"✅ Password changed successfully for {current_user.email}")
    return {"message": "Password changed successfully."}