"""Durable, owner-scoped analysis lifecycle and post-commit dispatch."""

from __future__ import annotations

import base64
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.analysis_job_schemas import (
    AnalysisAttemptDetail,
    AnalysisJobDetail,
    AnalysisJobSummary,
    AnalysisResultItemPublic,
    AnalysisResultPublic,
    CreateAnalysisJobRequest,
    JobFailure,
    RetryAnalysisJobRequest,
)
from app.api.report_schemas import Page
from app.db.models import (
    AnalysisJob,
    AnalysisJobAttempt,
    AnalysisResult,
    AnalysisResultItem,
    CanonicalDataset,
    DraftObjective,
    MetricResultSet,
    Report,
    ReportDraft,
)
from app.db.repositories import (
    ANALYSIS_MAX_TOTAL_ATTEMPTS,
    ConcurrencyConflict,
    IdempotencyConflict,
    create_analysis_job,
    finalize_idempotency,
    queued_analysis_attempts,
    resolve_idempotency,
    retry_analysis_job,
)
from app.db.session import transaction
from app.domain.assets import ResourceNotFound
from app.domain.reports import InvalidCursor, validate_idempotency_key

Publisher = Callable[[UUID, UUID, UUID, int], None]
logger = logging.getLogger(__name__)


def publish_analysis_attempt(owner_id: UUID, report_id: UUID, job_id: UUID, ordinal: int) -> None:
    from app.core.config import Settings
    from app.jobs.celery_app import celery_app, configure_celery

    configure_celery(celery_app, Settings())
    celery_app.send_task(
        "analysis.execute",
        args=[str(owner_id), str(report_id), str(job_id), ordinal],
        retry=False,
    )


def _failure(code: str | None, message: str | None, retryable: bool | None) -> JobFailure | None:
    if code is None or message is None or retryable is None:
        return None
    return JobFailure(code=code, message=message, retryable=retryable)


def _summary(job: AnalysisJob) -> AnalysisJobSummary:
    return AnalysisJobSummary(
        id=job.id,
        report_id=job.report_id,
        state=job.state,
        attempt_count=job.attempt_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        failure=_failure(
            job.failure_code,
            job.failure_message,
            job.failure_retryable is True and job.attempt_count < ANALYSIS_MAX_TOTAL_ATTEMPTS
            if job.failure_retryable is not None
            else None,
        ),
    )


async def _detail(session: AsyncSession, job: AnalysisJob) -> AnalysisJobDetail:
    attempts = list(
        (
            await session.scalars(
                select(AnalysisJobAttempt)
                .where(
                    AnalysisJobAttempt.owner_id == job.owner_id,
                    AnalysisJobAttempt.report_id == job.report_id,
                    AnalysisJobAttempt.job_id == job.id,
                )
                .order_by(AnalysisJobAttempt.attempt_ordinal)
            )
        ).all()
    )
    public_result = None
    if job.state == "succeeded" and job.current_result_id is not None:
        result = await session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.id == job.current_result_id,
                AnalysisResult.job_id == job.id,
                AnalysisResult.owner_id == job.owner_id,
                AnalysisResult.report_id == job.report_id,
            )
        )
        if result is not None:
            result_items = list(
                (
                    await session.scalars(
                        select(AnalysisResultItem)
                        .where(
                            AnalysisResultItem.result_id == result.id,
                            AnalysisResultItem.owner_id == job.owner_id,
                            AnalysisResultItem.report_id == job.report_id,
                        )
                        .order_by(AnalysisResultItem.section, AnalysisResultItem.ordinal)
                    )
                ).all()
            )
            sections: dict[str, list[AnalysisResultItemPublic]] = {
                key: []
                for key in ("summary", "findings", "anomalies", "recommendations", "data_gaps")
            }
            for item in result_items:
                sections[item.section].append(
                    AnalysisResultItemPublic(
                        section=item.section,
                        ordinal=item.ordinal,
                        classification=item.classification,
                        content=item.content,
                    )
                )
            public_result = AnalysisResultPublic(
                id=result.id,
                model_identifier=result.model_identifier,
                prompt_version=result.prompt_version,
                request_provenance=result.request_provenance,
                created_at=result.created_at,
                **sections,
            )
    return AnalysisJobDetail(
        **_summary(job).model_dump(),
        dataset_id=job.dataset_id,
        metric_result_set_id=job.metric_result_set_id,
        draft_id=job.draft_id,
        draft_revision=job.draft_revision,
        result_id=job.current_result_id if job.state == "succeeded" else None,
        result=public_result,
        attempts=[
            AnalysisAttemptDetail(
                ordinal=item.attempt_ordinal,
                state=item.state,
                queued_at=item.queued_at,
                started_at=item.started_at,
                finished_at=item.finished_at,
                failure=_failure(item.failure_code, item.failure_message, item.failure_retryable),
            )
            for item in attempts
        ],
    )


async def current_analysis_input(
    session: AsyncSession,
    report: Report,
    expected_revision: int,
    dataset_id: UUID | None = None,
    metric_result_set_id: UUID | None = None,
) -> tuple[ReportDraft, CanonicalDataset, MetricResultSet, bytes]:
    draft = await session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.owner_id == report.owner_id,
            ReportDraft.is_active.is_(True),
        )
    )
    if (
        draft is None
        or draft.revision != expected_revision
        or report.current_dataset_id is None
        or report.current_metric_result_set_id is None
        or (dataset_id is not None and dataset_id != report.current_dataset_id)
        or (
            metric_result_set_id is not None
            and metric_result_set_id != report.current_metric_result_set_id
        )
    ):
        raise ConcurrencyConflict("analysis input is stale")
    dataset = await session.scalar(
        select(CanonicalDataset).where(
            CanonicalDataset.id == report.current_dataset_id,
            CanonicalDataset.owner_id == report.owner_id,
            CanonicalDataset.report_id == report.id,
        )
    )
    metrics = await session.scalar(
        select(MetricResultSet).where(
            MetricResultSet.id == report.current_metric_result_set_id,
            MetricResultSet.dataset_id == report.current_dataset_id,
            MetricResultSet.owner_id == report.owner_id,
            MetricResultSet.report_id == report.id,
        )
    )
    if dataset is None or metrics is None:
        raise ConcurrencyConflict("analysis inputs are unavailable")
    objectives = list(
        (
            await session.scalars(
                select(DraftObjective.content)
                .where(
                    DraftObjective.draft_id == draft.id,
                    DraftObjective.owner_id == report.owner_id,
                    DraftObjective.report_id == report.id,
                )
                .order_by(DraftObjective.ordinal)
            )
        ).all()
    )
    identity = sha256(
        json.dumps(
            {
                "report": str(report.id),
                "source": str(dataset.source_id),
                "confirmation": str(dataset.confirmation_id),
                "dataset": str(dataset.id),
                "canonical": dataset.canonical_data_identity.hex(),
                "metrics": str(metrics.id),
                "metric_identity": metrics.identity.hex(),
                "calculation_version": metrics.calculation_version,
                "draft": str(draft.id),
                "draft_revision": draft.revision,
                "objectives_revision": draft.objectives_revision,
                "objectives": objectives,
                "period_revision": report.period_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).digest()
    return draft, dataset, metrics, identity


class AnalysisJobServices:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cursor_secret: str,
        publisher: Publisher = publish_analysis_attempt,
    ) -> None:
        self.sessions = sessions
        self.secret = cursor_secret.encode()
        self.publisher = publisher

    async def _report(self, session: AsyncSession, owner_id: UUID, report_id: UUID) -> Report:
        report = await session.scalar(
            select(Report).where(Report.id == report_id, Report.owner_id == owner_id)
        )
        if report is None:
            raise ResourceNotFound
        return report

    async def _job(
        self, session: AsyncSession, owner_id: UUID, report_id: UUID, job_id: UUID
    ) -> AnalysisJob:
        job = await session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.id == job_id,
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
            )
        )
        if job is None:
            raise ResourceNotFound
        return job

    async def _current_input(
        self,
        session: AsyncSession,
        report: Report,
        expected_revision: int,
        dataset_id: UUID | None = None,
        metric_result_set_id: UUID | None = None,
    ) -> tuple[ReportDraft, CanonicalDataset, MetricResultSet, bytes]:
        return await current_analysis_input(
            session, report, expected_revision, dataset_id, metric_result_set_id
        )

    def _dispatch(self, owner_id: UUID, report_id: UUID, job_id: UUID, ordinal: int) -> None:
        try:
            self.publisher(owner_id, report_id, job_id, ordinal)
        except Exception:
            logger.warning(
                "Analysis delivery pending recovery: job_id=%s ordinal=%d", job_id, ordinal
            )

    async def create(
        self,
        owner_id: UUID,
        report_id: UUID,
        command: CreateAnalysisJobRequest,
        key: str,
    ) -> tuple[AnalysisJobDetail, bool]:
        validate_idempotency_key(key)
        fingerprint = sha256(command.model_dump_json().encode()).digest()
        async with transaction(self.sessions) as session:
            report = await self._report(session, owner_id, report_id)
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="create-analysis",
                scope_kind="report",
                scope_id=report_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            replayed = record.result_id is not None
            new_attempt = False
            if replayed:
                if record.result_type != "analysis_job":
                    raise IdempotencyConflict("idempotency result type changed")
                assert record.result_id is not None
                job = await self._job(session, owner_id, report_id, record.result_id)
            else:
                draft, dataset, metrics, identity = await self._current_input(
                    session,
                    report,
                    command.expected_revision,
                    command.dataset_id,
                    command.metric_result_set_id,
                )
                await session.scalar(
                    select(Report.id)
                    .where(Report.id == report_id, Report.owner_id == owner_id)
                    .with_for_update()
                )
                new_attempt = (
                    await session.scalar(
                        select(AnalysisJob.id).where(
                            AnalysisJob.report_id == report_id,
                            AnalysisJob.semantic_input_identity == identity,
                        )
                    )
                    is None
                )
                job = await create_analysis_job(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    semantic_input_identity=identity,
                    dataset_id=dataset.id,
                    metric_result_set_id=metrics.id,
                    draft_id=draft.id,
                    draft_revision=draft.revision,
                    objectives_revision=draft.objectives_revision,
                    idempotency=record,
                )
            detail = await _detail(session, job)
        if new_attempt and job.state == "queued":
            self._dispatch(owner_id, report_id, job.id, job.attempt_count)
        return detail, replayed

    async def detail(self, owner_id: UUID, report_id: UUID, job_id: UUID) -> AnalysisJobDetail:
        async with self.sessions() as session:
            await self._report(session, owner_id, report_id)
            return await _detail(session, await self._job(session, owner_id, report_id, job_id))

    def _encode_cursor(self, owner_id: UUID, report_id: UUID, job: AnalysisJob) -> str:
        body = {
            "v": 1,
            "owner": str(owner_id),
            "report": str(report_id),
            "route": "analysis-jobs",
            "created_at": job.created_at.astimezone(UTC).isoformat(),
            "id": str(job.id),
            "expires_at": int((datetime.now(UTC) + timedelta(hours=24)).timestamp()),
        }
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return (
            base64.urlsafe_b64encode(payload + hmac.new(self.secret, payload, sha256).digest())
            .decode()
            .rstrip("=")
        )

    def _decode_cursor(self, owner_id: UUID, report_id: UUID, cursor: str) -> tuple[datetime, UUID]:
        try:
            if not cursor or len(cursor) > 2048:
                raise ValueError
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor:
                raise ValueError
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.new(self.secret, payload, sha256).digest()):
                raise ValueError
            body = json.loads(payload)
            if (
                body["v"] != 1
                or body["owner"] != str(owner_id)
                or body["report"] != str(report_id)
                or body["route"] != "analysis-jobs"
                or body["expires_at"] <= int(datetime.now(UTC).timestamp())
            ):
                raise ValueError
            instant = datetime.fromisoformat(body["created_at"])
            if instant.tzinfo is None:
                raise ValueError
            return instant, UUID(body["id"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidCursor from error

    async def list(
        self,
        owner_id: UUID,
        report_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[AnalysisJobSummary], Page]:
        async with self.sessions() as session:
            await self._report(session, owner_id, report_id)
            query = select(AnalysisJob).where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
            )
            if cursor is not None:
                instant, job_id = self._decode_cursor(owner_id, report_id, cursor)
                query = query.where(
                    or_(
                        AnalysisJob.created_at < instant,
                        and_(AnalysisJob.created_at == instant, AnalysisJob.id < job_id),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(
                            AnalysisJob.created_at.desc(),
                            AnalysisJob.id.desc(),
                        ).limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            visible = rows[:limit]
            return (
                [_summary(job) for job in visible],
                Page(
                    limit=limit,
                    has_more=has_more,
                    next_cursor=self._encode_cursor(owner_id, report_id, visible[-1])
                    if has_more
                    else None,
                ),
            )

    async def retry(
        self,
        owner_id: UUID,
        report_id: UUID,
        job_id: UUID,
        command: RetryAnalysisJobRequest,
        key: str,
    ) -> tuple[AnalysisJobDetail, bool]:
        validate_idempotency_key(key)
        fingerprint = sha256(f"{job_id}:{command.expected_attempt_count}".encode()).digest()
        async with transaction(self.sessions) as session:
            report = await self._report(session, owner_id, report_id)
            job = await self._job(session, owner_id, report_id, job_id)
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="retry-analysis",
                scope_kind="analysis_job",
                scope_id=job_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            replayed = record.result_id is not None
            if replayed:
                if record.result_id != job_id:
                    raise IdempotencyConflict("retry target changed")
            else:
                draft, _dataset, _metrics, identity = await self._current_input(
                    session,
                    report,
                    job.draft_revision,
                    job.dataset_id,
                    job.metric_result_set_id,
                )
                if (
                    identity != job.semantic_input_identity
                    or draft.objectives_revision != job.objectives_revision
                ):
                    raise ConcurrencyConflict("analysis input is stale")
                await retry_analysis_job(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    job_id=job_id,
                    expected_attempt_count=command.expected_attempt_count,
                )
                await finalize_idempotency(
                    session,
                    record=record,
                    result_type="analysis_job",
                    result_id=job_id,
                    success_status=202,
                )
                await session.refresh(job)
            detail = await _detail(session, job)
        if not replayed and job.state == "queued":
            self._dispatch(owner_id, report_id, job.id, job.attempt_count)
        return detail, replayed

    async def reconcile(self, limit: int = 100) -> int:
        async with self.sessions() as session:
            pending = await queued_analysis_attempts(session, limit=limit)
        for owner_id, report_id, job_id, ordinal in pending:
            self._dispatch(owner_id, report_id, job_id, ordinal)
        return len(pending)
