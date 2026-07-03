"""Promotion related Celery tasks."""

import asyncio

from app.db.session import AsyncSessionLocal
from app.services.promotion_service import promotion_service
from app.tasks.celery_app import celery_app


@celery_app.task(name="promotion.expire_user_coupons")
def expire_user_coupons() -> int:
    """Mark unused coupons as expired after their template valid_to time."""
    return asyncio.run(_expire_user_coupons())


async def _expire_user_coupons() -> int:
    async with AsyncSessionLocal() as session:
        return await promotion_service.expire_user_coupons(session)
