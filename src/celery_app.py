from celery import Celery

from src.config import get_settings

settings = get_settings()

celery_app = Celery("online_cinema", broker=settings.REDIS_URL, include=["src.tasks"])

celery_app.conf.update(
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "delete-expired-activation-tokens": {
            "task": "src.tasks.delete_expired_activation_tokens",
            "schedule": 3600.0,
        },
    },
)
