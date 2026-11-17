"""Immutable create-or-verify and verified retrieval orchestration."""

from __future__ import annotations

from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import PreparedContent, VerifiedContent, metadata_matches, verify_download
from app.storage.protocol import ObjectStorage
from app.storage.types import ObjectMetadata, StoreResult


class StorageCoordinator:
    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    async def create_or_verify(self, prepared: PreparedContent) -> StoreResult:
        expected = prepared.metadata
        existing = await self._storage.head(expected.identity)
        created = False
        if existing is None:
            created = await self._storage.put_if_absent(prepared)
            existing = await self._storage.head(expected.identity)
        if existing is None:
            raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
        if not metadata_matches(existing, expected):
            raise StorageError(StorageErrorCode.COLLISION)
        retrieved = await self._storage.get(expected.identity)
        verified = await verify_download(
            retrieved,
            expected=expected,
            safe_filename=prepared.safe_filename,
            max_bytes=expected.byte_size,
        )
        verified.close()
        return StoreResult(metadata=expected, created=created)

    async def retrieve_verified(
        self,
        *,
        expected: ObjectMetadata,
        safe_filename: str,
        max_bytes: int,
    ) -> VerifiedContent:
        provider_object = await self._storage.get(expected.identity)
        return await verify_download(
            provider_object,
            expected=expected,
            safe_filename=safe_filename,
            max_bytes=max_bytes,
        )

    async def compensate(self, result: StoreResult) -> bool:
        return await self._storage.delete_exact(
            result.metadata,
            created_by_invocation=result.created,
        )
