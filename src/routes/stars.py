from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import UserGroupEnum
from src.models.movies import StarModel
from src.schemas.accounts import MessageResponseSchema
from src.schemas.movies import NamedItemListResponseSchema, NamedItemSchema, NameRequestSchema
from src.security.dependencies import require_group

router = APIRouter(prefix="/stars", tags=["stars"])

moderator_only = Depends(require_group(UserGroupEnum.MODERATOR))


async def _get_star(db: AsyncSession, star_id: int) -> StarModel:
    star = await db.get(StarModel, star_id)
    if star is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Star not found.")
    return star


@router.get("/", response_model=NamedItemListResponseSchema, summary="List Stars")
async def list_stars(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> NamedItemListResponseSchema:
    total = await db.scalar(select(func.count()).select_from(StarModel)) or 0
    result = await db.scalars(
        select(StarModel).order_by(StarModel.name, StarModel.id).offset((page - 1) * per_page).limit(per_page)
    )
    return NamedItemListResponseSchema.model_validate(
        {"items": result.all(), "total": total, "page": page, "per_page": per_page}
    )


@router.post(
    "/",
    response_model=NamedItemSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Star",
    dependencies=[moderator_only],
    responses={409: {"description": "A star with this name already exists."}},
)
async def create_star(data: NameRequestSchema, db: AsyncSession = Depends(get_db)) -> StarModel:
    star = StarModel(name=data.name)
    db.add(star)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A star with this name already exists.") from error
    return star


@router.put(
    "/{star_id}/",
    response_model=NamedItemSchema,
    summary="Rename Star",
    dependencies=[moderator_only],
    responses={
        404: {"description": "Star not found."},
        409: {"description": "A star with this name already exists."},
    },
)
async def rename_star(star_id: int, data: NameRequestSchema, db: AsyncSession = Depends(get_db)) -> StarModel:
    star = await _get_star(db, star_id)
    star.name = data.name
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A star with this name already exists.") from error
    return star


@router.delete(
    "/{star_id}/",
    response_model=MessageResponseSchema,
    summary="Delete Star",
    description="The star is removed from their movies; the movies themselves stay.",
    dependencies=[moderator_only],
    responses={404: {"description": "Star not found."}},
)
async def delete_star(star_id: int, db: AsyncSession = Depends(get_db)) -> MessageResponseSchema:
    await _get_star(db, star_id)
    await db.execute(delete(StarModel).where(StarModel.id == star_id))
    await db.commit()
    return MessageResponseSchema(message="Star deleted successfully.")
