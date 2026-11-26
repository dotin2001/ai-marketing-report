"""Immutable, validated input boundary for report PDF rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.db.models import ReportVersion
from app.db.repositories import report_snapshot_identity
from app.db.snapshots import (
    ReportVersionSnapshot,
    ReportVersionSnapshotV2,
    parse_report_version_snapshot,
)
from app.pdf.errors import PdfRenderFailure

SUPPORTED_TEMPLATE = "report-v1"


@dataclass(frozen=True, slots=True)
class SavedVersion:
    """A copy of version columns and JSONB bytes, independent of the ORM session."""

    version_id: UUID
    report_id: UUID
    version_number: int
    created_at: datetime
    snapshot_identity: bytes
    snapshot_schema_version: int
    template_version: str
    snapshot_json: bytes

    @classmethod
    def from_record(cls, record: ReportVersion) -> SavedVersion:
        return cls(
            version_id=record.id,
            report_id=record.report_id,
            version_number=record.version_number,
            created_at=record.created_at,
            snapshot_identity=bytes(record.snapshot_identity),
            snapshot_schema_version=record.snapshot_schema_version,
            template_version=record.template_version,
            snapshot_json=json.dumps(
                record.snapshot, sort_keys=True, separators=(",", ":")
            ).encode(),
        )

    def validated_snapshot(self) -> ReportVersionSnapshot | ReportVersionSnapshotV2:
        try:
            if (
                self.version_number < 1
                or self.created_at.tzinfo is None
                or len(self.snapshot_identity) != 32
                or self.template_version != SUPPORTED_TEMPLATE
            ):
                raise ValueError
            stored: Any = json.loads(self.snapshot_json)
            snapshot = parse_report_version_snapshot(stored)
            if (
                snapshot.report_id != self.report_id
                or snapshot.schema_version != self.snapshot_schema_version
                or snapshot.template_version != self.template_version
                or report_snapshot_identity(snapshot) != self.snapshot_identity
            ):
                raise ValueError
            return snapshot
        except (ValueError, TypeError, UnicodeDecodeError, ValidationError):
            raise PdfRenderFailure("invalid_snapshot") from None
