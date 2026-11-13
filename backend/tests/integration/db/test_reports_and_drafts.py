from __future__ import annotations

import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import (
    AnalysisJob,
    DraftClaim,
    DraftItemClaimReference,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    FileAsset,
    PdfExport,
    Principal,
    Report,
    ReportDraft,
    ReportSource,
    ReportVersion,
)
from app.db.repositories import (
    ConcurrencyConflict,
    activate_restored_draft,
    create_report,
    get_report,
    save_draft_objectives,
)
from app.db.testing import validate_test_database
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_create_report_builds_only_revision_one_draft(db_session: AsyncSession) -> None:
    owner, report, draft = await seed_report(db_session)
    assert draft.revision == 1 and draft.is_active
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(DraftObjective)
            .where(DraftObjective.draft_id == draft.id)
        )
        == 1
    )
    assert report.current_source_id is None
    for model in (ReportSource, AnalysisJob, ReportVersion, PdfExport, FileAsset):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert await get_report(db_session, owner_id=owner.id, report_id=report.id) is report
    assert await get_report(db_session, owner_id=uuid4(), report_id=report.id) is None


@pytest.mark.asyncio
async def test_report_creation_requires_a_non_blank_objective(db_session: AsyncSession) -> None:
    owner = Principal(identity_namespace="test", subject="missing-objective-owner")
    db_session.add(owner)
    await db_session.flush()
    for objectives in ([], [" "]):
        with pytest.raises(ValueError, match="non-blank objective"):
            await create_report(
                db_session,
                owner_id=owner.id,
                name="No objective",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                objectives=objectives,
            )


@pytest.mark.asyncio
async def test_report_constraints_reject_blank_name_and_reversed_period(
    db_session: AsyncSession,
) -> None:
    owner = Principal(identity_namespace="test", subject="invalid-owner")
    db_session.add(owner)
    await db_session.flush()
    for name, start, end in (
        (" ", date(2026, 1, 1), date(2026, 1, 2)),
        ("Invalid", date(2026, 2, 1), date(2026, 1, 1)),
    ):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(
                    Report(owner_id=owner.id, name=name, period_start=start, period_end=end)
                )
                await db_session.flush()


@pytest.mark.asyncio
async def test_compare_and_set_preserves_content_on_stale_revision(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="cas-owner")
    revision = await save_draft_objectives(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        objectives=["Updated objective"],
    )
    assert revision == 2
    with pytest.raises(ConcurrencyConflict):
        await save_draft_objectives(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=1,
            objectives=["Stale content"],
        )
    assert (
        await db_session.scalar(
            select(DraftObjective.content).where(DraftObjective.draft_id == draft.id)
        )
        == "Updated objective"
    )


@pytest.mark.asyncio
async def test_report_lock_retires_old_draft_and_activates_one_new_draft(
    db_session: AsyncSession,
) -> None:
    owner, report, original = await seed_report(db_session, subject="restore-owner")
    restored = await activate_restored_draft(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        objectives=["Restored objective"],
    )
    await db_session.flush()
    await db_session.refresh(original)
    assert not original.is_active
    assert restored.is_active
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportDraft)
            .where(ReportDraft.report_id == report.id, ReportDraft.is_active.is_(True))
        )
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_restoration_leaves_exactly_one_active_draft() -> None:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    principal_id = uuid4()
    report_id = uuid4()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup, setup.begin():
            owner = Principal(
                id=principal_id,
                identity_namespace="test",
                subject=f"concurrent-restore-{principal_id}",
            )
            setup.add(owner)
            await setup.flush()
            report, _draft = await create_report(
                setup,
                owner_id=owner.id,
                name="Concurrent restoration",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                objectives=["Original objective"],
            )
            report_id = report.id

        async def restore(objective: str) -> None:
            async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
                await activate_restored_draft(
                    session,
                    owner_id=principal_id,
                    report_id=report_id,
                    objectives=[objective],
                )

        await asyncio.gather(restore("First restoration"), restore("Second restoration"))

        async with AsyncSession(engine) as verification:
            active = await verification.scalar(
                select(func.count())
                .select_from(ReportDraft)
                .where(ReportDraft.report_id == report_id, ReportDraft.is_active.is_(True))
            )
            assert active == 1
    finally:
        async with AsyncSession(engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                delete(DraftObjective).where(DraftObjective.report_id == report_id)
            )
            await cleanup.execute(delete(ReportDraft).where(ReportDraft.report_id == report_id))
            await cleanup.execute(delete(Report).where(Report.id == report_id))
            await cleanup.execute(delete(Principal).where(Principal.id == principal_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_cross_owner_draft_relationship_is_rejected(db_session: AsyncSession) -> None:
    _owner, report, _ = await seed_report(db_session, subject="aggregate-a")
    other = Principal(identity_namespace="test", subject="aggregate-b")
    db_session.add(other)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ReportDraft(owner_id=other.id, report_id=report.id, revision=1, is_active=False)
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_principal_identity_is_unique(db_session: AsyncSession) -> None:
    db_session.add(Principal(identity_namespace="provider", subject="duplicate"))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Principal(identity_namespace="provider", subject="duplicate"))
            await db_session.flush()


@pytest.mark.asyncio
async def test_cross_owner_current_pointer_is_rejected(db_session: AsyncSession) -> None:
    _first_owner, first_report, _ = await seed_report(db_session, subject="pointer-owner-a")
    second_owner, second_report, _ = await seed_report(db_session, subject="pointer-owner-b")
    source = ReportSource(
        owner_id=second_owner.id,
        report_id=second_report.id,
        source_type="text",
        checksum_sha256=b"s" * 32,
        byte_size=4,
        media_type="text/plain",
        encoding="utf-8",
        inline_text="safe",
    )
    db_session.add(source)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            first_report.current_source_id = source.id
            await db_session.flush()
            await db_session.execute(text("SET CONSTRAINTS fk_reports_current_source IMMEDIATE"))


@pytest.mark.asyncio
async def test_draft_children_reject_invalid_shape_and_cross_report_reference(
    db_session: AsyncSession,
) -> None:
    owner, first_report, first_draft = await seed_report(db_session, subject="draft-children")
    second_report, second_draft = await create_report(
        db_session,
        owner_id=owner.id,
        name="Second report",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        objectives=["Second objective"],
    )
    item = DraftNarrativeItem(
        owner_id=owner.id,
        report_id=first_report.id,
        draft_id=first_draft.id,
        section="summary",
        ordinal=1,
        content="Narrative",
        classification="observation",
    )
    claim = DraftClaim(
        owner_id=owner.id,
        report_id=second_report.id,
        draft_id=second_draft.id,
        ordinal=1,
        content="Claim",
        classification="user_claim",
    )
    db_session.add_all([item, claim])
    await db_session.flush()

    invalid_children = (
        DraftNarrativeItem(
            owner_id=owner.id,
            report_id=first_report.id,
            draft_id=first_draft.id,
            section="unsupported",
            ordinal=2,
            content="Narrative",
        ),
        DraftLimitation(
            owner_id=owner.id,
            report_id=first_report.id,
            draft_id=first_draft.id,
            ordinal=1,
            content=" ",
        ),
        DraftObjective(
            owner_id=owner.id,
            report_id=first_report.id,
            draft_id=first_draft.id,
            ordinal=1,
            content="Duplicate ordinal",
        ),
    )
    for child in invalid_children:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(child)
                await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                DraftItemClaimReference(
                    item_id=item.id,
                    claim_id=claim.id,
                    owner_id=owner.id,
                    report_id=first_report.id,
                    draft_id=first_draft.id,
                )
            )
            await db_session.flush()
