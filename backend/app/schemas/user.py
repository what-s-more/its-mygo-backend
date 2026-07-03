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
