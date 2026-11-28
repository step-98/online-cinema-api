import secrets
from datetime import datetime, timezone


def generate_secure_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
