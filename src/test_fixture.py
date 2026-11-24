import argparse
import asyncio
import os
from decimal import Decimal
from typing import TypedDict, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import engine, get_db_contextmanager
from src.models.accounts import UserGroupEnum, UserGroupModel, UserModel
from src.models.movies import CertificationModel, DirectorModel, GenreModel, MovieModel, StarModel

DEFAULT_PASSWORD = "Demo1234!"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)

DEMO_USERS = {
    "demo.user@example.com": UserGroupEnum.USER,
    "demo.moderator@example.com": UserGroupEnum.MODERATOR,
    "demo.admin@example.com": UserGroupEnum.ADMIN,
}


class DemoMovie(TypedDict):
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    price: str
    certification: str
    genres: list[str]
    stars: list[str]
    directors: list[str]
    description: str


DEMO_MOVIES: list[DemoMovie] = [
    {
        "name": "The Shawshank Redemption",
        "year": 1994,
        "time": 142,
        "imdb": 9.3,
        "votes": 3000000,
        "price": "7.99",
        "certification": "R",
        "genres": ["Drama"],
        "stars": ["Tim Robbins", "Morgan Freeman"],
        "directors": ["Frank Darabont"],
        "description": "A banker sentenced to prison builds an unlikely friendship and never gives up hope.",
    },
    {
        "name": "The Godfather",
        "year": 1972,
        "time": 175,
        "imdb": 9.2,
        "votes": 2100000,
        "price": "9.99",
        "certification": "R",
        "genres": ["Crime", "Drama"],
        "stars": ["Marlon Brando", "Al Pacino"],
        "directors": ["Francis Ford Coppola"],
        "description": "The aging head of a crime family hands control to his reluctant youngest son.",
    },
    {
        "name": "The Dark Knight",
        "year": 2008,
        "time": 152,
        "imdb": 9.0,
        "votes": 2900000,
        "price": "11.99",
        "certification": "PG-13",
        "genres": ["Action", "Crime", "Drama"],
        "stars": ["Christian Bale", "Heath Ledger"],
        "directors": ["Christopher Nolan"],
        "description": "Batman faces a chaotic criminal who pushes Gotham to its limits.",
    },
    {
        "name": "Pulp Fiction",
        "year": 1994,
        "time": 154,
        "imdb": 8.9,
        "votes": 2300000,
        "price": "8.99",
        "certification": "R",
        "genres": ["Crime", "Drama"],
        "stars": ["John Travolta", "Samuel L. Jackson", "Uma Thurman"],
        "directors": ["Quentin Tarantino"],
        "description": "Several intertwined stories of criminals in Los Angeles told out of order.",
    },
    {
        "name": "Forrest Gump",
        "year": 1994,
        "time": 142,
        "imdb": 8.8,
        "votes": 2400000,
        "price": "6.99",
        "certification": "PG-13",
        "genres": ["Drama", "Romance"],
        "stars": ["Tom Hanks", "Robin Wright"],
        "directors": ["Robert Zemeckis"],
        "description": "A kind man with a low IQ accidentally witnesses and shapes decades of history.",
    },
    {
        "name": "Inception",
        "year": 2010,
        "time": 148,
        "imdb": 8.8,
        "votes": 2600000,
        "price": "12.99",
        "certification": "PG-13",
        "genres": ["Action", "Sci-Fi"],
        "stars": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
        "directors": ["Christopher Nolan"],
        "description": "A thief who steals secrets from dreams is offered a chance to plant an idea instead.",
    },
    {
        "name": "The Matrix",
        "year": 1999,
        "time": 136,
        "imdb": 8.7,
        "votes": 2200000,
        "price": "7.49",
        "certification": "R",
        "genres": ["Action", "Sci-Fi"],
        "stars": ["Keanu Reeves", "Laurence Fishburne"],
        "directors": ["Lana Wachowski", "Lilly Wachowski"],
        "description": "A hacker learns that his everyday world is a simulation and joins a rebellion.",
    },
    {
        "name": "Spirited Away",
        "year": 2001,
        "time": 125,
        "imdb": 8.6,
        "votes": 850000,
        "price": "5.99",
        "certification": "PG",
        "genres": ["Animation", "Fantasy"],
        "stars": ["Rumi Hiiragi", "Miyu Irino"],
        "directors": ["Hayao Miyazaki"],
        "description": "A girl wanders into a world of spirits and must work to free her parents.",
    },
    {
        "name": "Heat",
        "year": 1995,
        "time": 170,
        "imdb": 8.3,
        "votes": 700000,
        "price": "9.49",
        "certification": "R",
        "genres": ["Crime", "Drama"],
        "stars": ["Al Pacino", "Robert De Niro"],
        "directors": ["Michael Mann"],
        "description": "A detective and a professional thief circle each other across Los Angeles.",
    },
    {
        "name": "Amélie",
        "year": 2001,
        "time": 122,
        "imdb": 8.3,
        "votes": 800000,
        "price": "4.99",
        "certification": "R",
        "genres": ["Comedy", "Romance"],
        "stars": ["Audrey Tautou"],
        "directors": ["Jean-Pierre Jeunet"],
        "description": "A shy waitress in Paris secretly sets out to improve the lives of those around her.",
    },
]

NamedModel = TypeVar("NamedModel", GenreModel, StarModel, DirectorModel, CertificationModel)


async def seed_user_groups(session: AsyncSession) -> None:
    result = await session.execute(select(UserGroupModel.name))
    existing = set(result.scalars().all())

    for group in UserGroupEnum:
        if group not in existing:
            session.add(UserGroupModel(name=group))

    await session.commit()


async def seed_demo_users(session: AsyncSession) -> None:
    await seed_user_groups(session)

    for email, group in DEMO_USERS.items():
        group_id = (await session.execute(select(UserGroupModel.id).where(UserGroupModel.name == group))).scalar_one()
        user = await session.scalar(select(UserModel).where(UserModel.email == email))
        if user is None:
            user = UserModel.create(email=email, raw_password=DEMO_PASSWORD, group_id=group_id)
            session.add(user)
        else:
            user.password = DEMO_PASSWORD
        user.is_active = True
        user.group_id = group_id

    await session.commit()


async def _get_or_create(session: AsyncSession, model: type[NamedModel], names: list[str]) -> list[NamedModel]:
    found = (await session.scalars(select(model).where(model.name.in_(names)))).all()
    by_name = {row.name: row for row in found}
    for name in names:
        if name not in by_name:
            by_name[name] = model(name=name)
            session.add(by_name[name])
    await session.flush()
    return [by_name[name] for name in names]


async def seed_demo_movies(session: AsyncSession) -> int:
    created = 0
    for data in DEMO_MOVIES:
        exists = await session.scalar(
            select(MovieModel.id).where(
                MovieModel.name == data["name"], MovieModel.year == data["year"], MovieModel.time == data["time"]
            )
        )
        if exists is not None:
            continue

        (certification,) = await _get_or_create(session, CertificationModel, [data["certification"]])
        session.add(
            MovieModel(
                name=data["name"],
                year=data["year"],
                time=data["time"],
                imdb=data["imdb"],
                votes=data["votes"],
                description=data["description"],
                price=Decimal(data["price"]),
                certification=certification,
                genres=await _get_or_create(session, GenreModel, data["genres"]),
                stars=await _get_or_create(session, StarModel, data["stars"]),
                directors=await _get_or_create(session, DirectorModel, data["directors"]),
            )
        )
        created += 1

    await session.commit()
    return created


async def main(groups_only: bool = False) -> None:
    created = 0
    try:
        async with get_db_contextmanager() as session:
            if groups_only:
                await seed_user_groups(session)
            else:
                await seed_demo_users(session)
                created = await seed_demo_movies(session)
    finally:
        await engine.dispose()

    if groups_only:
        print("User groups are ready.")
        return

    print("Demo accounts are ready:")
    for email, group in DEMO_USERS.items():
        print(f"  {group.value:10s} {email}")
    if DEMO_PASSWORD == DEFAULT_PASSWORD:
        print(f"Password: {DEFAULT_PASSWORD}  (set DEMO_PASSWORD to use another one)")
    else:
        print("Password: the value of DEMO_PASSWORD")
    print(f"Demo catalog: {created} movie(s) added, {len(DEMO_MOVIES) - created} already there.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load the initial data and, by default, the demo data.")
    parser.add_argument(
        "--groups-only", action="store_true", help="create only the user groups the app needs (no demo data)"
    )
    asyncio.run(main(parser.parse_args().groups_only))
