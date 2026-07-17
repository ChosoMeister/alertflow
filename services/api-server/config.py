import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    webhook_auth_token: str = ""

    # JWT
    jwt_secret: str  # REQUIRED — no default, must be set via env
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Default Destinations (for routing fallback)
    telegram_default_chat_id: str = ""
    telegram_default_thread_id: str = "0"
    matrix_default_room_id: str = ""
    default_notification_channel: str = "both"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
