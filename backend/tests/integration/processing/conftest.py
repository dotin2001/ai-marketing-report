"""Reuse the isolated PostgreSQL transaction fixture for processing tests."""

from tests.integration.db.conftest import db_session

__all__ = ["db_session"]
