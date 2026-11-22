from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import (
    ActivationTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)
from src.schemas.accounts import MessageResponseSchema, UserGroupUpdateRequestSchema
from src.security.dependencies import require_group

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_group(UserGroupEnum.ADMIN))],
)


@router.patch(
    "/users/{user_id}/group/",
    response_model=MessageResponseSchema,
    summary="Change User Group",
    responses={
        403: {"description": "Not enough permissions."},
        404: {"description": "User not found."},
    },
)
async def change_user_group(
    user_id: int,
    data: UserGroupUpdateRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    user = await db.get(UserModel, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    group_id = await db.scalar(select(UserGroupModel.id).where(UserGroupModel.name == data.group))
    if group_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User group not found.",
        )

    try:
        user.group_id = group_id
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while changing the group.",
        ) from error

    return MessageResponseSchema(message="User group changed successfully.")


@router.post(
    "/users/{user_id}/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Manually",
    responses={
        403: {"description": "Not enough permissions."},
        404: {"description": "User not found."},
    },
)
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    user = await db.get(UserModel, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    try:
        user.is_active = True
        await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user_id))
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while activating the user.",
        ) from error

    return MessageResponseSchema(message="User activated successfully.")
