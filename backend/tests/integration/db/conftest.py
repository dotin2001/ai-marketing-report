from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import Principal, Report, ReportDraft
from app.db.repositories import create_report
from app.db.testing import validate_test_database


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    async with engine.connect() as connection:
        outer = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


async def seed_report(
    session: AsyncSession,
    *,
    namespace: str = "test",
    subject: str = "owner",
) -> tuple[Principal, Report, ReportDraft]:
    principal = Principal(identity_namespace=namespace, subject=subject)
    session.add(principal)
    await session.flush()
    report, draft = await create_report(
        session,
        owner_id=principal.id,
        name="Quarterly report",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        objectives=["Explain acquisition performance"],
    )
    return principal, report, draft
