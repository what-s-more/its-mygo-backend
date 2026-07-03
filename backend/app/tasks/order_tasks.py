"""Order related Celery tasks."""

import asyncio

from app.db.session import AsyncSessionLocal
from app.services.order_service import order_service
from app.tasks.celery_app import celery_app


@celery_app.task(name="order.cancel_expired_unpaid_orders")
def cancel_expired_unpaid_orders() -> int:
    """Cancel unpaid orders after the configured payment window."""
    return asyncio.run(_cancel_expired_unpaid_orders())


@celery_app.task(name="order.auto_confirm_received_orders")
def auto_confirm_received_orders() -> int:
    """Auto-confirm shipped orders after the configured receipt window."""
    return asyncio.run(_auto_confirm_received_orders())


async def _cancel_expired_unpaid_orders() -> int:
    async with AsyncSessionLocal() as session:
        return await order_service.cancel_expired_unpaid_orders(session)


async def _auto_confirm_received_orders() -> int:
    async with AsyncSessionLocal() as session:
        return await order_service.auto_confirm_received_orders(session)
