import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from src.exceptions import InvalidTokenError, TokenExpiredError


class JWTAuthManager:

    def __init__(
        self,
        secret_key_access: str,
        secret_key_refresh: str,
        algorithm: str,
        access_token_expire_minutes: int,
        refresh_token_expire_days: int,
    ) -> None:
        self._secret_key_access = secret_key_access
        self._secret_key_refresh = secret_key_refresh
        self._algorithm = algorithm
        self._access_ttl = timedelta(minutes=access_token_expire_minutes)
        self._refresh_ttl = timedelta(days=refresh_token_expire_days)

    def _create_token(
        self,
        data: dict[str, Any],
        secret_key: str,
        expires_delta: timedelta,
    ) -> str:
        payload = {
            **data,
            "exp": datetime.now(timezone.utc) + expires_delta,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, secret_key, algorithm=self._algorithm)

    def _decode_token(self, token: str, secret_key: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, secret_key, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError as error:
            raise TokenExpiredError() from error
        except jwt.InvalidTokenError as error:
            raise InvalidTokenError() from error

    def create_access_token(self, data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        return self._create_token(data, self._secret_key_access, expires_delta or self._access_ttl)

    def create_refresh_token(self, data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        return self._create_token(data, self._secret_key_refresh, expires_delta or self._refresh_ttl)

    def decode_access_token(self, token: str) -> dict[str, Any]:
        return self._decode_token(token, self._secret_key_access)

    def decode_refresh_token(self, token: str) -> dict[str, Any]:
        return self._decode_token(token, self._secret_key_refresh)
