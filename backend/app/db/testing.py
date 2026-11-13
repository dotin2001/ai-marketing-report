"""Fail-closed guards for destructive PostgreSQL integration fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

APPROVED_TEST_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "postgres"})


class UnsafeTestDatabaseError(RuntimeError):
    """Raised before any destructive database operation can run."""


@dataclass(frozen=True, slots=True)
class SafeTestDatabase:
    url: str
    host: str
    database: str


def validate_test_database(
    *,
    app_env: str | None,
    test_database_url: str | None,
    database_url: str | None,
    approved_hosts: frozenset[str] = APPROVED_TEST_HOSTS,
) -> SafeTestDatabase:
    """Validate only setting names and URL structure; never echo credentials."""

    if app_env != "test":
        raise UnsafeTestDatabaseError("APP_ENV must be test")
    if not test_database_url:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL is required")
    if not database_url:
        raise UnsafeTestDatabaseError("DATABASE_URL is required for isolation comparison")
    if test_database_url == database_url:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL must differ from DATABASE_URL")

    parsed = urlsplit(test_database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL must use PostgreSQL")
    host = parsed.hostname or ""
    database = parsed.path.removeprefix("/")
    if host not in approved_hosts:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL host is not approved")
    if not database.endswith("_test"):
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL database must end in _test")
    return SafeTestDatabase(url=test_database_url, host=host, database=database)
