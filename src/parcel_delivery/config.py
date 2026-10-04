from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"] = "INFO"

    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_name: str
    db_user: str
    db_password: str

    redis_host: str
    redis_port: int = Field(ge=1, le=65535)
    redis_db: int = Field(ge=0)

    exchange_rate_cache_ttl_seconds: int = Field(gt=0)
    delivery_cost_batch_size: int = Field(default=100, gt=0, le=10_000)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().upper()
            return {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(value, value)
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
