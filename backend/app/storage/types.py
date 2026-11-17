"""Provider-neutral immutable object identities and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Literal
from uuid import UUID

AppEnvironment = Literal["local", "test", "development", "staging", "production"]


class StoragePurpose(StrEnum):
    SOURCE_CSV = "source_csv"
    GENERATED_PDF = "generated_pdf"


@dataclass(frozen=True, slots=True)
class ObjectIdentity:
    environment: AppEnvironment
    bucket: str
    key: str
    purpose: StoragePurpose


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    identity: ObjectIdentity
    owner_id: UUID
    report_id: UUID
    logical_id: UUID
    content_type: str
    byte_size: int
    checksum_sha256: str

    def provider_metadata(self) -> dict[str, str]:
        return {
            "schema-version": "1",
            "environment": self.identity.environment,
            "owner-id": str(self.owner_id),
            "report-id": str(self.report_id),
            "purpose": self.identity.purpose.value,
            "logical-id": str(self.logical_id),
            "content-type": self.content_type,
            "byte-size": str(self.byte_size),
            "sha256": self.checksum_sha256,
        }


@dataclass(slots=True)
class ProviderObject:
    metadata: ObjectMetadata
    body: BinaryIO


@dataclass(frozen=True, slots=True)
class StoreResult:
    metadata: ObjectMetadata
    created: bool
