from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.user import User, UserSignIn
from app.schemas.auth import UserProfileResponse, UserProfileUpdateRequest
from app.schemas.admin import MemberPointsConfig, MemberLevelRule
from app.schemas.user import MemberLevelResponse, PointsAccountResponse, SignInResponse
from app.services.platform_setting_service import platform_setting_service
from app.services.points_service import points_service


class UserService:
    async def update_profile(
        self,
        db: AsyncSession,
        user: User,
        payload: UserProfileUpdateRequest,
    ) -> UserProfileResponse:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(user, key, value)
        await db.commit()
        await db.refresh(user)
        return UserProfileResponse.model_validate(user)

    async def get_points_account(self, db: AsyncSession, user: User) -> PointsAccountResponse:
        config = await platform_setting_service.get_member_points_config(db)
        today = date.today()
        sign_in = await self._get_sign_in_by_date(db, user.id, today)
        latest_sign_in = await self._get_latest_sign_in(db, user.id)
        current_streak = latest_sign_in.streak_days if latest_sign_in else 0
        return PointsAccountResponse(
            user_id=user.id,
            points=user.points,
            sign_in_today=sign_in is not None,
            current_streak_days=current_streak,
            today_reward_points=self._calculate_sign_in_reward(config, current_streak + (0 if sign_in else 1)),
        )

    async def get_member_level(self, db: AsyncSession, user: User) -> MemberLevelResponse:
        config = await platform_setting_service.get_member_points_config(db)
        growth_value = await self._calculate_growth_value_cent(db, user.id)
        level_rule = self._resolve_level(config, growth_value)
        next_rule = self._next_level_rule(config, growth_value)
        level = level_rule.level
        user.level = level
        await db.commit()
        return MemberLevelResponse(
            user_id=user.id,
            level=level,
            level_name=level_rule.name,
            growth_value_cent=growth_value,
            next_level=next_rule.level if next_rule else None,
            next_level_name=next_rule.name if next_rule else None,
            next_level_need_cent=max(0, next_rule.threshold_cent - growth_value) if next_rule else None,
            benefits=level_rule.benefits,
        )

    async def sign_in(self, db: AsyncSession, user: User) -> SignInResponse:
        config = await platform_setting_service.get_member_points_config(db)
        today = date.today()
        existing = await self._get_sign_in_by_date(db, user.id, today)
        if existing is not None:
            return SignInResponse(
                signed=True,
                points=user.points,
                reward_points=0,
                streak_days=existing.streak_days,
                message="今日已签到",
            )
        yesterday = today - timedelta(days=1)
        yesterday_sign_in = await self._get_sign_in_by_date(db, user.id, yesterday)
        streak_days = (yesterday_sign_in.streak_days + 1) if yesterday_sign_in else 1
        reward_points = self._calculate_sign_in_reward(config, streak_days)
        sign_in = UserSignIn(
            user_id=user.id,
            sign_date=today,
            streak_days=streak_days,
            reward_points=reward_points,
        )
        db.add(sign_in)
        await points_service.change_points(
            db,
            user,
            change_points=reward_points,
            source_type="sign_in",
            source_id=int(today.strftime("%Y%m%d")),
            description=f"每日签到奖励，连续 {streak_days} 天",
        )
        await db.commit()
        return SignInResponse(
            signed=True,
            points=user.points,
            reward_points=reward_points,
            streak_days=streak_days,
            message="签到成功",
        )

    async def _calculate_growth_value_cent(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.coalesce(func.sum(Order.pay_amount_cent), 0)).where(
                Order.user_id == user_id,
                Order.status.in_(["completed", "closed", "after_sale"]),
            )
        )
        return int(result.scalar_one() or 0)

    async def _get_sign_in_by_date(self, db: AsyncSession, user_id: int, sign_date: date) -> UserSignIn | None:
        result = await db.execute(
            select(UserSignIn).where(UserSignIn.user_id == user_id, UserSignIn.sign_date == sign_date)
        )
        return result.scalar_one_or_none()

    async def _get_latest_sign_in(self, db: AsyncSession, user_id: int) -> UserSignIn | None:
        result = await db.execute(
            select(UserSignIn)
            .where(UserSignIn.user_id == user_id)
            .order_by(UserSignIn.sign_date.desc(), UserSignIn.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _calculate_sign_in_reward(self, config: MemberPointsConfig, streak_days: int) -> int:
        reward = config.sign_in_base_points + max(0, streak_days - 1) * config.sign_in_streak_increment
        return min(config.sign_in_max_points, reward)

    def _resolve_level(self, config: MemberPointsConfig, growth_value_cent: int) -> MemberLevelRule:
        rules = sorted(config.level_rules, key=lambda item: item.threshold_cent, reverse=True)
        for rule in rules:
            if growth_value_cent >= rule.threshold_cent:
                return rule
        return min(config.level_rules, key=lambda item: item.threshold_cent)

    def _next_level_rule(self, config: MemberPointsConfig, growth_value_cent: int) -> MemberLevelRule | None:
        ascending_rules = sorted(config.level_rules, key=lambda item: item.threshold_cent)
        for rule in ascending_rules:
            if growth_value_cent < rule.threshold_cent:
                return rule
        return None


user_service = UserService()
