import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import PlatformSetting
from app.schemas.admin import MemberPointsConfig


class PlatformSettingService:
    MEMBER_POINTS_KEY = "member_points"

    DEFAULT_MEMBER_POINTS_CONFIG = MemberPointsConfig(
        level_rules=[
            {
                "level": "normal",
                "name": "普通会员",
                "threshold_cent": 0,
                "benefits": ["基础积分", "优惠券领取"],
                "sign_in_bonus_points": 0,
                "max_points_discount_percent": None,
                "points_multiplier": 1.0,
                "benefit_description": "可领取平台优惠券并参与基础积分活动",
            },
            {
                "level": "silver",
                "name": "银卡会员",
                "threshold_cent": 50000,
                "benefits": ["签到加成", "会员活动"],
                "sign_in_bonus_points": 1,
                "max_points_discount_percent": 12,
                "points_multiplier": 1.1,
                "benefit_description": "每日签到额外积分，订单积分抵扣上限提升",
            },
            {
                "level": "gold",
                "name": "金卡会员",
                "threshold_cent": 200000,
                "benefits": ["签到加成", "生日礼券", "优先客服"],
                "sign_in_bonus_points": 2,
                "max_points_discount_percent": 15,
                "points_multiplier": 1.2,
                "benefit_description": "更高积分权益，并享受优先客服",
            },
            {
                "level": "diamond",
                "name": "钻石会员",
                "threshold_cent": 500000,
                "benefits": ["签到加成", "生日礼券", "专属客服", "免邮权益"],
                "sign_in_bonus_points": 3,
                "max_points_discount_percent": 20,
                "points_multiplier": 1.5,
                "benefit_description": "最高等级权益，适合高频消费用户",
            },
        ],
        sign_in_base_points=2,
        sign_in_streak_increment=1,
        sign_in_max_points=10,
        points_to_yuan_rate=100,
        max_points_discount_percent=10,
    )

    async def get_member_points_config(self, db: AsyncSession) -> MemberPointsConfig:
        setting = await self._get_setting(db, self.MEMBER_POINTS_KEY)
        if setting is None:
            return self.DEFAULT_MEMBER_POINTS_CONFIG
        try:
            return self._normalize_member_points_config(json.loads(setting.value_json))
        except (json.JSONDecodeError, ValueError):
            return self.DEFAULT_MEMBER_POINTS_CONFIG

    async def update_member_points_config(self, db: AsyncSession, payload: MemberPointsConfig) -> MemberPointsConfig:
        normalized = self._normalize_member_points_config(payload.model_dump())
        setting = await self._get_setting(db, self.MEMBER_POINTS_KEY)
        value_json = normalized.model_dump_json()
        if setting is None:
            db.add(PlatformSetting(key=self.MEMBER_POINTS_KEY, value_json=value_json))
        else:
            setting.value_json = value_json
        await db.commit()
        return normalized

    async def _get_setting(self, db: AsyncSession, key: str) -> PlatformSetting | None:
        result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
        return result.scalar_one_or_none()

    def _normalize_member_points_config(self, payload: dict) -> MemberPointsConfig:
        default = self.DEFAULT_MEMBER_POINTS_CONFIG.model_dump()
        merged = {**default, **payload}
        rules = payload.get("level_rules") or default["level_rules"]
        merged["level_rules"] = [
            {
                "sign_in_bonus_points": 0,
                "max_points_discount_percent": None,
                "points_multiplier": 1.0,
                "benefit_description": None,
                **rule,
            }
            for rule in rules
        ]
        config = MemberPointsConfig.model_validate(merged)
        ordered_rules = sorted(config.level_rules, key=lambda item: item.threshold_cent)
        return config.model_copy(update={"level_rules": ordered_rules})


platform_setting_service = PlatformSettingService()
