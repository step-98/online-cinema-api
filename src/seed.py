import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import engine, get_db_contextmanager
from src.models.accounts import UserGroupEnum, UserGroupModel


async def seed_user_groups(session: AsyncSession) -> None:
    """Create any missing user groups. Safe to run any number of times."""
    result = await session.execute(select(UserGroupModel.name))
    existing = set(result.scalars().all())

    for group in UserGroupEnum:
        if group not in existing:
            session.add(UserGroupModel(name=group))

    await session.commit()


async def main() -> None:
    try:
        async with get_db_contextmanager() as session:
            await seed_user_groups(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
