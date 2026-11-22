from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from collections.abc import Awaitable, Callable
from src.config import Settings, get_settings
from src.database import get_db
from src.exceptions import BaseSecurityError
from src.models.accounts import UserModel, UserGroupEnum
from src.security.jwt_manager import JWTAuthManager

bearer_scheme = HTTPBearer()


def get_jwt_auth_manager(settings: Settings = Depends(get_settings)) -> JWTAuthManager:
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
        access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_token_expire_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
) -> UserModel:
    try:
        payload = jwt_manager.decode_access_token(credentials.credentials)
    except BaseSecurityError as error:
        raise _unauthorized(error.message) from error

    user_id = payload.get("user_id")
    if user_id is None:
        raise _unauthorized("Invalid token.")

    user = await db.get(UserModel, user_id, options=[joinedload(UserModel.group)])
    if user is None or not user.is_active:
        raise _unauthorized("User not found or not active.")

    return user


_GROUP_RANK = {
    UserGroupEnum.USER: 0,
    UserGroupEnum.MODERATOR: 1,
    UserGroupEnum.ADMIN: 2,
}


def require_group(minimum: UserGroupEnum) -> Callable[..., Awaitable[UserModel]]:
    async def checker(user: UserModel = Depends(get_current_user)) -> UserModel:
        if _GROUP_RANK[user.group.name] < _GROUP_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions.",
            )
        return user

    return checker
