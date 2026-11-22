from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.database import get_db
from src.models.accounts import UserGroupEnum, UserModel
from src.models.cart import CartItemModel
from src.models.movies import (
    CertificationModel,
    CommentLikeModel,
    CommentModel,
    DirectorModel,
    GenreModel,
    MovieLikeModel,
    MovieModel,
    NotificationModel,
    RatingModel,
    StarModel,
    favorite_movies,
)
from src.models.orders import OrderItemModel, OrderModel, OrderStatusEnum
from src.schemas.accounts import MessageResponseSchema
from src.schemas.movies import (
    CommentCreateSchema,
    CommentSchema,
    LikeRequestSchema,
    MovieCreateSchema,
    MovieDetailSchema,
    MovieListResponseSchema,
    MovieSortBy,
    MovieStatsSchema,
    MovieUpdateSchema,
    RatingRequestSchema,
    SortOrder,
)
from src.security.dependencies import get_current_user, require_group

router = APIRouter(prefix="/movies", tags=["movies"])

moderator_only = Depends(require_group(UserGroupEnum.MODERATOR))

NamedModel = TypeVar("NamedModel", GenreModel, StarModel, DirectorModel, CertificationModel)

_SORT_COLUMNS = {
    MovieSortBy.PRICE: MovieModel.price,
    MovieSortBy.YEAR: MovieModel.year,
    MovieSortBy.POPULARITY: MovieModel.votes,
}

_MOVIE_OPTIONS = (
    joinedload(MovieModel.certification),
    selectinload(MovieModel.genres),
    selectinload(MovieModel.stars),
    selectinload(MovieModel.directors),
)


async def _get_or_create(db: AsyncSession, model: type[NamedModel], names: list[str]) -> list[NamedModel]:
    unique_names = list(dict.fromkeys(names))
    if not unique_names:
        return []

    result = await db.scalars(select(model).where(model.name.in_(unique_names)))
    existing = {row.name: row for row in result.all()}

    rows: list[NamedModel] = []
    for name in unique_names:
        row = existing.get(name)
        if row is None:
            row = model(name=name)
            db.add(row)
        rows.append(row)
    return rows


async def _load_movie(db: AsyncSession, movie_id: int) -> MovieModel:
    movie = await db.scalar(select(MovieModel).where(MovieModel.id == movie_id).options(*_MOVIE_OPTIONS))
    if movie is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Movie not found.")
    return movie


async def _ensure_movie_exists(db: AsyncSession, movie_id: int) -> None:
    if await db.scalar(select(MovieModel.id).where(MovieModel.id == movie_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Movie not found.")


async def _movie_stats(db: AsyncSession, movie_id: int) -> MovieStatsSchema:
    likes, dislikes = (
        await db.execute(
            select(
                func.coalesce(func.sum(case((MovieLikeModel.is_like.is_(True), 1), else_=0)), 0),
                func.coalesce(func.sum(case((MovieLikeModel.is_like.is_(False), 1), else_=0)), 0),
            ).where(MovieLikeModel.movie_id == movie_id)
        )
    ).one()
    average, count = (
        await db.execute(
            select(func.avg(RatingModel.score), func.count(RatingModel.score)).where(RatingModel.movie_id == movie_id)
        )
    ).one()
    return MovieStatsSchema(
        likes=int(likes),
        dislikes=int(dislikes),
        average_rating=round(float(average), 2) if average is not None else None,
        ratings_count=int(count),
    )


class CatalogParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        per_page: int = Query(10, ge=1, le=100),
        year: int | None = Query(None, description="Release year"),
        imdb_min: float | None = Query(None, ge=0, le=10, description="Minimum IMDb rating"),
        genre_id: int | None = Query(None, description="Only movies of this genre"),
        q: str | None = Query(None, min_length=1, max_length=100, description="Search text"),
        sort_by: MovieSortBy | None = Query(None),
        order: SortOrder = Query(SortOrder.ASC),
    ) -> None:
        self.page = page
        self.per_page = per_page
        self.year = year
        self.imdb_min = imdb_min
        self.genre_id = genre_id
        self.q = q
        self.sort_by = sort_by
        self.order = order


async def _catalog_page(db: AsyncSession, params: CatalogParams, *extra_filters) -> MovieListResponseSchema:
    filters = [*extra_filters]
    if params.year is not None:
        filters.append(MovieModel.year == params.year)
    if params.imdb_min is not None:
        filters.append(MovieModel.imdb >= params.imdb_min)
    if params.genre_id is not None:
        filters.append(MovieModel.genres.any(GenreModel.id == params.genre_id))
    if params.q:
        text = params.q
        filters.append(
            or_(
                MovieModel.name.icontains(text, autoescape=True),
                MovieModel.description.icontains(text, autoescape=True),
                MovieModel.stars.any(StarModel.name.icontains(text, autoescape=True)),
                MovieModel.directors.any(DirectorModel.name.icontains(text, autoescape=True)),
            )
        )

    total = await db.scalar(select(func.count()).select_from(MovieModel).where(*filters)) or 0

    stmt = select(MovieModel).where(*filters)
    if params.sort_by is not None:
        column = _SORT_COLUMNS[params.sort_by]
        stmt = stmt.order_by(column.desc() if params.order == SortOrder.DESC else column.asc())
    stmt = stmt.order_by(MovieModel.id).offset((params.page - 1) * params.per_page).limit(params.per_page)

    result = await db.scalars(stmt)
    return MovieListResponseSchema.model_validate(
        {
            "items": result.all(),
            "total": total,
            "page": params.page,
            "per_page": params.per_page,
        }
    )


@router.get(
    "/",
    response_model=MovieListResponseSchema,
    summary="List Movies",
    description="Public catalog with pagination, filters, sorting and search "
    "(by title, description, star or director).",
)
async def list_movies(
    params: CatalogParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    return await _catalog_page(db, params)


@router.get(
    "/favorites/",
    response_model=MovieListResponseSchema,
    summary="My Favorite Movies",
    description="The current user's favorites, with the same filters, sorting and search as the catalog.",
)
async def list_favorites(
    params: CatalogParams = Depends(),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    favorite_ids = select(favorite_movies.c.movie_id).where(favorite_movies.c.user_id == user.id)
    return await _catalog_page(db, params, MovieModel.id.in_(favorite_ids))


@router.get(
    "/{movie_id}/",
    response_model=MovieDetailSchema,
    summary="Movie Details",
    responses={404: {"description": "Movie not found."}},
)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)) -> MovieModel:
    return await _load_movie(db, movie_id)


@router.post(
    "/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Movie",
    description="Moderators and admins only. Missing genres, stars, directors and "
    "certification are created automatically by name.",
    dependencies=[moderator_only],
    responses={
        403: {"description": "Not enough permissions."},
        409: {"description": "A movie with this name, year and time already exists."},
    },
)
async def create_movie(data: MovieCreateSchema, db: AsyncSession = Depends(get_db)) -> MovieModel:
    movie = MovieModel(
        name=data.name,
        year=data.year,
        time=data.time,
        imdb=data.imdb,
        votes=data.votes,
        meta_score=data.meta_score,
        gross=data.gross,
        description=data.description,
        price=data.price,
        certification=(await _get_or_create(db, CertificationModel, [data.certification]))[0],
        genres=await _get_or_create(db, GenreModel, data.genres),
        stars=await _get_or_create(db, StarModel, data.stars),
        directors=await _get_or_create(db, DirectorModel, data.directors),
    )
    db.add(movie)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A movie with this name, year and time already exists."
        ) from error
    return movie


@router.patch(
    "/{movie_id}/",
    response_model=MovieDetailSchema,
    summary="Update Movie",
    description="Moderators and admins only. Only the fields that are sent are changed; "
    "a list of genres, stars or directors replaces the existing one.",
    dependencies=[moderator_only],
    responses={
        403: {"description": "Not enough permissions."},
        404: {"description": "Movie not found."},
        409: {"description": "A movie with this name, year and time already exists."},
    },
)
async def update_movie(
    movie_id: int,
    data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
) -> MovieModel:
    movie = await _load_movie(db, movie_id)

    changes = data.model_dump(exclude_unset=True)
    certification = changes.pop("certification", None)
    genres = changes.pop("genres", None)
    stars = changes.pop("stars", None)
    directors = changes.pop("directors", None)

    for field, value in changes.items():
        setattr(movie, field, value)
    if certification is not None:
        movie.certification = (await _get_or_create(db, CertificationModel, [certification]))[0]
    if genres is not None:
        movie.genres = await _get_or_create(db, GenreModel, genres)
    if stars is not None:
        movie.stars = await _get_or_create(db, StarModel, stars)
    if directors is not None:
        movie.directors = await _get_or_create(db, DirectorModel, directors)

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A movie with this name, year and time already exists."
        ) from error
    return movie


@router.delete(
    "/{movie_id}/",
    response_model=MessageResponseSchema,
    summary="Delete Movie",
    description="Moderators and admins only. A movie that someone has purchased cannot be "
    "deleted. Likes, ratings, comments, favorites and cart entries are removed with it; "
    "the response tells how many carts it was in.",
    dependencies=[moderator_only],
    responses={
        403: {"description": "Not enough permissions."},
        404: {"description": "Movie not found."},
        409: {"description": "The movie has been purchased and cannot be deleted."},
    },
)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)) -> MessageResponseSchema:
    await _ensure_movie_exists(db, movie_id)

    purchased = await db.scalar(
        select(OrderItemModel.id)
        .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
        .where(OrderItemModel.movie_id == movie_id, OrderModel.status == OrderStatusEnum.PAID)
        .limit(1)
    )
    if purchased is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="The movie has been purchased by at least one user and cannot be deleted.",
        )

    in_carts = await db.scalar(
        select(func.count()).select_from(CartItemModel).where(CartItemModel.movie_id == movie_id)
    )
    await db.execute(delete(MovieModel).where(MovieModel.id == movie_id))
    await db.commit()

    message = "Movie deleted successfully."
    if in_carts:
        message += f" It was in {in_carts} user cart(s) and has been removed from them."
    return MessageResponseSchema(message=message)


@router.get("/{movie_id}/stats/", response_model=MovieStatsSchema, summary="Movie Likes and Rating")
async def get_movie_stats(movie_id: int, db: AsyncSession = Depends(get_db)) -> MovieStatsSchema:
    await _ensure_movie_exists(db, movie_id)
    return await _movie_stats(db, movie_id)


@router.put(
    "/{movie_id}/like/",
    response_model=MovieStatsSchema,
    summary="Like or Dislike a Movie",
    description="One reaction per user: sending it again replaces the previous one.",
)
async def react_to_movie(
    movie_id: int,
    data: LikeRequestSchema,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MovieStatsSchema:
    await _ensure_movie_exists(db, movie_id)
    await db.merge(MovieLikeModel(user_id=user.id, movie_id=movie_id, is_like=data.is_like))
    await db.commit()
    return await _movie_stats(db, movie_id)


@router.delete("/{movie_id}/like/", response_model=MovieStatsSchema, summary="Remove My Reaction")
async def remove_reaction(
    movie_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MovieStatsSchema:
    await _ensure_movie_exists(db, movie_id)
    await db.execute(
        delete(MovieLikeModel).where(MovieLikeModel.user_id == user.id, MovieLikeModel.movie_id == movie_id)
    )
    await db.commit()
    return await _movie_stats(db, movie_id)


@router.put(
    "/{movie_id}/rating/",
    response_model=MovieStatsSchema,
    summary="Rate a Movie (1-10)",
    description="One rating per user: sending it again replaces the previous one.",
)
async def rate_movie(
    movie_id: int,
    data: RatingRequestSchema,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MovieStatsSchema:
    await _ensure_movie_exists(db, movie_id)
    await db.merge(RatingModel(user_id=user.id, movie_id=movie_id, score=data.score))
    await db.commit()
    return await _movie_stats(db, movie_id)


@router.post(
    "/{movie_id}/favorite/",
    response_model=MessageResponseSchema,
    summary="Add to Favorites",
)
async def add_favorite(
    movie_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    await _ensure_movie_exists(db, movie_id)
    already = await db.scalar(
        select(favorite_movies.c.movie_id).where(
            favorite_movies.c.user_id == user.id, favorite_movies.c.movie_id == movie_id
        )
    )
    if already is None:
        await db.execute(insert(favorite_movies).values(user_id=user.id, movie_id=movie_id))
        await db.commit()
    return MessageResponseSchema(message="Movie added to favorites.")


@router.delete(
    "/{movie_id}/favorite/",
    response_model=MessageResponseSchema,
    summary="Remove from Favorites",
)
async def remove_favorite(
    movie_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    await db.execute(
        delete(favorite_movies).where(favorite_movies.c.user_id == user.id, favorite_movies.c.movie_id == movie_id)
    )
    await db.commit()
    return MessageResponseSchema(message="Movie removed from favorites.")


@router.get(
    "/{movie_id}/comments/",
    response_model=list[CommentSchema],
    summary="List Comments",
    description="All comments of the movie, oldest first. Replies have parent_id set.",
)
async def list_comments(movie_id: int, db: AsyncSession = Depends(get_db)) -> list[CommentSchema]:
    await _ensure_movie_exists(db, movie_id)
    rows = await db.execute(
        select(CommentModel, func.count(CommentLikeModel.user_id))
        .outerjoin(CommentLikeModel, CommentLikeModel.comment_id == CommentModel.id)
        .where(CommentModel.movie_id == movie_id)
        .group_by(CommentModel.id)
        .order_by(CommentModel.created_at, CommentModel.id)
    )
    return [
        CommentSchema(
            id=comment.id,
            movie_id=comment.movie_id,
            user_id=comment.user_id,
            parent_id=comment.parent_id,
            text=comment.text,
            created_at=comment.created_at,
            likes_count=likes_count,
        )
        for comment, likes_count in rows.all()
    ]


@router.post(
    "/{movie_id}/comments/",
    response_model=CommentSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Write a Comment",
    description="Set parent_id to reply to another comment; its author gets a notification.",
)
async def create_comment(
    movie_id: int,
    data: CommentCreateSchema,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommentSchema:
    movie = await db.get(MovieModel, movie_id)
    if movie is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Movie not found.")

    parent = None
    if data.parent_id is not None:
        parent = await db.get(CommentModel, data.parent_id)
        if parent is None or parent.movie_id != movie_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Parent comment not found.")

    comment = CommentModel(movie_id=movie_id, user_id=user.id, parent_id=data.parent_id, text=data.text)
    db.add(comment)
    if parent is not None and parent.user_id != user.id:
        db.add(
            NotificationModel(
                user_id=parent.user_id,
                message=f'Someone replied to your comment on "{movie.name}".',
            )
        )
    await db.commit()
    await db.refresh(comment)

    return CommentSchema(
        id=comment.id,
        movie_id=comment.movie_id,
        user_id=comment.user_id,
        parent_id=comment.parent_id,
        text=comment.text,
        created_at=comment.created_at,
        likes_count=0,
    )
