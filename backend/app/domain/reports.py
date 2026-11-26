"""Owner-scoped report lifecycle commands and public projections."""

from __future__ import annotations

import base64
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.report_schemas import (
    Chart,
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
    UpdateDraftRequest,
    VersionReference,
)
from app.db.models import (
    AnalysisJob,
    DraftChart,
    DraftChartMetricReference,
    DraftClaim,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    MetricResult,
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


class DraftValidationError(Exception):
    def __init__(self, path: list[str | int]) -> None:
        self.path = path
        super().__init__("invalid draft reference")


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
        section_order = {
            section: index
            for index, section in enumerate(
                ("summary", "findings", "anomalies", "recommendations", "data_gaps")
            )
        }
        narrative.sort(key=lambda item: (section_order[item.section], item.ordinal))
        claims = list(
            await session.scalars(
                select(DraftClaim)
                .where(
                    DraftClaim.draft_id == draft.id,
                    DraftClaim.report_id == report.id,
                    DraftClaim.owner_id == report.owner_id,
                    DraftClaim.is_active.is_(True),
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
        charts = list(
            await session.scalars(
                select(DraftChart)
                .where(
                    DraftChart.draft_id == draft.id,
                    DraftChart.report_id == report.id,
                    DraftChart.owner_id == report.owner_id,
                )
                .order_by(DraftChart.ordinal)
            )
        )
        chart_ids = [chart.id for chart in charts]
        chart_references = (
            list(
                await session.scalars(
                    select(DraftChartMetricReference)
                    .where(DraftChartMetricReference.chart_id.in_(chart_ids))
                    .order_by(DraftChartMetricReference.chart_id, DraftChartMetricReference.ordinal)
                )
            )
            if chart_ids
            else []
        )
        references_by_chart: dict[UUID, list[UUID]] = {chart_id: [] for chart_id in chart_ids}
        for reference in chart_references:
            references_by_chart[reference.chart_id].append(reference.metric_result_id)
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
            charts=[
                Chart(
                    id=chart.id,
                    ordinal=chart.ordinal,
                    chart_type=chart.chart_type,
                    title=chart.title,
                    scope=chart.scope,
                    x_label=chart.x_label,
                    y_label=chart.y_label,
                    metric_result_ids=references_by_chart[chart.id],
                )
                for chart in charts
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

    async def update_draft(
        self, owner_id: UUID, report_id: UUID, command: UpdateDraftRequest
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
            if draft.revision != command.expected_revision:
                raise ConcurrencyConflict("draft revision is stale")

            # Check all references before changing the revision or any collection.
            if command.claims is not None:
                source_ids = {claim.source_id for claim in command.claims if claim.source_id}
                found_sources = (
                    set(
                        await session.scalars(
                            select(ReportSource.id).where(
                                ReportSource.id.in_(source_ids),
                                ReportSource.owner_id == owner_id,
                                ReportSource.report_id == report_id,
                            )
                        )
                    )
                    if source_ids
                    else set()
                )
                for index, claim in enumerate(command.claims):
                    if claim.source_id is not None and claim.source_id not in found_sources:
                        raise DraftValidationError(["claims", index, "source_id"])
            if command.charts is not None:
                metric_ids = {
                    metric_id for chart in command.charts for metric_id in chart.metric_result_ids
                }
                metrics = (
                    {
                        metric_id: scope
                        for metric_id, scope in (
                            await session.execute(
                                select(MetricResult.id, MetricResult.scope).where(
                                    MetricResult.id.in_(metric_ids),
                                    MetricResult.owner_id == owner_id,
                                    MetricResult.report_id == report_id,
                                    MetricResult.result_set_id
                                    == report.current_metric_result_set_id,
                                )
                            )
                        ).all()
                    }
                    if report.current_metric_result_set_id is not None
                    else {}
                )
                for index, chart in enumerate(command.charts):
                    for metric_index, metric_id in enumerate(chart.metric_result_ids):
                        if metrics.get(metric_id) != chart.scope:
                            raise DraftValidationError(
                                ["charts", index, "metric_result_ids", metric_index]
                            )

            async def owned_rows(
                model: type[DraftNarrativeItem]
                | type[DraftLimitation]
                | type[DraftClaim]
                | type[DraftChart],
            ) -> dict[UUID, object]:
                return {
                    cast(Any, row).id: row
                    for row in await session.scalars(
                        select(model).where(
                            model.draft_id == draft.id,
                            model.report_id == report_id,
                            model.owner_id == owner_id,
                        )
                    )
                }

            if command.narrative is not None:
                old_narrative = cast(
                    dict[UUID, DraftNarrativeItem], await owned_rows(DraftNarrativeItem)
                )
                for index, narrative_edit in enumerate(command.narrative):
                    if narrative_edit.id is not None:
                        previous_narrative = old_narrative.get(narrative_edit.id)
                        if (
                            previous_narrative is None
                            or previous_narrative.section != narrative_edit.section
                            or previous_narrative.content != narrative_edit.content
                            or previous_narrative.classification != narrative_edit.classification
                        ):
                            raise DraftValidationError(["narrative", index, "id"])
            if command.limitations is not None:
                old_limitations = cast(
                    dict[UUID, DraftLimitation], await owned_rows(DraftLimitation)
                )
                for index, limitation_edit in enumerate(command.limitations):
                    if limitation_edit.id is not None:
                        previous_limitation = old_limitations.get(limitation_edit.id)
                        if (
                            previous_limitation is None
                            or previous_limitation.content != limitation_edit.content
                        ):
                            raise DraftValidationError(["limitations", index, "id"])
            if command.claims is not None:
                old_claims = {
                    row.id: row
                    for row in await session.scalars(
                        select(DraftClaim).where(
                            DraftClaim.draft_id == draft.id,
                            DraftClaim.owner_id == owner_id,
                            DraftClaim.report_id == report_id,
                            DraftClaim.is_active.is_(True),
                        )
                    )
                }
                for index, claim_edit in enumerate(command.claims):
                    if claim_edit.id is not None:
                        previous_claim = old_claims.get(claim_edit.id)
                        if (
                            previous_claim is None
                            or previous_claim.content != claim_edit.content
                            or previous_claim.classification != claim_edit.classification
                            or previous_claim.source_id != claim_edit.source_id
                        ):
                            raise DraftValidationError(["claims", index, "id"])
            if command.charts is not None:
                old_charts = cast(dict[UUID, DraftChart], await owned_rows(DraftChart))
                old_ids = list(old_charts)
                old_refs = (
                    list(
                        await session.scalars(
                            select(DraftChartMetricReference)
                            .where(DraftChartMetricReference.chart_id.in_(old_ids))
                            .order_by(
                                DraftChartMetricReference.chart_id,
                                DraftChartMetricReference.ordinal,
                            )
                        )
                    )
                    if old_ids
                    else []
                )
                old_metric_ids: dict[UUID, list[UUID]] = {chart_id: [] for chart_id in old_ids}
                for reference in old_refs:
                    old_metric_ids[reference.chart_id].append(reference.metric_result_id)
                for index, chart_edit in enumerate(command.charts):
                    if chart_edit.id is not None:
                        previous_chart = old_charts.get(chart_edit.id)
                        if (
                            previous_chart is None
                            or previous_chart.chart_type != chart_edit.chart_type
                            or previous_chart.title != chart_edit.title
                            or previous_chart.scope != chart_edit.scope
                            or previous_chart.x_label != chart_edit.x_label
                            or previous_chart.y_label != chart_edit.y_label
                            or old_metric_ids[chart_edit.id] != chart_edit.metric_result_ids
                        ):
                            raise DraftValidationError(["charts", index, "id"])

            for field in ("narrative", "limitations", "claims", "charts"):
                values = getattr(command, field)
                if values is not None:
                    identifiers = [entry.id for entry in values if entry.id is not None]
                    if len(identifiers) != len(set(identifiers)):
                        raise DraftValidationError([field])

            if command.objectives is not None:
                await session.execute(
                    delete(DraftObjective).where(DraftObjective.draft_id == draft.id)
                )
                session.add_all(
                    DraftObjective(
                        owner_id=owner_id,
                        report_id=report_id,
                        draft_id=draft.id,
                        ordinal=index,
                        content=value,
                    )
                    for index, value in enumerate(command.objectives, start=1)
                )
                draft.objectives_revision = draft.revision + 1
                draft.current_analysis_result_id = None
                report.current_analysis_result_id = None
            if command.narrative is not None:
                await session.execute(
                    delete(DraftNarrativeItem).where(DraftNarrativeItem.draft_id == draft.id)
                )
                section_ordinals: dict[str, int] = {}
                for narrative_edit in command.narrative:
                    section_ordinals[narrative_edit.section] = (
                        section_ordinals.get(narrative_edit.section, 0) + 1
                    )
                    values = dict(
                        owner_id=owner_id,
                        report_id=report_id,
                        draft_id=draft.id,
                        section=narrative_edit.section,
                        ordinal=section_ordinals[narrative_edit.section],
                        content=narrative_edit.content,
                        classification=narrative_edit.classification,
                    )
                    if narrative_edit.id is not None:
                        values["id"] = narrative_edit.id
                    session.add(DraftNarrativeItem(**values))
            if command.limitations is not None:
                await session.execute(
                    delete(DraftLimitation).where(DraftLimitation.draft_id == draft.id)
                )
                for index, limitation_edit in enumerate(command.limitations, start=1):
                    values = dict(
                        owner_id=owner_id,
                        report_id=report_id,
                        draft_id=draft.id,
                        ordinal=index,
                        content=limitation_edit.content,
                    )
                    if limitation_edit.id is not None:
                        values["id"] = limitation_edit.id
                    session.add(DraftLimitation(**values))
            if command.claims is not None:
                await session.execute(
                    update(DraftClaim)
                    .where(DraftClaim.draft_id == draft.id, DraftClaim.is_active.is_(True))
                    .values(is_active=False)
                )
                for index, claim_edit in enumerate(command.claims, start=1):
                    if claim_edit.id is not None:
                        await session.execute(
                            update(DraftClaim)
                            .where(DraftClaim.id == claim_edit.id, DraftClaim.draft_id == draft.id)
                            .values(is_active=True, ordinal=index)
                        )
                        continue
                    values = dict(
                        owner_id=owner_id,
                        report_id=report_id,
                        draft_id=draft.id,
                        ordinal=index,
                        content=claim_edit.content,
                        classification=claim_edit.classification,
                        source_id=claim_edit.source_id,
                    )
                    session.add(DraftClaim(**values))
            if command.charts is not None:
                if old_ids:
                    await session.execute(
                        delete(DraftChartMetricReference).where(
                            DraftChartMetricReference.chart_id.in_(old_ids)
                        )
                    )
                    await session.execute(delete(DraftChart).where(DraftChart.id.in_(old_ids)))
                for index, chart_edit in enumerate(command.charts, start=1):
                    values = dict(
                        owner_id=owner_id,
                        report_id=report_id,
                        draft_id=draft.id,
                        ordinal=index,
                        chart_type=chart_edit.chart_type,
                        title=chart_edit.title,
                        scope=chart_edit.scope,
                        x_label=chart_edit.x_label,
                        y_label=chart_edit.y_label,
                    )
                    if chart_edit.id is not None:
                        values["id"] = chart_edit.id
                    saved_chart = DraftChart(**values)
                    session.add(saved_chart)
                    await session.flush()
                    session.add_all(
                        DraftChartMetricReference(
                            chart_id=saved_chart.id,
                            ordinal=metric_index,
                            metric_result_id=metric_id,
                            owner_id=owner_id,
                            report_id=report_id,
                            draft_id=draft.id,
                        )
                        for metric_index, metric_id in enumerate(
                            chart_edit.metric_result_ids, start=1
                        )
                    )
            draft.revision += 1
            draft.updated_at = datetime.now(UTC)
            report.updated_at = datetime.now(UTC)
            await session.flush()
            return (await self._detail(session, report)).active_draft
