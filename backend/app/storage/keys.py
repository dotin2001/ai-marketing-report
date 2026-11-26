"""Versioned object keys built only from trusted scope identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.storage.types import AppEnvironment, ObjectIdentity, StoragePurpose

_BUCKET = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class TrustedKeyBuilder:
    environment: AppEnvironment
    bucket: str

    def __post_init__(self) -> None:
        if not 3 <= len(self.bucket) <= 63 or not _BUCKET.fullmatch(self.bucket):
            raise ValueError("configured storage bucket is invalid")

    def source_csv(self, *, owner_id: UUID, report_id: UUID, source_id: UUID) -> ObjectIdentity:
        return ObjectIdentity(
            environment=self.environment,
            bucket=self.bucket,
            key=(
                f"v1/{self.environment}/owners/{owner_id}/reports/{report_id}/"
                f"sources/{source_id}/original.csv"
            ),
            purpose=StoragePurpose.SOURCE_CSV,
        )

    def generated_pdf(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
        attempt_ordinal: int = 1,
    ) -> ObjectIdentity:
        if attempt_ordinal < 1:
            raise ValueError("PDF attempt ordinal must be positive")
        return ObjectIdentity(
            environment=self.environment,
            bucket=self.bucket,
            key=(
                f"v1/{self.environment}/owners/{owner_id}/reports/{report_id}/"
                f"versions/{version_id}/pdf-exports/{export_id}/attempts/{attempt_ordinal}/report.pdf"
            ),
            purpose=StoragePurpose.GENERATED_PDF,
        )
