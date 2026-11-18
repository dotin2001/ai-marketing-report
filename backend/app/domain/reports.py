"""Owner-scoped report lifecycle commands and public projections."""

from __future__ import annotations

import base64
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.report_schemas import (
    Claim,
    CreateReportRequest,
    DraftDetail,
    DraftReference,
    Limitation,
    MetadataPatchRequest,
    NarrativeItem,
    ObjectivesPatchRequest,
    Page,
    Period,
    ReportDetail,
    ReportSummary,
    VersionReference,
)
from app.db.models import (
    AnalysisJob,
    DraftClaim,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    Report,
    ReportDraft,
    ReportSource,
    ReportVersion,
    SourceReviewConfirmation,
)
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    create_report,
    finalize_idempotency,
    get_report,
    resolve_idempotency,
    save_draft_objectives,
)
from app.db.session import transaction

ROOT_SCOPE = UUID(int=0)
CURSOR_ROUTE = "/api/v1/reports"
CURSOR_ORDER = "created_at:desc,id:desc"


class ReportNotFound(Exception):
    pass


class InvalidCursor(Exception):
    pass


def validate_idempotency_key(key: str) -> None:
    if not 1 <= len(key) <= 128 or re.fullmatch(r"[A-Za-z0-9._:-]+", key) is None:
        raise ValueError("invalid idempotency key")


def command_fingerprint(command: CreateReportRequest) -> bytes:
    canonical = command.model_dump(mode="json")
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).digest()


class ReportServices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], cursor_secret: str) -> None:
        self.sessions = sessions
        self.cursor_secret = cursor_secret.encode()

    def _encode_cursor(self, owner_id: UUID, report: Report) -> str:
        body = {
            "v": 1,
            "owner": str(owner_id),
            "route": CURSOR_ROUTE,
            "filters": {},
            "order": CURSOR_ORDER,
            "created_at": report.created_at.astimezone(UTC).isoformat(),
            "id": str(report.id),
            "expires_at": int((datetime.now(UTC) + timedelta(hours=24)).timestamp()),
        }
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.cursor_secret, payload, sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def _decode_cursor(self, owner_id: UUID, cursor: str) -> tuple[datetime, UUID]:
        try:
            if not cursor or len(cursor) > 2048 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
                raise ValueError
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor:
                raise ValueError
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                signature, hmac.new(self.cursor_secret, payload, sha256).digest()
            ):
                raise ValueError
            body = json.loads(payload)
            if (
                body["v"] != 1
                or body["owner"] != str(owner_id)
                or body["route"] != CURSOR_ROUTE
                or body["filters"] != {}
                or body["order"] != CURSOR_ORDER
                or body["expires_at"] <= int(datetime.now(UTC).timestamp())
            ):
                raise ValueError
            boundary = datetime.fromisoformat(body["created_at"])
            if boundary.tzinfo is None:
                raise ValueError
            return boundary, UUID(body["id"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidCursor from error

    async def _draft(
        self, session: AsyncSession, report: Report, *, lock: bool = False
    ) -> ReportDraft:
        query = select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.owner_id == report.owner_id,
            ReportDraft.is_active.is_(True),
        )
        draft = await session.scalar(query.with_for_update() if lock else query)
        if draft is None:
            raise ConcurrencyConflict("active draft is unavailable")
        return draft

    async def _latest_version(self, session: AsyncSession, report: Report) -> ReportVersion | None:
        return await session.scalar(
            select(ReportVersion)
            .where(ReportVersion.report_id == report.id, ReportVersion.owner_id == report.owner_id)
            .order_by(ReportVersion.version_number.desc(), ReportVersion.id.desc())
            .limit(1)
        )

    async def _stage(
        self,
        session: AsyncSession,
        report: Report,
        draft: ReportDraft,
        version: ReportVersion | None,
    ) -> str:
        if report.current_source_id is None:
            return "created"
        if report.current_dataset_id is None or report.current_metric_result_set_id is None:
            source = await session.scalar(
                select(ReportSource).where(
                    ReportSource.id == report.current_source_id,
                    ReportSource.report_id == report.id,
                    ReportSource.owner_id == report.owner_id,
                )
            )
            if source is None or source.source_type != "text":
                return "source_review"
            confirmed = await session.scalar(
                select(SourceReviewConfirmation.id).where(
                    SourceReviewConfirmation.source_id == source.id,
                    SourceReviewConfirmation.report_id == report.id,
                    SourceReviewConfirmation.owner_id == report.owner_id,
                    SourceReviewConfirmation.source_checksum == source.checksum_sha256,
                    SourceReviewConfirmation.period_start == report.period_start,
                    SourceReviewConfirmation.period_end == report.period_end,
                    SourceReviewConfirmation.period_revision == report.period_revision,
                )
            )
            if confirmed is None:
                return "source_review"
            if (
                version is not None
                and version.source_draft_id == draft.id
                and version.source_draft_revision == draft.revision
            ):
                return "versioned"
            if report.current_analysis_result_id is not None:
                return "reviewing"
            return "analysis_ready"
        current_job = await session.scalar(
            select(AnalysisJob.state)
            .where(
                AnalysisJob.report_id == report.id,
                AnalysisJob.owner_id == report.owner_id,
                AnalysisJob.dataset_id == report.current_dataset_id,
                AnalysisJob.metric_result_set_id == report.current_metric_result_set_id,
                AnalysisJob.objectives_revision == draft.objectives_revision,
            )
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        )
        if current_job in {"queued", "running"}:
            return "analysis_pending"
        if (
            version is not None
            and version.source_draft_id == draft.id
            and version.source_draft_revision == draft.revision
        ):
            return "versioned"
        if report.current_analysis_result_id is None:
            return "analysis_ready"
        return "reviewing"

    async def _summary(self, session: AsyncSession, report: Report) -> ReportSummary:
        draft = await self._draft(session, report)
        version = await self._latest_version(session, report)
        return ReportSummary(
            id=report.id,
            name=report.name,
            period=Period(start_date=report.period_start, end_date=report.period_end),
            stage=await self._stage(session, report, draft, version),
            active_draft=DraftReference(id=draft.id, revision=draft.revision),
            current_source_id=report.current_source_id,
            current_dataset_id=report.current_dataset_id,
            current_analysis_result_id=report.current_analysis_result_id,
            latest_version=VersionReference(id=version.id, version_number=version.version_number)
            if version
            else None,
            created_at=report.created_at,
            updated_at=report.updated_at,
        )

    async def _detail(self, session: AsyncSession, report: Report) -> ReportDetail:
        summary = await self._summary(session, report)
        draft = await self._draft(session, report)
        objectives = list(
            await session.scalars(
                select(DraftObjective.content)
                .where(
                    DraftObjective.draft_id == draft.id,
                    DraftObjective.report_id == report.id,
                    DraftObjective.owner_id == report.owner_id,
                )
                .order_by(DraftObjective.ordinal)
            )
        )
        narrative = list(
            await session.scalars(
                select(DraftNarrativeItem)
                .where(
                    DraftNarrativeItem.draft_id == draft.id,
                    DraftNarrativeItem.report_id == report.id,
                    DraftNarrativeItem.owner_id == report.owner_id,
                )
                .order_by(DraftNarrativeItem.section, DraftNarrativeItem.ordinal)
            )
        )
        claims = list(
            await session.scalars(
                select(DraftClaim)
                .where(
                    DraftClaim.draft_id == draft.id,
                    DraftClaim.report_id == report.id,
                    DraftClaim.owner_id == report.owner_id,
                )
                .order_by(DraftClaim.ordinal)
            )
        )
        limitations = list(
            await session.scalars(
                select(DraftLimitation)
                .where(
                    DraftLimitation.draft_id == draft.id,
                    DraftLimitation.report_id == report.id,
                    DraftLimitation.owner_id == report.owner_id,
                )
                .order_by(DraftLimitation.ordinal)
            )
        )
        detail = DraftDetail(
            id=draft.id,
            report_id=report.id,
            revision=draft.revision,
            objectives=objectives,
            narrative=[
                NarrativeItem(
                    id=item.id,
                    section=item.section,
                    ordinal=item.ordinal,
                    content=item.content,
                    classification=item.classification,
                )
                for item in narrative
            ],
            claims=[
                Claim(
                    id=item.id,
                    ordinal=item.ordinal,
                    content=item.content,
                    classification=item.classification,
                    source_id=item.source_id,
                )
                for item in claims
            ],
            limitations=[
                Limitation(id=item.id, ordinal=item.ordinal, content=item.content)
                for item in limitations
            ],
            current_metric_result_set_id=draft.current_metric_result_set_id,
            current_analysis_result_id=draft.current_analysis_result_id,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
        return ReportDetail(
            **summary.model_dump(mode="json", exclude={"active_draft"}),
            objectives=objectives,
            active_draft=detail,
            current_metric_result_set_id=report.current_metric_result_set_id,
        )

    async def create(
        self, owner_id: UUID, command: CreateReportRequest, key: str
    ) -> tuple[ReportDetail, bool]:
        validate_idempotency_key(key)
        async with transaction(self.sessions) as session:
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="create-report",
                scope_kind="root",
                scope_id=ROOT_SCOPE,
                raw_key=key,
                command_fingerprint=command_fingerprint(command),
            )
            if record.result_id is not None:
                if record.result_type != "report" or record.success_status != 201:
                    raise IdempotencyConflict("idempotency result differs")
                report = await get_report(session, owner_id=owner_id, report_id=record.result_id)
                if report is None or record.result_snapshot is None:
                    raise IdempotencyConflict("idempotency result is unavailable")
                return ReportDetail.model_validate_json(record.result_snapshot), True
            report, _ = await create_report(
                session,
                owner_id=owner_id,
                name=command.name,
                period_start=command.period.start_date,
                period_end=command.period.end_date,
                objectives=command.objectives,
            )
            detail = await self._detail(session, report)
            await finalize_idempotency(
                session,
                record=record,
                result_type="report",
                result_id=report.id,
                success_status=201,
                result_snapshot=detail.model_dump_json(),
            )
            return detail, False

    async def detail(self, owner_id: UUID, report_id: UUID) -> ReportDetail:
        async with transaction(self.sessions) as session:
            report = await get_report(session, owner_id=owner_id, report_id=report_id)
            if report is None:
                raise ReportNotFound
            return await self._detail(session, report)

    async def list(
        self, owner_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[ReportSummary], Page]:
        boundary = self._decode_cursor(owner_id, cursor) if cursor is not None else None
        async with transaction(self.sessions) as session:
            query = select(Report).where(Report.owner_id == owner_id)
            if boundary is not None:
                query = query.where(
                    or_(
                        Report.created_at < boundary[0],
                        and_(Report.created_at == boundary[0], Report.id < boundary[1]),
                    )
                )
            reports = list(
                await session.scalars(
                    query.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit + 1)
                )
            )
            has_more = len(reports) > limit
            selected = reports[:limit]
            summaries = [await self._summary(session, report) for report in selected]
            return summaries, Page(
                limit=limit,
                has_more=has_more,
                next_cursor=self._encode_cursor(owner_id, selected[-1]) if has_more else None,
            )

    async def update_metadata(
        self, owner_id: UUID, report_id: UUID, command: MetadataPatchRequest
    ) -> ReportDetail:
        async with transaction(self.sessions) as session:
            report = await session.scalar(
                select(Report)
                .where(Report.id == report_id, Report.owner_id == owner_id)
                .with_for_update()
            )
            if report is None:
                raise ReportNotFound
            draft = await self._draft(session, report, lock=True)
            if draft.revision != command.expected_revision:
                raise ConcurrencyConflict("draft revision is stale")
            changed_name = command.name is not None and command.name != report.name
            changed_period = command.period is not None and (
                command.period.start_date != report.period_start
                or command.period.end_date != report.period_end
            )
            if changed_name or changed_period:
                values: dict[str, object] = {"updated_at": func.current_timestamp()}
                if changed_name:
                    values["name"] = command.name
                if changed_period:
                    assert command.period is not None
                    values.update(
                        period_start=command.period.start_date,
                        period_end=command.period.end_date,
                        period_revision=report.period_revision + 1,
                        current_dataset_id=None,
                        current_metric_result_set_id=None,
                        current_analysis_result_id=None,
                    )
                    await session.execute(
                        update(ReportDraft)
                        .where(ReportDraft.id == draft.id)
                        .values(current_metric_result_set_id=None, current_analysis_result_id=None)
                    )
                await session.execute(update(Report).where(Report.id == report.id).values(**values))
                await session.execute(
                    update(ReportDraft)
                    .where(ReportDraft.id == draft.id)
                    .values(revision=draft.revision + 1, updated_at=func.current_timestamp())
                )
                await session.refresh(report)
                await session.refresh(draft)
            return await self._detail(session, report)

    async def update_objectives(
        self, owner_id: UUID, report_id: UUID, command: ObjectivesPatchRequest
    ) -> DraftDetail:
        async with transaction(self.sessions) as session:
            report = await session.scalar(
                select(Report)
                .where(Report.id == report_id, Report.owner_id == owner_id)
                .with_for_update()
            )
            if report is None:
                raise ReportNotFound
            draft = await self._draft(session, report, lock=True)
            await save_draft_objectives(
                session,
                owner_id=owner_id,
                report_id=report_id,
                draft_id=draft.id,
                expected_revision=command.expected_revision,
                objectives=command.objectives,
            )
            await session.execute(
                update(Report)
                .where(Report.id == report.id)
                .values(current_analysis_result_id=None, updated_at=func.current_timestamp())
            )
            await session.execute(
                update(ReportDraft)
                .where(ReportDraft.id == draft.id)
                .values(current_analysis_result_id=None)
            )
            await session.refresh(report)
            return (await self._detail(session, report)).active_draft
