import random
from datetime import datetime,timedelta
from sqlmodel import Session,select
from app.models.otp import OTP
from app.services .email_service import email_service

def generate_otp()->str:
    return ''.join(str(random.randint(0,9)) for _ in range(6))

def create_otp(session: Session,email:str,purpose:str)->str:
    statement=select(OTP).where(
        OTP.email==email,
        OTP.purpose==purpose,
        OTP.is_used==False
    )
    old_otps=session.exec(statement).all()
    for otp in old_otps:
        session.delete(otp)
    session.commit()

    otp_code=generate_otp()
    expires_at=datetime.now()+timedelta(minutes=10)

    new_otp=OTP(
        email=email,
        otp_code=otp_code,
        purpose=purpose,
        expires_at=expires_at
    )
    session.add(new_otp)
    session.commit()
    session.refresh(new_otp)

    send_otp_email(email,otp_code,purpose)
    
    print(f"OTP DEMO:{otp_code}")
    return otp_code

def verify_otp(session: Session, email: str, otp_code: str, purpose: str) -> bool:
    """
    Verify OTP.
    Returns: True if valid, False otherwise
    """
    # ✅ Find the OTP
    statement = select(OTP).where(
        OTP.email == email,
        OTP.otp_code == otp_code,
        OTP.purpose == purpose,
        OTP.is_used == False
    )
    otp = session.exec(statement).first()
    
    # ✅ Check if OTP exists
    if not otp:
        return False
    
    # ✅ Check if expired
    if otp.expires_at < datetime.now():
        return False
    
    
    otp.is_used = True
    session.add(otp)
    session.commit()
    
    return True


def send_otp_email(email: str, otp_code: str, purpose: str):
    """Send OTP via email"""
    purpose_labels = {
        "signup": "account verification",
        "reset_password": "password reset",
        "change_email": "email change"
    }
    
    label = purpose_labels.get(purpose, purpose)
    
    subject = f"Your OTP for {label}"
    
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #4F46E5;">Email Verification</h2>
        <p>Hello,</p>
        <p>Your OTP for <strong>{label}</strong> is:</p>
        
        <div style="background: #f3f4f6; padding: 16px; text-align: center; border-radius: 8px; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1f2937;">
                {otp_code}
            </span>
        </div>
        
        <p style="color: #6b7280; font-size: 14px;">
            This OTP is valid for <strong>10 minutes</strong>.
        </p>
        <p style="color: #6b7280; font-size: 14px;">
            If you didn't request this, please ignore this email.
        </p>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            This is an automated email. Please do not reply.
        </p>
    </div>
    """
    
    # ✅ Use your existing email service
    email_service.send_email(
        to=email,
        subject=subject,
        html_body=html_body
    )


def get_otp_attempts(session: Session, email: str) -> int:
    """Get failed attempts count for an email"""
    statement = select(OTP).where(
        OTP.email == email,
        OTP.is_used == False
    )
    otp = session.exec(statement).first()
    return otp.attempts if otp else 0

def increment_otp_attempts(session: Session, email: str):
    """Increment failed attempts for OTP"""
    statement = select(OTP).where(
        OTP.email == email,
        OTP.is_used == False
    )
    otp = session.exec(statement).first()
    if otp:
        otp.attempts += 1
        session.add(otp)
        session.commit()
