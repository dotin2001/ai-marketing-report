"""Deterministic in-memory implementation of the storage contract."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import anyio

from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import PreparedContent
from app.storage.types import ObjectIdentity, ObjectMetadata, ProviderObject


@dataclass(frozen=True, slots=True)
class _FakeEntry:
    content: bytes
    metadata: ObjectMetadata


class FakeObjectStorage:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], _FakeEntry] = {}
        self.calls: list[str] = []
        self.failures: dict[str, StorageErrorCode] = {}

    def _fail(self, operation: str) -> None:
        code = self.failures.get(operation)
        if code is not None:
            raise StorageError(code)

    async def put_if_absent(self, prepared: PreparedContent) -> bool:
        self.calls.append("put_if_absent")
        self._fail("put_if_absent")
        key = (prepared.metadata.identity.bucket, prepared.metadata.identity.key)
        if key in self._objects:
            return False

        def read() -> bytes:
            prepared.file.seek(0)
            return prepared.file.read()

        content = await anyio.to_thread.run_sync(read)
        self._objects[key] = _FakeEntry(content=content, metadata=prepared.metadata)
        return True

    async def head(self, identity: ObjectIdentity) -> ObjectMetadata | None:
        self.calls.append("head")
        self._fail("head")
        entry = self._objects.get((identity.bucket, identity.key))
        return None if entry is None else entry.metadata

    async def get(self, identity: ObjectIdentity) -> ProviderObject:
        self.calls.append("get")
        self._fail("get")
        entry = self._objects.get((identity.bucket, identity.key))
        if entry is None:
            raise StorageError(StorageErrorCode.UNAVAILABLE)
        return ProviderObject(metadata=entry.metadata, body=BytesIO(entry.content))

    async def delete_exact(
        self,
        expected: ObjectMetadata,
        *,
        created_by_invocation: bool,
    ) -> bool:
        self.calls.append("delete_exact")
        self._fail("delete_exact")
        if not created_by_invocation:
            return False
        key = (expected.identity.bucket, expected.identity.key)
        entry = self._objects.get(key)
        if entry is None or entry.metadata != expected:
            return False
        del self._objects[key]
        return True

    def corrupt(self, identity: ObjectIdentity, content: bytes) -> None:
        key = (identity.bucket, identity.key)
        entry = self._objects[key]
        self._objects[key] = _FakeEntry(content=content, metadata=entry.metadata)

    def replace_metadata(self, metadata: ObjectMetadata, content: bytes) -> None:
        self._objects[(metadata.identity.bucket, metadata.identity.key)] = _FakeEntry(
            content=content,
            metadata=metadata,
        )
