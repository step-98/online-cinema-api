from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import UserGroupEnum
from src.models.movies import GenreModel, movie_genres
from src.schemas.accounts import MessageResponseSchema
from src.schemas.movies import GenreWithCountSchema, NamedItemSchema, NameRequestSchema
from src.security.dependencies import require_group

router = APIRouter(prefix="/genres", tags=["genres"])

moderator_only = Depends(require_group(UserGroupEnum.MODERATOR))


async def _get_genre(db: AsyncSession, genre_id: int) -> GenreModel:
    genre = await db.get(GenreModel, genre_id)
    if genre is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Genre not found.")
    return genre


@router.get(
    "/",
    response_model=list[GenreWithCountSchema],
    summary="List Genres",
    description="Every genre with the number of movies in it. "
    "Use GET /movies/?genre_id=... to see the movies of a genre.",
)
async def list_genres(db: AsyncSession = Depends(get_db)) -> list[GenreWithCountSchema]:
    rows = await db.execute(
        select(GenreModel.id, GenreModel.name, func.count(movie_genres.c.movie_id))
        .outerjoin(movie_genres, movie_genres.c.genre_id == GenreModel.id)
        .group_by(GenreModel.id, GenreModel.name)
        .order_by(GenreModel.name)
    )
    return [GenreWithCountSchema(id=genre_id, name=name, movies_count=count) for genre_id, name, count in rows.all()]


@router.post(
    "/",
    response_model=NamedItemSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Genre",
    dependencies=[moderator_only],
    responses={409: {"description": "A genre with this name already exists."}},
)
async def create_genre(data: NameRequestSchema, db: AsyncSession = Depends(get_db)) -> GenreModel:
    genre = GenreModel(name=data.name)
    db.add(genre)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A genre with this name already exists.") from error
    return genre


@router.put(
    "/{genre_id}/",
    response_model=NamedItemSchema,
    summary="Rename Genre",
    dependencies=[moderator_only],
    responses={
        404: {"description": "Genre not found."},
        409: {"description": "A genre with this name already exists."},
    },
)
async def rename_genre(genre_id: int, data: NameRequestSchema, db: AsyncSession = Depends(get_db)) -> GenreModel:
    genre = await _get_genre(db, genre_id)
    genre.name = data.name
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A genre with this name already exists.") from error
    return genre


@router.delete(
    "/{genre_id}/",
    response_model=MessageResponseSchema,
    summary="Delete Genre",
    description="The genre is removed from its movies; the movies themselves stay.",
    dependencies=[moderator_only],
    responses={404: {"description": "Genre not found."}},
)
async def delete_genre(genre_id: int, db: AsyncSession = Depends(get_db)) -> MessageResponseSchema:
    await _get_genre(db, genre_id)
    await db.execute(delete(GenreModel).where(GenreModel.id == genre_id))
    await db.commit()
    return MessageResponseSchema(message="Genre deleted successfully.")
