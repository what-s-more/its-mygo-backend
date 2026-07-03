from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminOperationLog, AdminUser
from app.schemas.admin import AdminOperationLogResponse


class AdminLogService:
    async def record(
        self,
        db: AsyncSession,
        admin: AdminUser,
        *,
        action: str,
        resource_type: str,
        resource_id: int | None = None,
        description: str = "",
    ) -> AdminOperationLog:
        log = AdminOperationLog(
            admin_id=admin.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
        )
        db.add(log)
        return log

    async def list_logs(
        self,
        db: AsyncSession,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[AdminOperationLogResponse], int]:
        statement = select(AdminOperationLog)
        if action:
            statement = statement.where(AdminOperationLog.action == action)
        if resource_type:
            statement = statement.where(AdminOperationLog.resource_type == resource_type)
        statement = statement.order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        all_result = await db.execute(statement)
        all_logs = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [AdminOperationLogResponse.model_validate(log) for log in result.scalars()], len(all_logs)


admin_log_service = AdminLogService()
