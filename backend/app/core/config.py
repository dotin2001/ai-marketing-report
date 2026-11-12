"""Strict, redaction-safe runtime configuration."""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_FORBIDDEN_MARKERS = ("CHANGE_ME", "REPLACE_ME", "PLACEHOLDER")


def _reject_placeholder(value: str) -> str:
    upper_value = value.upper()
    if any(marker in upper_value for marker in _FORBIDDEN_MARKERS):
        raise ValueError("must not contain an example placeholder")
    return value


def _require_scheme(value: str, schemes: frozenset[str], setting_name: str) -> str:
    if urlsplit(value).scheme.lower() not in schemes:
        raise ValueError(f"{setting_name} uses an unsupported URL scheme")
    return value


class Settings(BaseSettings):
    """Configuration loaded only when an application instance is created."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",
        hide_input_in_errors=True,
        validate_default=True,
    )

    app_env: Literal["local", "test", "development", "staging", "production"] = Field(
        validation_alias="APP_ENV"
    )
    app_host: str = Field(min_length=1, validation_alias="APP_HOST")
    app_port: int = Field(ge=1, le=65535, validation_alias="APP_PORT")
    health_check_timeout_seconds: float = Field(
        gt=0,
        le=10,
        validation_alias="HEALTH_CHECK_TIMEOUT_SECONDS",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        validation_alias="LOG_LEVEL"
    )

    postgres_db: str = Field(min_length=1, validation_alias="POSTGRES_DB")
    postgres_user: str = Field(min_length=1, validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")

    redis_password: SecretStr = Field(validation_alias="REDIS_PASSWORD")
    redis_url: SecretStr = Field(validation_alias="REDIS_URL")

    s3_endpoint_url: str = Field(validation_alias="S3_ENDPOINT_URL")
    s3_region: str = Field(min_length=1, validation_alias="S3_REGION")
    s3_access_key_id: SecretStr = Field(validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr = Field(validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$",
        validation_alias="S3_BUCKET",
    )
    s3_use_ssl: bool = Field(validation_alias="S3_USE_SSL")

    @field_validator(
        "app_host",
        "postgres_db",
        "postgres_user",
        "s3_endpoint_url",
        "s3_region",
        "s3_bucket",
    )
    @classmethod
    def validate_public_strings(cls, value: str) -> str:
        return _reject_placeholder(value)

    @field_validator(
        "postgres_password",
        "database_url",
        "redis_password",
        "redis_url",
        "s3_access_key_id",
        "s3_secret_access_key",
    )
    @classmethod
    def validate_secrets(cls, value: SecretStr) -> SecretStr:
        _reject_placeholder(value.get_secret_value())
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        _require_scheme(
            value.get_secret_value(),
            frozenset({"postgresql", "postgresql+psycopg"}),
            "DATABASE_URL",
        )
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        _require_scheme(value.get_secret_value(), frozenset({"redis", "rediss"}), "REDIS_URL")
        return value

    @field_validator("s3_endpoint_url")
    @classmethod
    def validate_s3_endpoint_url(cls, value: str) -> str:
        return _require_scheme(value, frozenset({"http", "https"}), "S3_ENDPOINT_URL")

    @model_validator(mode="after")
    def reject_non_local_insecure_storage(self) -> Self:
        if self.app_env in {"staging", "production"}:
            if not self.s3_use_ssl or urlsplit(self.s3_endpoint_url).scheme != "https":
                raise ValueError("non-local object storage must use HTTPS")
        return self
