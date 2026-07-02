from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import AdminUser, User
from app.schemas.auth import (
    AdminLoginRequest,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserRegisterRequest,
)


class AuthService:
    async def register_user(self, db: AsyncSession, payload: UserRegisterRequest) -> User:
        existing_user = await self.get_user_by_mobile(db, payload.mobile)
        if existing_user is not None:
            raise AppException(40005, "手机号已注册")
        user = User(
            mobile=payload.mobile,
            password_hash=hash_password(payload.password),
            nickname=payload.nickname,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def login_user(self, db: AsyncSession, payload: LoginRequest) -> TokenResponse:
        user = await self.get_user_by_mobile(db, payload.account)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise UnauthorizedException("账号或密码错误")
        if not user.is_active:
            raise UnauthorizedException("用户已禁用")
        return self._build_token_response(str(user.id), "consumer")

    async def login_admin(self, db: AsyncSession, payload: AdminLoginRequest) -> TokenResponse:
        admin = await self.get_admin_by_username(db, payload.username)
        if admin is None or not verify_password(payload.password, admin.password_hash):
            raise UnauthorizedException("账号或密码错误")
        if not admin.is_active:
            raise UnauthorizedException("管理员已禁用")
        return self._build_token_response(str(admin.id), "admin")

    async def refresh_token(self, payload: RefreshTokenRequest, expected_account_type: str) -> TokenResponse:
        try:
            token_payload = decode_token(payload.refresh_token)
        except ValueError as exc:
            raise UnauthorizedException("刷新令牌无效或已过期") from exc
        if (
            token_payload.get("token_type") != "refresh"
            or token_payload.get("account_type") != expected_account_type
        ):
            raise UnauthorizedException("刷新令牌类型错误")
        return self._build_token_response(str(token_payload["sub"]), expected_account_type)

    async def get_user_by_mobile(self, db: AsyncSession, mobile: str) -> User | None:
        result = await db.execute(select(User).where(User.mobile == mobile))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, db: AsyncSession, user_id: int) -> User | None:
        return await db.get(User, user_id)

    async def get_admin_by_username(self, db: AsyncSession, username: str) -> AdminUser | None:
        result = await db.execute(select(AdminUser).where(AdminUser.username == username))
        return result.scalar_one_or_none()

    async def get_admin_by_id(self, db: AsyncSession, admin_id: int) -> AdminUser | None:
        return await db.get(AdminUser, admin_id)

    def _build_token_response(self, subject: str, account_type: str) -> TokenResponse:
        access_token, _, _ = create_access_token(subject, account_type)
        refresh_token, _, _ = create_refresh_token(subject, account_type)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )


auth_service = AuthService()
