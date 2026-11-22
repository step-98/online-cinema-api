import asyncio
import logging
from datetime import datetime, timezone
from typing import cast, TypedDict
from urllib.parse import urlencode

from celery import Task
from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from src.celery_app import celery_app
from src.config import get_settings
from src.database import engine, get_db_contextmanager
from src.models.accounts import ActivationTokenModel
from src.notifications.email import send_email

logger = logging.getLogger(__name__)


class EmailTaskOptions(TypedDict):
    autoretry_for: tuple[type[Exception], ...]
    retry_backoff: bool
    max_retries: int


_EMAIL_TASK: EmailTaskOptions = {"autoretry_for": (OSError,), "retry_backoff": True, "max_retries": 3}


def queue_task(task: Task, *args: object) -> None:
    try:
        task.delay(*args)
    except Exception:
        logger.exception("Could not queue the task %s", task.name)


@celery_app.task(name="src.tasks.send_activation_email", **_EMAIL_TASK)
def send_activation_email(email: str, token: str) -> None:
    settings = get_settings()
    link = f"{settings.ACTIVATION_URL}?{urlencode({'email': email, 'token': token})}"
    send_email(
        settings,
        to=email,
        subject="Activate your account",
        body=(
            "Welcome to Online Cinema!\n\n" f"To activate your account, follow the link (valid for 24 hours):\n{link}\n"
        ),
    )


@celery_app.task(name="src.tasks.send_password_reset_email", **_EMAIL_TASK)
def send_password_reset_email(email: str, token: str) -> None:
    settings = get_settings()
    link = f"{settings.PASSWORD_RESET_URL}?{urlencode({'email': email, 'token': token})}"
    send_email(
        settings,
        to=email,
        subject="Reset your password",
        body=(
            "We received a request to reset your password.\n\n"
            f"To choose a new one, follow the link (valid for 24 hours):\n{link}\n\n"
            "If you did not ask for this, you can ignore this e-mail.\n"
        ),
    )


@celery_app.task(name="src.tasks.send_payment_confirmation_email", **_EMAIL_TASK)
def send_payment_confirmation_email(email: str, order_id: int, amount: str) -> None:
    settings = get_settings()
    send_email(
        settings,
        to=email,
        subject="Payment confirmation",
        body=(
            "Thank you for your purchase!\n\n"
            f"Order #{order_id} is paid. Total: {amount} {settings.STRIPE_CURRENCY.upper()}.\n"
        ),
    )


async def _delete_expired_activation_tokens() -> int:
    try:
        async with get_db_contextmanager() as session:
            result = await session.execute(
                delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < datetime.now(timezone.utc))
            )
            await session.commit()
            return cast(CursorResult, result).rowcount
    finally:
        await engine.dispose()


@celery_app.task(name="src.tasks.delete_expired_activation_tokens")
def delete_expired_activation_tokens() -> int:
    deleted = asyncio.run(_delete_expired_activation_tokens())
    logger.info("Deleted %s expired activation tokens", deleted)
    return deleted
