from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def build(data: dict[str, Any]) -> Settings:
    # Dictionary-level tests own their complete input and must not consult a developer dotenv file.
    return Settings(_env_file=None, **data)


def test_report_cursor_signing_key_is_required_and_strong(
    valid_settings_data: dict[str, Any],
) -> None:
    for invalid in (None, "short", "CHANGE_ME_RANDOM_SECRET_AT_LEAST_32_BYTES"):
        data = dict(valid_settings_data)
        if invalid is None:
            del data["REPORT_CURSOR_SIGNING_KEY"]
        else:
            data["REPORT_CURSOR_SIGNING_KEY"] = invalid
        with pytest.raises(ValidationError) as error:
            build(data)
        assert "REPORT_CURSOR_SIGNING_KEY" in str(error.value)


def test_valid_local_configuration_loads(valid_settings_data: dict[str, Any]) -> None:
    settings = build(valid_settings_data)

    assert settings.app_env == "test"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.redis_url.get_secret_value().startswith("redis://")
    assert settings.s3_use_ssl is False
    assert settings.source_csv_max_bytes == 10_485_760
    assert settings.source_text_max_bytes == 1_048_576
    assert settings.source_csv_max_records == 100_000
    assert settings.source_preview_max_rows == 50
    assert settings.source_preview_max_text_chars == 2000
    assert settings.source_preview_max_cell_chars == 500
    assert settings.source_preview_max_response_bytes == 65_536
    assert settings.generated_pdf_max_bytes == 26_214_400
    assert settings.object_storage_timeout_seconds == 10
    assert settings.analysis_publish_timeout_seconds == 3
    assert settings.analysis_task_time_limit_seconds == 300
    assert settings.analysis_stale_running_seconds == 600
    assert settings.pdf_task_time_limit_seconds == 180
    assert settings.pdf_stale_running_seconds == 360
    assert settings.openai_model == "unit-test-model"
    assert settings.openai_timeout_seconds == 60
    assert "unit-test-openai-key" not in repr(settings)


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS"])
def test_openai_settings_are_required(
    valid_settings_data: dict[str, Any], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(name, raising=False)
    data = dict(valid_settings_data)
    data.pop(name)
    with pytest.raises(ValidationError) as error:
        build(data)
    assert "unit-test-openai-key" not in str(error.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENAI_API_KEY", ""),
        ("OPENAI_API_KEY", "CHANGE_ME_KEY"),
        ("OPENAI_MODEL", ""),
        ("OPENAI_MODEL", "  "),
        ("OPENAI_TIMEOUT_SECONDS", 0),
        ("OPENAI_TIMEOUT_SECONDS", 300),
        ("OPENAI_TIMEOUT_SECONDS", 295),
    ],
)
def test_openai_settings_reject_blank_and_unsafe_values(
    valid_settings_data: dict[str, Any], name: str, value: str | int
) -> None:
    with pytest.raises(ValidationError) as error:
        build({**valid_settings_data, name: value})
    assert "unit-test-openai-key" not in str(error.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ANALYSIS_PUBLISH_TIMEOUT_SECONDS", 0),
        ("ANALYSIS_PUBLISH_TIMEOUT_SECONDS", 31),
        ("ANALYSIS_TASK_TIME_LIMIT_SECONDS", 9),
        ("ANALYSIS_TASK_TIME_LIMIT_SECONDS", 3601),
        ("ANALYSIS_STALE_RUNNING_SECONDS", 10),
        ("ANALYSIS_STALE_RUNNING_SECONDS", 7201),
        ("ANALYSIS_STALE_RUNNING_SECONDS", 300),
    ],
)
def test_analysis_worker_limits_are_bounded(
    valid_settings_data: dict[str, Any], name: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        build({**valid_settings_data, name: value})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PDF_TASK_TIME_LIMIT_SECONDS", 9),
        ("PDF_TASK_TIME_LIMIT_SECONDS", 3601),
        ("PDF_STALE_RUNNING_SECONDS", 10),
        ("PDF_STALE_RUNNING_SECONDS", 7201),
        ("PDF_STALE_RUNNING_SECONDS", 180),
        ("PDF_TASK_TIME_LIMIT_SECONDS", 45),
    ],
)
def test_pdf_worker_limits_are_bounded(
    valid_settings_data: dict[str, Any], name: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        build({**valid_settings_data, name: value})


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
        "SOURCE_CSV_MAX_BYTES",
        "GENERATED_PDF_MAX_BYTES",
        "OBJECT_STORAGE_TIMEOUT_SECONDS",
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
        ("SOURCE_CSV_MAX_BYTES", 0),
        ("SOURCE_CSV_MAX_BYTES", 1_073_741_825),
        ("SOURCE_TEXT_MAX_BYTES", 0),
        ("SOURCE_TEXT_MAX_BYTES", 10_485_761),
        ("SOURCE_CSV_MAX_RECORDS", 0),
        ("SOURCE_CSV_MAX_RECORDS", 1_000_001),
        ("SOURCE_PREVIEW_MAX_ROWS", 0),
        ("SOURCE_PREVIEW_MAX_ROWS", 1001),
        ("SOURCE_PREVIEW_MAX_TEXT_CHARS", 0),
        ("SOURCE_PREVIEW_MAX_TEXT_CHARS", 100_001),
        ("SOURCE_PREVIEW_MAX_CELL_CHARS", 0),
        ("SOURCE_PREVIEW_MAX_CELL_CHARS", 10_001),
        ("SOURCE_PREVIEW_MAX_RESPONSE_BYTES", 0),
        ("SOURCE_PREVIEW_MAX_RESPONSE_BYTES", 1_048_577),
        ("GENERATED_PDF_MAX_BYTES", 0),
        ("GENERATED_PDF_MAX_BYTES", 1_073_741_825),
        ("OBJECT_STORAGE_TIMEOUT_SECONDS", 0),
        ("OBJECT_STORAGE_TIMEOUT_SECONDS", 61),
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


def _set_environment(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, Any],
    *,
    exclude: set[str] | None = None,
) -> None:
    for name, value in values.items():
        if name in (exclude or set()):
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, str(value).lower() if isinstance(value, bool) else str(value))


def test_workflow_test_signal_keeps_deliberately_unset_values_missing(
    valid_settings_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("APP_HOST=dotenv-backfill.example\n", encoding="utf-8")
    _set_environment(monkeypatch, valid_settings_data, exclude={"APP_HOST"})
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_LOCAL_DISABLE_DOTENV", "1")

    with pytest.raises(ValidationError) as error:
        Settings()

    assert "APP_HOST" in str(error.value)


def test_normal_startup_and_non_test_signal_still_load_dotenv(
    valid_settings_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("APP_HOST=dotenv-loaded.example\n", encoding="utf-8")
    _set_environment(monkeypatch, valid_settings_data, exclude={"APP_HOST"})
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("AI_LOCAL_DISABLE_DOTENV", "1")

    settings = Settings()

    assert settings.app_env == "local"
    assert settings.app_host == "dotenv-loaded.example"
