from datetime import UTC, datetime

_blacklist: dict[str, datetime] = {}


def add_token_to_blacklist(jti: str, expire_at: datetime) -> None:
    _blacklist[jti] = expire_at
    clear_expired_tokens()


def is_token_blacklisted(jti: str | None) -> bool:
    if not jti:
        return False
    clear_expired_tokens()
    return jti in _blacklist


def clear_expired_tokens() -> None:
    now = datetime.now(UTC)
    expired_keys = [jti for jti, expire_at in _blacklist.items() if expire_at <= now]
    for jti in expired_keys:
        _blacklist.pop(jti, None)
