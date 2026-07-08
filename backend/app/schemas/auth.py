from datetime import date

from pydantic import BaseModel, Field


class UserRegisterRequest(BaseModel):
    mobile: str = Field(min_length=11, max_length=20)
    password: str = Field(min_length=8, max_length=64)
    nickname: str = Field(min_length=1, max_length=50)


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=64)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserRegisterResponse(BaseModel):
    user_id: int


class UserProfileResponse(BaseModel):
    id: int
    mobile: str
    nickname: str
    avatar_url: str | None = None
    gender: str | None = None
    birthday: date | None = None
    email: str | None = None
    level: str
    points: int

    model_config = {"from_attributes": True}


class UserProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=255)
    gender: str | None = Field(default=None, max_length=20)
    birthday: date | None = None
    email: str | None = Field(default=None, max_length=120)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=64)


class AdminProfileResponse(BaseModel):
    id: int
    username: str
    real_name: str
    role: str
    merchant_id: int | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class AdminMenuItem(BaseModel):
    key: str
    label: str
    path: str
    permissions: list[str] = []
