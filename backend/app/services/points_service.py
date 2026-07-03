from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.user import PointsLog, User
from app.schemas.user import PointsLogResponse


class PointsService:
    async def change_points(
        self,
        db: AsyncSession,
        user: User,
        *,
        change_points: int,
        source_type: str,
        source_id: int | None = None,
        description: str = "",
        idempotent: bool = True,
    ) -> PointsLog | None:
        if change_points == 0:
            raise AppException(40001, "积分变动不能为 0")
        if idempotent and source_id is not None:
            existing_result = await db.execute(
                select(PointsLog).where(
                    PointsLog.user_id == user.id,
                    PointsLog.source_type == source_type,
                    PointsLog.source_id == source_id,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing is not None:
                return existing

        next_balance = user.points + change_points
        if next_balance < 0:
            raise AppException(40005, "积分余额不足")

        user.points = next_balance
        log = PointsLog(
            user_id=user.id,
            change_points=change_points,
            balance_points=next_balance,
            source_type=source_type,
            source_id=source_id,
            description=description,
        )
        db.add(log)
        return log

    async def list_logs(
        self,
        db: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[PointsLogResponse], int]:
        statement = (
            select(PointsLog)
            .where(PointsLog.user_id == user.id)
            .order_by(PointsLog.created_at.desc(), PointsLog.id.desc())
        )
        all_result = await db.execute(statement)
        all_logs = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [PointsLogResponse.model_validate(log) for log in result.scalars()], len(all_logs)


points_service = PointsService()
