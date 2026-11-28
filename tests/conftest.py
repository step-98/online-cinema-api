import os

os.environ.update(
    {
        "DATABASE_URL": "sqlite+aiosqlite://",
        "SECRET_KEY_ACCESS": "test-access-secret-key-0123456789abcdef",
        "SECRET_KEY_REFRESH": "test-refresh-secret-key-0123456789abcdef",
        "STRIPE_SECRET_KEY": "sk_test",
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "STRIPE_CURRENCY": "usd",
    }
)

from src.config import get_settings  # noqa: E402

_database_kind = get_settings().DATABASE_URL.split(":")[0]
assert _database_kind.startswith("sqlite"), (
    f"The tests must run on the in-memory SQLite database, but the settings point to '{_database_kind}'. "
    "src.config was imported before tests/conftest.py set the test settings."
)

from dataclasses import dataclass  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import event, func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.models  # noqa: E402,F401  (registers every table)
from src.celery_app import celery_app  # noqa: E402
from src.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.models.accounts import UserGroupEnum, UserGroupModel, UserModel  # noqa: E402
from src.test_fixture import seed_user_groups  # noqa: E402
from tests.helpers import mail_params, movie_payload  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

DEFAULT_PASSWORD = "Passw0rd!"


@dataclass
class UserInfo:
    id: int
    email: str
    password: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        "src.tasks.send_email",
        lambda settings, to, subject, body: sent.append({"to": to, "subject": subject, "body": body}),
    )
    return sent


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        await seed_user_groups(session)
        groups_created = await session.scalar(select(func.count()).select_from(UserGroupModel))
    assert groups_created == len(UserGroupEnum), (
        f"Expected {len(UserGroupEnum)} user groups after seed_user_groups(), found {groups_created}. "
        "Check seed_user_groups in src/test_fixture.py and the import in tests/conftest.py."
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(client, outbox, session_factory):
    """Creates a user the real way (register -> activate by the e-mailed token -> login)."""

    async def _make(email="user@example.com", password=DEFAULT_PASSWORD, group=UserGroupEnum.USER) -> UserInfo:
        r = await client.post("/accounts/register/", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        user_id = r.json()["id"]
        token = mail_params(outbox[-1])["token"][0]
        r = await client.post("/accounts/activate/", json={"email": email, "token": token})
        assert r.status_code == 200, r.text
        r = await client.post("/accounts/login/", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        if group != UserGroupEnum.USER:
            async with session_factory() as session:
                group_id = await session.scalar(select(UserGroupModel.id).where(UserGroupModel.name == group))
                await session.execute(update(UserModel).where(UserModel.id == user_id).values(group_id=group_id))
                await session.commit()
        return UserInfo(user_id, email, password, r.json()["access_token"], r.json()["refresh_token"])

    return _make


@pytest_asyncio.fixture
async def user(make_user):
    return await make_user("user@example.com")


@pytest_asyncio.fixture
async def other_user(make_user):
    return await make_user("other@example.com")


@pytest_asyncio.fixture
async def moderator(make_user):
    return await make_user("moderator@example.com", group=UserGroupEnum.MODERATOR)


@pytest_asyncio.fixture
async def admin(make_user):
    return await make_user("admin@example.com", group=UserGroupEnum.ADMIN)


@pytest_asyncio.fixture
async def catalog(client, moderator):
    movies = [
        movie_payload(
            "Heat",
            1995,
            "9.99",
            8.3,
            700,
            genres=("Drama", "Crime"),
            stars=("Al Pacino", "Robert De Niro"),
            directors=("Michael Mann",),
        ),
        movie_payload(
            "Ronin",
            1998,
            "5.00",
            7.2,
            300,
            genres=("Drama", "Action"),
            stars=("Robert De Niro", "Jean Reno"),
            directors=("John Frankenheimer",),
        ),
        movie_payload(
            "Casino",
            1995,
            "7.50",
            8.2,
            500,
            genres=("Crime",),
            stars=("Robert De Niro", "Sharon Stone"),
            directors=("Martin Scorsese",),
        ),
    ]
    ids = {}
    for payload in movies:
        r = await client.post("/movies/", json=payload, headers=moderator.headers)
        assert r.status_code == 201, r.text
        ids[payload["name"]] = r.json()["id"]
    return ids


@pytest.fixture
def stripe_mock(monkeypatch):
    calls = {"checkout": [], "refund": []}

    async def fake_checkout(settings, order):
        calls["checkout"].append(order.id)
        return SimpleNamespace(url="https://checkout.stripe.test/session", id="cs_test_session")

    async def fake_refund(settings, payment_intent_id):
        calls["refund"].append(payment_intent_id)

    monkeypatch.setattr("src.routes.payments._create_checkout_session", fake_checkout)
    monkeypatch.setattr("src.routes.payments._create_refund", fake_refund)
    return calls


@pytest_asyncio.fixture
async def pending_order(client, user, catalog):
    for name in ("Heat", "Ronin"):
        r = await client.post(f"/cart/movies/{catalog[name]}/", headers=user.headers)
        assert r.status_code == 201, r.text
    r = await client.post("/orders/", headers=user.headers)
    assert r.status_code == 201, r.text
    return r.json()
