from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MovieSortBy(str, Enum):
    PRICE = "price"
    YEAR = "year"  # release date
    POPULARITY = "popularity"  # number of IMDb votes


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class NamedItemSchema(BaseModel):

    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class NamedItemListResponseSchema(BaseModel):
    items: list[NamedItemSchema]
    total: int
    page: int
    per_page: int


class NameRequestSchema(BaseModel):

    name: NonEmptyStr = Field(max_length=100)


class GenreWithCountSchema(BaseModel):
    id: int
    name: str
    movies_count: int


class MovieCreateSchema(BaseModel):
    name: NonEmptyStr
    year: int
    time: int = Field(gt=0, description="Duration in minutes")
    imdb: float = Field(ge=0, le=10)
    votes: int = Field(ge=0)
    meta_score: float | None = None
    gross: float | None = None
    description: str
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    certification: NonEmptyStr
    genres: list[NonEmptyStr]
    stars: list[NonEmptyStr]
    directors: list[NonEmptyStr]


class MovieUpdateSchema(BaseModel):

    name: NonEmptyStr | None = None
    year: int | None = None
    time: int | None = Field(None, gt=0)
    imdb: float | None = Field(None, ge=0, le=10)
    votes: int | None = Field(None, ge=0)
    meta_score: float | None = None
    gross: float | None = None
    description: str | None = None
    price: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=2)
    certification: NonEmptyStr | None = None
    genres: list[NonEmptyStr] | None = None
    stars: list[NonEmptyStr] | None = None
    directors: list[NonEmptyStr] | None = None

    @model_validator(mode="after")
    def _only_nullable_fields_may_be_null(self) -> "MovieUpdateSchema":
        for field in self.model_fields_set:
            if getattr(self, field) is None and field not in {"meta_score", "gross"}:
                raise ValueError(f"{field} cannot be null")
        return self


class MovieListItemSchema(BaseModel):
    id: int
    name: str
    year: int
    time: int
    imdb: float
    price: Decimal

    model_config = ConfigDict(from_attributes=True)


class MovieDetailSchema(MovieListItemSchema):
    uuid: UUID
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    certification: NamedItemSchema
    genres: list[NamedItemSchema]
    stars: list[NamedItemSchema]
    directors: list[NamedItemSchema]


class MovieListResponseSchema(BaseModel):
    items: list[MovieListItemSchema]
    total: int
    page: int
    per_page: int


class LikeRequestSchema(BaseModel):
    is_like: bool


class RatingRequestSchema(BaseModel):
    score: int = Field(ge=1, le=10)


class MovieStatsSchema(BaseModel):
    likes: int
    dislikes: int
    average_rating: float | None
    ratings_count: int


class CommentCreateSchema(BaseModel):
    text: NonEmptyStr = Field(max_length=2000)
    parent_id: int | None = Field(None, description="Id of the comment this one replies to")


class CommentSchema(BaseModel):
    id: int
    movie_id: int
    user_id: int
    parent_id: int | None
    text: str
    created_at: datetime
    likes_count: int


class NotificationSchema(BaseModel):
    id: int
    message: str
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
