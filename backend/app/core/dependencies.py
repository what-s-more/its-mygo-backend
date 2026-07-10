from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.core.token_blacklist import is_token_blacklisted
from app.db.session import get_db_session
from app.models.user import AdminUser, User
from app.services.auth_service import auth_service

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict:
    if credentials is None:
        raise UnauthorizedException()
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedException("token 无效或已过期") from exc
    if is_token_blacklisted(payload.get("jti")):
        raise UnauthorizedException("token 已失效")
    return payload


async def get_current_user(payload: Annotated[dict, Depends(get_token_payload)], db: DbSession) -> User:
    if payload.get("token_type") != "access" or payload.get("account_type") != "consumer":
        raise ForbiddenException()
    user = await auth_service.get_user_by_id(db, int(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedException("用户不存在或已禁用")
    return user


async def get_current_admin(payload: Annotated[dict, Depends(get_token_payload)], db: DbSession) -> AdminUser:
    if payload.get("token_type") != "access" or payload.get("account_type") != "admin":
        raise ForbiddenException()
    admin = await auth_service.get_admin_by_id(db, int(payload["sub"]))
    if admin is None or not admin.is_active:
        raise UnauthorizedException("管理员不存在或已禁用")
    return admin


async def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        return None
    if is_token_blacklisted(payload.get("jti")):
        return None
    if payload.get("token_type") != "access" or payload.get("account_type") != "consumer":
        return None
    user = await auth_service.get_user_by_id(db, int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user
