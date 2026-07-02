from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.core.dependencies import DbSession, bearer_scheme, get_current_user
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.core.token_blacklist import add_token_to_blacklist
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserProfileResponse,
    UserRegisterRequest,
    UserRegisterResponse,
)
from app.services.auth_service import auth_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "module": "auth"}


@router.post("/register", response_model=ApiResponse[UserRegisterResponse])
async def register(payload: UserRegisterRequest, db: DbSession) -> ApiResponse[UserRegisterResponse]:
    user = await auth_service.register_user(db, payload)
    return success(UserRegisterResponse(user_id=user.id))


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(payload: LoginRequest, db: DbSession) -> ApiResponse[TokenResponse]:
    token = await auth_service.login_user(db, payload)
    return success(token)


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh(payload: RefreshTokenRequest) -> ApiResponse[TokenResponse]:
    token = await auth_service.refresh_token(payload, "consumer")
    return success(token)


@router.post("/logout", response_model=ApiResponse[None])
async def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> ApiResponse[None]:
    if credentials is None:
        raise UnauthorizedException()
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedException("token 无效或已过期") from exc
    expire_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    add_token_to_blacklist(payload["jti"], expire_at)
    return success(None)


@router.get("/me", response_model=ApiResponse[UserProfileResponse])
async def me(current_user: User = Depends(get_current_user)) -> ApiResponse[UserProfileResponse]:
    return success(UserProfileResponse.model_validate(current_user))
