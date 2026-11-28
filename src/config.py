from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str

    SECRET_KEY_ACCESS: str = Field(min_length=32)
    SECRET_KEY_REFRESH: str = Field(min_length=32)

    JWT_SIGNING_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_CURRENCY: str = "usd"

    PAYMENT_SUCCESS_URL: str = "http://localhost:8000/docs"
    PAYMENT_CANCEL_URL: str = "http://localhost:8000/docs"

    REDIS_URL: str = "redis://localhost:6379/0"
    EMAIL_HOST: str = "localhost"
    EMAIL_PORT: int = 1025
    EMAIL_FROM: str = "no-reply@online-cinema.local"
    ACTIVATION_URL: str = "http://localhost:8000/docs"
    PASSWORD_RESET_URL: str = "http://localhost:8000/docs"

    @model_validator(mode="after")
    def _keys_must_differ(self) -> "Settings":
        if self.SECRET_KEY_ACCESS == self.SECRET_KEY_REFRESH:
            raise ValueError("SECRET_KEY_ACCESS and SECRET_KEY_REFRESH must be different")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
