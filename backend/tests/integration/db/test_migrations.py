from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import cast

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic import command
from app.db import Base
from app.db.models import Principal
from app.db.testing import validate_test_database

pytestmark = pytest.mark.postgres
BACKEND = Path(__file__).parents[3]


def alembic_config() -> Config:
    return Config(BACKEND / "alembic.ini")


def test_migration_scaffold_loads_without_connecting() -> None:
    config = alembic_config()
    scripts = ScriptDirectory.from_config(config)
    assert scripts.dir == str(BACKEND / "alembic")
    assert len(scripts.get_heads()) == 1
    assert len(list(scripts.walk_revisions())) == 1
    assert "invalid:invalid" in (config.get_main_option("sqlalchemy.url") or "")


def test_offline_sql_contains_reviewed_schema_without_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+psycopg://offline_user:offline_password@127.0.0.1/offline_test",
    )
    command.upgrade(alembic_config(), "head", sql=True)
    sql = capsys.readouterr().out.lower()
    for table_name in Base.metadata.tables:
        assert f"create table {table_name}" in sql
    assert "gen_random_uuid()" in sql
    assert "timestamp with time zone" in sql
    assert "deferrable initially deferred" in sql
    assert "reject_immutable_row" in sql
    assert "offline_password" not in sql
    for forbidden in ("public_url", "signed_url", "credential", "access_key", "secret_key"):
        assert forbidden not in sql


@pytest.mark.asyncio
async def test_migrated_database_is_at_head(db_session: AsyncSession) -> None:
    current = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert current == ScriptDirectory.from_config(alembic_config()).get_current_head()


@pytest.mark.asyncio
async def test_empty_roundtrip_populated_refusal_and_schema_parity() -> None:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    config = alembic_config()
    os.environ["MIGRATION_DATABASE_URL"] = target.url

    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")
    engine = create_async_engine(target.url, pool_pre_ping=False)
    async with engine.connect() as connection:
        product_tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
            - {"alembic_version"}
        )
    assert not product_tables

    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as connection:
        current = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        def metadata_differences(sync_connection: object) -> list[object]:
            context = MigrationContext.configure(sync_connection)  # type: ignore[arg-type]
            return cast(list[object], compare_metadata(context, Base.metadata))

        differences = await connection.run_sync(metadata_differences)
    assert current == ScriptDirectory.from_config(config).get_current_head()
    assert differences == []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            principal = Principal(identity_namespace="migration-test", subject="populated")
            session.add(principal)
    with pytest.raises(DBAPIError, match="guarded downgrade refused"):
        await asyncio.to_thread(command.downgrade, config, "base")
    async with AsyncSession(engine) as session:
        assert await session.get(Principal, principal.id) is not None
        current = await session.scalar(text("SELECT version_num FROM alembic_version"))
        assert current == ScriptDirectory.from_config(config).get_current_head()
        await session.execute(delete(Principal).where(Principal.id == principal.id))
        await session.commit()
    await engine.dispose()
