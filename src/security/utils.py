import secrets
from datetime import datetime, timezone


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a secure random token.

    Returns:
        str: Securely generated token.
    """
    return secrets.token_urlsafe(length)


def as_utc(value: datetime) -> datetime:
    """
    Return the given datetime as an aware UTC datetime.

    SQLite returns naive datetimes (the zone is lost on save), PostgreSQL returns
    aware ones. Naive values are assumed to be UTC already, because that is how
    we store them; aware values are converted, not just relabelled.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
