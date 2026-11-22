from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import UserModel
from src.models.movies import CommentLikeModel, CommentModel, NotificationModel
from src.schemas.accounts import MessageResponseSchema
from src.security.dependencies import get_current_user

router = APIRouter(prefix="/comments", tags=["comments"])


@router.post(
    "/{comment_id}/like/",
    response_model=MessageResponseSchema,
    summary="Like a Comment",
    description="Idempotent. The comment's author gets a notification the first time.",
    responses={404: {"description": "Comment not found."}},
)
async def like_comment(
    comment_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    comment = await db.get(CommentModel, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    already_liked = await db.scalar(
        select(CommentLikeModel.comment_id).where(
            CommentLikeModel.user_id == user.id, CommentLikeModel.comment_id == comment_id
        )
    )
    if already_liked is None:
        db.add(CommentLikeModel(user_id=user.id, comment_id=comment_id))
        if comment.user_id != user.id:
            db.add(NotificationModel(user_id=comment.user_id, message="Someone liked your comment."))
        await db.commit()

    return MessageResponseSchema(message="Comment liked.")


@router.delete(
    "/{comment_id}/like/",
    response_model=MessageResponseSchema,
    summary="Remove My Like from a Comment",
)
async def unlike_comment(
    comment_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    await db.execute(
        delete(CommentLikeModel).where(CommentLikeModel.user_id == user.id, CommentLikeModel.comment_id == comment_id)
    )
    await db.commit()
    return MessageResponseSchema(message="Like removed.")
