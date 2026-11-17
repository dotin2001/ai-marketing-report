from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReportVersion
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_version_binding_rejects_foreign_dataset_and_retains_immutability(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-bindings")
    wrong_dataset = ReportVersion(
        owner_id=owner.id,
        report_id=report.id,
        version_number=1,
        source_draft_id=draft.id,
        source_draft_revision=draft.revision,
        dataset_id=uuid4(),
        template_version="v1",
        snapshot_schema_version=1,
        snapshot={},
        snapshot_identity=sha256(b"wrong-dataset").digest(),
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(wrong_dataset)
            await db_session.flush()

    version = ReportVersion(
        owner_id=owner.id,
        report_id=report.id,
        version_number=1,
        source_draft_id=draft.id,
        source_draft_revision=draft.revision,
        template_version="v1",
        snapshot_schema_version=1,
        snapshot={},
        snapshot_identity=sha256(b"valid-version").digest(),
    )
    db_session.add(version)
    await db_session.flush()
    for operation in (
        update(ReportVersion).where(ReportVersion.id == version.id).values(template_version="v2"),
        delete(ReportVersion).where(ReportVersion.id == version.id),
    ):
        with pytest.raises(DBAPIError, match="immutable table report_versions rejects"):
            async with db_session.begin_nested():
                await db_session.execute(operation)
    retained = await db_session.scalar(select(ReportVersion).where(ReportVersion.id == version.id))
    assert retained is not None
    assert retained.template_version == "v1"
