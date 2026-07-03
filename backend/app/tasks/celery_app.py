from celery import Celery

from app.core.config import settings

celery_app = Celery("its_mygo", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    imports=(
        "app.tasks.order_tasks",
        "app.tasks.promotion_tasks",
    ),
    beat_schedule={
        "cancel-expired-unpaid-orders": {
            "task": "order.cancel_expired_unpaid_orders",
            "schedule": settings.celery_cancel_unpaid_interval_seconds,
        },
        "auto-confirm-received-orders": {
            "task": "order.auto_confirm_received_orders",
            "schedule": settings.celery_auto_confirm_interval_seconds,
        },
        "expire-user-coupons": {
            "task": "promotion.expire_user_coupons",
            "schedule": settings.celery_expire_coupon_interval_seconds,
        },
    },
)
