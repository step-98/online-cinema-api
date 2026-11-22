from datetime import timedelta

import pytest

from src.exceptions import BaseSecurityError, InvalidTokenError, TokenExpiredError
from src.security.jwt_manager import JWTAuthManager


@pytest.fixture
def manager():
    return JWTAuthManager("a" * 40, "b" * 40, "HS256", access_token_expire_minutes=15, refresh_token_expire_days=7)


def test_an_access_token_carries_its_data(manager):
    token = manager.create_access_token({"user_id": 7})
    assert manager.decode_access_token(token)["user_id"] == 7


def test_two_refresh_tokens_for_one_user_are_different(manager):
    first = manager.create_refresh_token({"user_id": 7})
    second = manager.create_refresh_token({"user_id": 7})
    assert first != second  # refresh_tokens.token is UNIQUE in the database


def test_an_expired_token_is_reported_as_expired(manager):
    token = manager.create_access_token({"user_id": 7}, expires_delta=timedelta(seconds=-5))
    with pytest.raises(TokenExpiredError):
        manager.decode_access_token(token)


def test_a_token_signed_with_another_key_is_invalid(manager):
    stranger = JWTAuthManager("c" * 40, "d" * 40, "HS256", 15, 7)
    with pytest.raises(InvalidTokenError):
        manager.decode_access_token(stranger.create_access_token({"user_id": 7}))


def test_a_refresh_token_does_not_pass_as_an_access_token(manager):
    with pytest.raises(InvalidTokenError):
        manager.decode_access_token(manager.create_refresh_token({"user_id": 7}))


def test_garbage_is_invalid_and_both_errors_share_one_base_class(manager):
    with pytest.raises(BaseSecurityError):
        manager.decode_refresh_token("not-a-token")
