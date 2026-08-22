from pydantic import BaseModel, EmailStr


class GoogleAuthRequest(BaseModel):
    id_token: str  # Google ID token from frontend


class GoogleUserInfo(BaseModel):
    id: str
    email: EmailStr
    name: str
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    verified_email: bool = False