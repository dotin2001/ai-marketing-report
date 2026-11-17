"""Bounded temporary-file preparation and complete retrieval verification."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import UUID

import anyio

from app.storage.errors import ContentRejected, StorageError, StorageErrorCode
from app.storage.types import ObjectIdentity, ObjectMetadata, ProviderObject, StoragePurpose

DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_SPOOL_MAX_BYTES = 1024 * 1024


@dataclass(slots=True)
class PreparedContent:
    metadata: ObjectMetadata
    safe_filename: str
    file: SpooledTemporaryFile[bytes]

    @property
    def rolled_to_disk(self) -> bool:
        return bool(getattr(self.file, "_rolled", False))

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> PreparedContent:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(slots=True)
class VerifiedContent:
    metadata: ObjectMetadata
    safe_filename: str
    file: SpooledTemporaryFile[bytes]

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> VerifiedContent:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _copy_bounded(
    source: BinaryIO,
    destination: SpooledTemporaryFile[bytes],
    *,
    max_bytes: int,
    chunk_size: int,
) -> tuple[int, str]:
    digest = sha256()
    byte_size = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ContentRejected("content stream must produce bytes")
        byte_size += len(chunk)
        if byte_size > max_bytes:
            raise ContentRejected("content exceeds configured byte limit")
        digest.update(chunk)
        destination.write(chunk)
    destination.seek(0)
    return byte_size, digest.hexdigest()


def _validate_purpose(identity: ObjectIdentity, content_type: str, byte_size: int) -> None:
    expected = {
        StoragePurpose.SOURCE_CSV: "text/csv",
        StoragePurpose.GENERATED_PDF: "application/pdf",
    }[identity.purpose]
    if content_type != expected:
        raise ContentRejected("content type does not match storage purpose")
    if byte_size == 0:
        raise ContentRejected("stored content must not be empty")


async def prepare_content(
    source: BinaryIO,
    *,
    identity: ObjectIdentity,
    owner_id: UUID,
    report_id: UUID,
    logical_id: UUID,
    safe_filename: str,
    content_type: str,
    max_bytes: int,
    spool_max_bytes: int = DEFAULT_SPOOL_MAX_BYTES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> PreparedContent:
    if max_bytes <= 0 or spool_max_bytes <= 0 or chunk_size <= 0:
        raise ValueError("storage preparation bounds must be positive")
    temporary = SpooledTemporaryFile(max_size=spool_max_bytes, mode="w+b")
    try:
        byte_size, checksum = await anyio.to_thread.run_sync(
            lambda: _copy_bounded(
                source,
                temporary,
                max_bytes=max_bytes,
                chunk_size=chunk_size,
            )
        )
        _validate_purpose(identity, content_type, byte_size)
        return PreparedContent(
            metadata=ObjectMetadata(
                identity=identity,
                owner_id=owner_id,
                report_id=report_id,
                logical_id=logical_id,
                content_type=content_type,
                byte_size=byte_size,
                checksum_sha256=checksum,
            ),
            safe_filename=safe_filename,
            file=temporary,
        )
    except BaseException:
        temporary.close()
        raise


def metadata_matches(actual: ObjectMetadata, expected: ObjectMetadata) -> bool:
    return actual == expected


async def verify_download(
    provider_object: ProviderObject,
    *,
    expected: ObjectMetadata,
    safe_filename: str,
    max_bytes: int,
    spool_max_bytes: int = DEFAULT_SPOOL_MAX_BYTES,
) -> VerifiedContent:
    temporary = SpooledTemporaryFile(max_size=spool_max_bytes, mode="w+b")
    try:
        if not metadata_matches(provider_object.metadata, expected):
            raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
        byte_size, checksum = await anyio.to_thread.run_sync(
            lambda: _copy_bounded(
                provider_object.body,
                temporary,
                max_bytes=max_bytes,
                chunk_size=DEFAULT_CHUNK_SIZE,
            )
        )
        if byte_size != expected.byte_size or checksum != expected.checksum_sha256:
            raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
        return VerifiedContent(
            metadata=expected,
            safe_filename=safe_filename,
            file=temporary,
        )
    except ContentRejected as exc:
        temporary.close()
        raise StorageError(StorageErrorCode.INTEGRITY_FAILED) from exc
    except BaseException:
        temporary.close()
        raise
    finally:
        await anyio.to_thread.run_sync(provider_object.body.close)
