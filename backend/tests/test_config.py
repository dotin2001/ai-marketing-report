from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def build(data: dict[str, Any]) -> Settings:
    return Settings.model_validate(data)


def test_valid_local_configuration_loads(valid_settings_data: dict[str, Any]) -> None:
    settings = build(valid_settings_data)

    assert settings.app_env == "test"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.redis_url.get_secret_value().startswith("redis://")
    assert settings.s3_use_ssl is False


@pytest.mark.parametrize(
    "missing_name",
    [
        "APP_ENV",
        "APP_HOST",
        "APP_PORT",
        "HEALTH_CHECK_TIMEOUT_SECONDS",
        "LOG_LEVEL",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "S3_ENDPOINT_URL",
        "S3_REGION",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET",
        "S3_USE_SSL",
    ],
)
def test_each_required_setting_is_enforced(
    valid_settings_data: dict[str, Any],
    missing_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = valid_settings_data.copy()
    invalid.pop(missing_name)
    monkeypatch.delenv(missing_name, raising=False)

    with pytest.raises(ValidationError) as error:
        build(invalid)

    assert missing_name in str(error.value)


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        ("APP_PORT", "not-a-port"),
        ("HEALTH_CHECK_TIMEOUT_SECONDS", 0),
        ("DATABASE_URL", "mysql://user:secret@localhost/db"),
        ("REDIS_URL", "http://localhost:6379"),
        ("S3_ENDPOINT_URL", "ftp://localhost:9000"),
        ("S3_USE_SSL", "sometimes"),
    ],
)
def test_invalid_types_and_url_schemes_are_rejected(
    valid_settings_data: dict[str, Any],
    setting_name: str,
    invalid_value: object,
) -> None:
    invalid = {**valid_settings_data, setting_name: invalid_value}

    with pytest.raises(ValidationError) as error:
        build(invalid)

    message = str(error.value)
    assert setting_name in message
    if isinstance(invalid_value, str):
        assert invalid_value not in message


@pytest.mark.parametrize(
    "setting_name",
    [
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ],
)
def test_placeholders_are_rejected_without_echoing_them(
    valid_settings_data: dict[str, Any],
    setting_name: str,
) -> None:
    rejected_value = "CHANGE_ME_RECOGNIZABLE_SECRET"
    invalid = {**valid_settings_data, setting_name: rejected_value}

    with pytest.raises(ValidationError) as error:
        build(invalid)

    assert rejected_value not in str(error.value)


def test_unknown_settings_are_forbidden(valid_settings_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as error:
        build({**valid_settings_data, "UNEXPECTED_SECRET": "must-not-be-accepted"})

    assert "UNEXPECTED_SECRET" in str(error.value)
    assert "must-not-be-accepted" not in str(error.value)


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_non_local_insecure_object_storage_is_rejected(
    valid_settings_data: dict[str, Any],
    app_env: str,
) -> None:
    invalid = {**valid_settings_data, "APP_ENV": app_env}

    with pytest.raises(ValidationError, match="must use HTTPS"):
        build(invalid)


def test_non_local_https_object_storage_is_allowed(valid_settings_data: dict[str, Any]) -> None:
    configured = build(
        {
            **valid_settings_data,
            "APP_ENV": "production",
            "S3_ENDPOINT_URL": "https://objects.example.test",
            "S3_USE_SSL": True,
        }
    )

    assert configured.s3_use_ssl is True
