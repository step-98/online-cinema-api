import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import engine, get_db_contextmanager
from src.models.accounts import UserGroupEnum, UserGroupModel, UserModel
from src.seed import seed_user_groups

DEFAULT_PASSWORD = "Demo1234!"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)

DEMO_USERS = {
    "demo.user@example.com": UserGroupEnum.USER,
    "demo.moderator@example.com": UserGroupEnum.MODERATOR,
    "demo.admin@example.com": UserGroupEnum.ADMIN,
}


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


async def main() -> None:
    try:
        async with get_db_contextmanager() as session:
            await seed_demo_users(session)
    finally:
        await engine.dispose()

    print("Demo accounts are ready:")
    for email, group in DEMO_USERS.items():
        print(f"  {group.value:10s} {email}")
    if DEMO_PASSWORD == DEFAULT_PASSWORD:
        print(f"Password: {DEFAULT_PASSWORD}  (set DEMO_PASSWORD to use another one)")
    else:
        print("Password: the value of DEMO_PASSWORD")


if __name__ == "__main__":
    asyncio.run(main())
