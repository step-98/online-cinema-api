import uuid as uuid_lib
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

movie_genres = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)

movie_stars = Table(
    "movie_stars",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("star_id", ForeignKey("stars.id", ondelete="CASCADE"), primary_key=True),
)

movie_directors = Table(
    "movie_directors",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("director_id", ForeignKey("directors.id", ondelete="CASCADE"), primary_key=True),
)


class GenreModel(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    movies: Mapped[List["MovieModel"]] = relationship("MovieModel", secondary=movie_genres, back_populates="genres")

    def __repr__(self) -> str:
        return f"<GenreModel(id={self.id}, name={self.name})>"


class StarModel(Base):
    __tablename__ = "stars"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    movies: Mapped[List["MovieModel"]] = relationship("MovieModel", secondary=movie_stars, back_populates="stars")

    def __repr__(self) -> str:
        return f"<StarModel(id={self.id}, name={self.name})>"


class DirectorModel(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    movies: Mapped[List["MovieModel"]] = relationship(
        "MovieModel", secondary=movie_directors, back_populates="directors"
    )

    def __repr__(self) -> str:
        return f"<DirectorModel(id={self.id}, name={self.name})>"


class CertificationModel(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    movies: Mapped[List["MovieModel"]] = relationship("MovieModel", back_populates="certification")

    def __repr__(self) -> str:
        return f"<CertificationModel(id={self.id}, name={self.name})>"


class MovieModel(Base):
    __tablename__ = "movies"
    __table_args__ = (UniqueConstraint("name", "year", "time", name="unique_movie_constraint"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(Uuid, unique=True, nullable=False, default=uuid_lib.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    time: Mapped[int] = mapped_column(nullable=False)  # duration in minutes
    imdb: Mapped[float] = mapped_column(nullable=False)
    votes: Mapped[int] = mapped_column(nullable=False)
    meta_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    gross: Mapped[Optional[float]] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # RESTRICT: a certification that is still used by movies cannot be deleted.
    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id", ondelete="RESTRICT"), nullable=False)
    certification: Mapped["CertificationModel"] = relationship("CertificationModel", back_populates="movies")

    genres: Mapped[List["GenreModel"]] = relationship("GenreModel", secondary=movie_genres, back_populates="movies")
    stars: Mapped[List["StarModel"]] = relationship("StarModel", secondary=movie_stars, back_populates="movies")
    directors: Mapped[List["DirectorModel"]] = relationship(
        "DirectorModel", secondary=movie_directors, back_populates="movies"
    )

    def __repr__(self) -> str:
        return f"<MovieModel(id={self.id}, name={self.name}, year={self.year})>"


favorite_movies = Table(
    "favorite_movies",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, autoincrement=False),
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True, autoincrement=False),
)


class MovieLikeModel(Base):

    __tablename__ = "movie_likes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    is_like: Mapped[bool] = mapped_column(nullable=False)


class RatingModel(Base):

    __tablename__ = "ratings"
    __table_args__ = (CheckConstraint("score >= 1 AND score <= 10", name="ck_ratings_score_range"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    score: Mapped[int] = mapped_column(nullable=False)


class CommentModel(Base):

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommentLikeModel(Base):
    __tablename__ = "comment_likes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )


class NotificationModel(Base):

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    is_read: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
