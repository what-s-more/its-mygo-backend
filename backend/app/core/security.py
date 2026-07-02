from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    password_digest = sha256(password.encode("utf-8")).digest()
    return bcrypt.hashpw(password_digest, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    password_digest = sha256(password.encode("utf-8")).digest()
    return bcrypt.checkpw(password_digest, password_hash.encode("utf-8"))


def create_token(
    *,
    subject: str,
    account_type: str,
    token_type: str,
    expires_delta: timedelta,
) -> tuple[str, datetime, str]:
    expire_at = datetime.now(UTC) + expires_delta
    jti = str(uuid4())
    payload = {
        "sub": subject,
        "account_type": account_type,
        "token_type": token_type,
        "exp": expire_at,
        "iat": datetime.now(UTC),
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expire_at, jti


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("invalid token") from exc


def create_access_token(subject: str, account_type: str) -> tuple[str, datetime, str]:
    return create_token(
        subject=subject,
        account_type=account_type,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )


def create_refresh_token(subject: str, account_type: str) -> tuple[str, datetime, str]:
    return create_token(
        subject=subject,
        account_type=account_type,
        token_type="refresh",
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
    )
