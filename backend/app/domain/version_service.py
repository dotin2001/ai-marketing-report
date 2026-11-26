"""Owner-scoped commands and public projections for saved report versions."""

from __future__ import annotations

import base64
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.report_schemas import DraftDetail, Page
from app.api.version_schemas import PdfExportSummary, VersionDetail, VersionSummary
from app.db.models import IdempotencyRecord, PdfExport, ReportVersion
from app.db.repositories import get_report, get_version, list_versions_page
from app.db.session import transaction
from app.db.snapshots import parse_report_version_snapshot
from app.domain.reports import (
    InvalidCursor,
    ReportNotFound,
    ReportServices,
    validate_idempotency_key,
)
from app.domain.versions import restore_saved_version, save_current_report_version

CURSOR_ROUTE = "/api/v1/reports/{report_id}/versions"
CURSOR_ORDER = "version_number:desc,id:desc"
REPORT_TEMPLATE_VERSION = "report-v1"


class VersionNotFound(Exception):
    pass


class VersionServices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], cursor_secret: str) -> None:
        self.sessions = sessions
        self.cursor_secret = cursor_secret.encode()
        self.reports = ReportServices(sessions, cursor_secret)

    def _encode_cursor(self, owner_id: UUID, report_id: UUID, version: ReportVersion) -> str:
        body = {
            "v": 1,
            "owner": str(owner_id),
            "report": str(report_id),
            "route": CURSOR_ROUTE,
            "order": CURSOR_ORDER,
            "number": version.version_number,
            "id": str(version.id),
            "expires_at": int((datetime.now(UTC) + timedelta(hours=24)).timestamp()),
        }
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.cursor_secret, payload, sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def _decode_cursor(self, owner_id: UUID, report_id: UUID, cursor: str) -> tuple[int, UUID]:
        try:
            if not cursor or len(cursor) > 2048 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
                raise ValueError
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor or len(raw) <= 32:
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
                or body["report"] != str(report_id)
                or body["route"] != CURSOR_ROUTE
                or body["order"] != CURSOR_ORDER
                or type(body["number"]) is not int
                or body["number"] <= 0
                or type(body["expires_at"]) is not int
                or body["expires_at"] <= int(datetime.now(UTC).timestamp())
            ):
                raise ValueError
            return body["number"], UUID(body["id"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidCursor from error

    async def _summary(self, session: AsyncSession, version: ReportVersion) -> VersionSummary:
        export = await session.scalar(
            select(PdfExport)
            .where(
                PdfExport.owner_id == version.owner_id,
                PdfExport.report_id == version.report_id,
                PdfExport.version_id == version.id,
            )
            .order_by(PdfExport.created_at.desc(), PdfExport.id.desc())
            .limit(1)
        )
        return VersionSummary(
            id=version.id,
            report_id=version.report_id,
            version_number=version.version_number,
            source_draft_id=version.source_draft_id,
            source_draft_revision=version.source_draft_revision,
            template_version=version.template_version,
            snapshot_schema_version=version.snapshot_schema_version,
            snapshot_identity=version.snapshot_identity.hex(),
            dataset_id=version.dataset_id if version.snapshot_schema_version == 2 else None,
            metric_result_set_id=(
                version.metric_result_set_id if version.snapshot_schema_version == 2 else None
            ),
            analysis_result_id=(
                version.analysis_result_id if version.snapshot_schema_version == 2 else None
            ),
            latest_pdf_export=(
                PdfExportSummary(
                    id=export.id,
                    report_id=export.report_id,
                    version_id=export.version_id,
                    template_version=export.template_version,
                    input_identity=export.input_identity.hex(),
                    state=export.state,
                    attempt_count=export.attempt_count,
                    created_at=export.created_at,
                    updated_at=export.updated_at,
                )
                if export is not None
                else None
            ),
            created_at=version.created_at,
        )

    async def _detail(self, session: AsyncSession, version: ReportVersion) -> VersionDetail:
        snapshot = parse_report_version_snapshot(version.snapshot)
        summary = await self._summary(session, version)
        return VersionDetail(**summary.model_dump(), snapshot=snapshot)

    async def _idempotency_record(
        self, session: AsyncSession, owner_id: UUID, report_id: UUID, key: str
    ) -> IdempotencyRecord | None:
        return await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.principal_id == owner_id,
                IdempotencyRecord.operation == "create-version-v2",
                IdempotencyRecord.scope_kind == "report",
                IdempotencyRecord.scope_id == report_id,
                IdempotencyRecord.key_digest == sha256(key.encode()).digest(),
            )
        )

    async def create(
        self, owner_id: UUID, report_id: UUID, expected_revision: int, key: str
    ) -> tuple[VersionDetail, bool]:
        validate_idempotency_key(key)
        async with transaction(self.sessions) as session:
            report = await get_report(session, owner_id=owner_id, report_id=report_id)
            if report is None:
                raise ReportNotFound
            prior = await self._idempotency_record(session, owner_id, report_id, key)
            previous_version = (
                await get_version(
                    session, owner_id=owner_id, report_id=report_id, version_id=prior.result_id
                )
                if prior is not None and prior.result_type == "report_version" and prior.result_id
                else None
            )
            draft_id = previous_version.source_draft_id if previous_version else None
            if draft_id is None:
                draft = await self.reports._draft(session, report)
                draft_id = draft.id
            replay_state: list[bool] = []
            version = await save_current_report_version(
                session,
                owner_id=owner_id,
                report_id=report_id,
                draft_id=draft_id,
                expected_revision=expected_revision,
                template_version=REPORT_TEMPLATE_VERSION,
                idempotency_key=key,
                replayed=replay_state,
            )
            return await self._detail(session, version), bool(replay_state)

    async def list(
        self, owner_id: UUID, report_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[VersionSummary], Page]:
        boundary = self._decode_cursor(owner_id, report_id, cursor) if cursor is not None else None
        async with transaction(self.sessions) as session:
            if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
                raise ReportNotFound
            rows = list(
                await list_versions_page(
                    session, owner_id=owner_id, report_id=report_id, limit=limit, before=boundary
                )
            )
            has_more = len(rows) > limit
            visible = rows[:limit]
            return [await self._summary(session, row) for row in visible], Page(
                limit=limit,
                has_more=has_more,
                next_cursor=(
                    self._encode_cursor(owner_id, report_id, visible[-1]) if has_more else None
                ),
            )

    async def detail(self, owner_id: UUID, report_id: UUID, version_id: UUID) -> VersionDetail:
        async with transaction(self.sessions) as session:
            if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
                raise ReportNotFound
            version = await get_version(
                session, owner_id=owner_id, report_id=report_id, version_id=version_id
            )
            if version is None:
                raise VersionNotFound
            return await self._detail(session, version)

    async def restore(
        self,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        expected_draft_id: UUID,
        expected_revision: int,
        key: str,
    ) -> tuple[DraftDetail, bool]:
        validate_idempotency_key(key)
        async with transaction(self.sessions) as session:
            report = await get_report(session, owner_id=owner_id, report_id=report_id)
            if report is None:
                raise ReportNotFound
            version = await get_version(
                session, owner_id=owner_id, report_id=report_id, version_id=version_id
            )
            if version is None:
                raise VersionNotFound
            replay_state: list[bool] = []
            draft = await restore_saved_version(
                session,
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                expected_draft_id=expected_draft_id,
                expected_revision=expected_revision,
                idempotency_key=key,
                replayed=replay_state,
            )
            return await self.reports.draft_detail(session, report, draft), bool(replay_state)
