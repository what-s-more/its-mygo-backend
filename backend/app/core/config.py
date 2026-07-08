from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "its-mygo"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./its_mygo.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    cors_allow_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]
    cors_allow_origin_regex: str | None = r"^https?://(localhost|127\.0\.0\.1):\d+$"
    upload_dir: str = "uploads"
    upload_max_size_mb: int = 5
    order_payment_expire_minutes: int = 15
    order_auto_confirm_days: int = 7
    celery_cancel_unpaid_interval_seconds: int = 300
    celery_expire_coupon_interval_seconds: int = 300
    celery_auto_confirm_interval_seconds: int = 3600
    alipay_enabled: bool = False
    alipay_gateway_url: str = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    alipay_app_id: str | None = None
    alipay_app_private_key: str | None = None
    alipay_public_key: str | None = None
    alipay_notify_url: str | None = None
    alipay_subject_prefix: str = "一次买够订单"
    alipay_request_timeout_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
