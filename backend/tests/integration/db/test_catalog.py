from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.db.models import IMMUTABLE_TABLES

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_catalog_contains_every_model_table_and_one_head(
    db_session: AsyncSession,
) -> None:
    tables = set(
        (
            await db_session.scalars(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() AND tablename <> 'alembic_version'"
                )
            )
        ).all()
    )
    assert tables == set(Base.metadata.tables)


@pytest.mark.asyncio
async def test_catalog_has_uuid_defaults_timestamptz_and_immutable_triggers(
    db_session: AsyncSession,
) -> None:
    uuid_columns = set(
        (
            await db_session.scalars(
                text(
                    "SELECT table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND data_type = 'uuid'"
                )
            )
        ).all()
    )
    expected_uuid_columns = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.c
        if column.type.__class__.__name__ == "UUID"
    }
    assert uuid_columns == expected_uuid_columns

    uuid_defaults = set(
        (
            await db_session.scalars(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND column_name = 'id' "
                    "AND data_type = 'uuid' AND column_default LIKE 'gen_random_uuid()%'"
                )
            )
        ).all()
    )
    assert uuid_defaults == {
        table.name for table in Base.metadata.tables.values() if "id" in table.c
    }

    timestamptz = set(
        (
            await db_session.scalars(
                text(
                    "SELECT table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND data_type = 'timestamp with time zone'"
                )
            )
        ).all()
    )
    expected_timestamptz = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.c
        if column.type.__class__.__name__ == "TIMESTAMP"
        and bool(getattr(column.type, "timezone", False))
    }
    assert timestamptz == expected_timestamptz

    trigger_events = {
        tuple(row)
        for row in await db_session.execute(
            text(
                "SELECT event_object_table, event_manipulation "
                "FROM information_schema.triggers WHERE trigger_schema = current_schema()"
            )
        )
    }
    assert {
        (table_name, operation)
        for table_name in IMMUTABLE_TABLES
        for operation in ("UPDATE", "DELETE")
    } <= trigger_events


@pytest.mark.asyncio
async def test_catalog_contains_every_named_constraint_and_index(
    db_session: AsyncSession,
) -> None:
    expected_constraints = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, (ForeignKeyConstraint, CheckConstraint, UniqueConstraint))
        and constraint.name is not None
    }
    catalog_constraints = set(
        (
            await db_session.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE connamespace = ("
                    "SELECT oid FROM pg_namespace WHERE nspname = current_schema()"
                    ") "
                    "AND contype IN ('f','c','u')"
                )
            )
        ).all()
    )
    assert expected_constraints == catalog_constraints

    expected_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name is not None
    }
    catalog_indexes = set(
        (
            await db_session.scalars(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            )
        ).all()
    )
    assert expected_indexes <= catalog_indexes


@pytest.mark.asyncio
async def test_owner_keyset_indexes_have_required_leading_columns(
    db_session: AsyncSession,
) -> None:
    definitions = {
        row.indexname: row.indexdef.lower()
        for row in (
            await db_session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()"
                )
            )
        )
    }
    expected_fragments = {
        "ix_reports_owner_created_keyset": "(owner_id, created_at desc, id desc)",
        "ix_analysis_jobs_owner_report_created_keyset": (
            "(owner_id, report_id, created_at desc, id desc)"
        ),
        "ix_report_versions_owner_report_number_keyset": (
            "(owner_id, report_id, version_number desc, id desc)"
        ),
        "ix_pdf_exports_owner_report_version_created_keyset": (
            "(owner_id, report_id, version_id, created_at desc, id desc)"
        ),
        "ix_canonical_rows_owner_report_dataset_keyset": (
            "(owner_id, report_id, dataset_id, source_record_index, id)"
        ),
    }
    for index_name, fragment in expected_fragments.items():
        assert fragment in definitions[index_name]


@pytest.mark.asyncio
async def test_catalog_forbids_secret_and_content_indexes(db_session: AsyncSession) -> None:
    definitions = await db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
    )
    for index_name, definition in definitions:
        if index_name == "uq_file_assets_object_identity":
            continue
        lowered = str(definition).lower()
        for forbidden in (
            "inline_text",
            "object_key",
            "content",
            "credential",
            "signed_url",
            "public_url",
        ):
            assert forbidden not in lowered
