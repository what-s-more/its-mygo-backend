from datetime import datetime

from pydantic import BaseModel


class PointsLogResponse(BaseModel):
    id: int
    user_id: int
    change_points: int
    balance_points: int
    source_type: str
    source_id: int | None = None
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PointsAccountResponse(BaseModel):
    user_id: int
    points: int
    sign_in_today: bool
    current_streak_days: int
    today_reward_points: int


class MemberLevelResponse(BaseModel):
    user_id: int
    level: str
    level_name: str
    growth_value_cent: int
    next_level: str | None = None
    next_level_name: str | None = None
    next_level_need_cent: int | None = None
    benefits: list[str]


class SignInResponse(BaseModel):
    signed: bool
    points: int
    reward_points: int
    streak_days: int
    message: str
