from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import UserModel
from src.models.movies import NotificationModel
from src.schemas.accounts import MessageResponseSchema
from src.schemas.movies import NotificationSchema
from src.security.dependencies import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "/",
    response_model=list[NotificationSchema],
    summary="My Notifications",
    description="Replies and likes on the current user's comments, newest first (up to 100).",
)
async def list_notifications(
    unread_only: bool = Query(False),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationModel]:
    stmt = select(NotificationModel).where(NotificationModel.user_id == user.id)
    if unread_only:
        stmt = stmt.where(NotificationModel.is_read.is_(False))
    stmt = stmt.order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc()).limit(100)
    return list((await db.scalars(stmt)).all())


@router.post(
    "/{notification_id}/read/",
    response_model=MessageResponseSchema,
    summary="Mark Notification as Read",
    responses={404: {"description": "Notification not found."}},
)
async def mark_notification_read(
    notification_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    notification = await db.get(NotificationModel, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found.")

    notification.is_read = True
    await db.commit()
    return MessageResponseSchema(message="Notification marked as read.")
