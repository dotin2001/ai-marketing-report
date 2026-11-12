from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings


@pytest.fixture
def valid_settings_data() -> dict[str, Any]:
    return {
        "APP_ENV": "test",
        "APP_HOST": "127.0.0.1",
        "APP_PORT": 8000,
        "HEALTH_CHECK_TIMEOUT_SECONDS": 0.1,
        "LOG_LEVEL": "INFO",
        "POSTGRES_DB": "marketing_reports",
        "POSTGRES_USER": "marketing_app",
        "POSTGRES_PASSWORD": "unit-postgres-password",
        "DATABASE_URL": "postgresql+psycopg://marketing_app:unit-postgres-password@127.0.0.1:5432/marketing_reports",
        "REDIS_PASSWORD": "unit-redis-password",
        "REDIS_URL": "redis://:unit-redis-password@127.0.0.1:6379/0",
        "S3_ENDPOINT_URL": "http://127.0.0.1:9000",
        "S3_REGION": "us-east-1",
        "S3_ACCESS_KEY_ID": "unit-minio-user",
        "S3_SECRET_ACCESS_KEY": "unit-minio-password",
        "S3_BUCKET": "marketing-reports-test",
        "S3_USE_SSL": False,
    }


@pytest.fixture
def settings(valid_settings_data: dict[str, Any]) -> Settings:
    return Settings.model_validate(valid_settings_data)
