from __future__ import annotations

import pytest

from app.db.testing import UnsafeTestDatabaseError, validate_test_database

SAFE = "postgresql+psycopg://test_user:test-password@127.0.0.1:5432/reporting_test"
DEV = "postgresql+psycopg://dev_user:dev-password@127.0.0.1:5432/reporting"


def test_isolated_local_database_is_accepted() -> None:
    target = validate_test_database(app_env="test", test_database_url=SAFE, database_url=DEV)
    assert target.database == "reporting_test"


@pytest.mark.parametrize(
    ("app_env", "test_url", "database_url", "setting"),
    [
        ("development", SAFE, DEV, "APP_ENV"),
        ("test", DEV, SAFE, "TEST_DATABASE_URL"),
        ("test", SAFE, SAFE, "TEST_DATABASE_URL"),
        (
            "test",
            "postgresql://remote:recognizable-secret@db.example.com/reporting_test",
            DEV,
            "TEST_DATABASE_URL",
        ),
    ],
)
def test_unsafe_database_configuration_fails_without_credentials(
    app_env: str,
    test_url: str,
    database_url: str,
    setting: str,
) -> None:
    with pytest.raises(UnsafeTestDatabaseError) as error:
        validate_test_database(
            app_env=app_env,
            test_database_url=test_url,
            database_url=database_url,
        )
    message = str(error.value)
    assert setting in message
    assert "recognizable-secret" not in message
