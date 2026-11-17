"""Narrow async object-storage port; intentionally no list or arbitrary-key API."""

from __future__ import annotations

from typing import Protocol

from app.storage.files import PreparedContent
from app.storage.types import ObjectIdentity, ObjectMetadata, ProviderObject


class ObjectStorage(Protocol):
    async def put_if_absent(self, prepared: PreparedContent) -> bool: ...

    async def head(self, identity: ObjectIdentity) -> ObjectMetadata | None: ...

    async def get(self, identity: ObjectIdentity) -> ProviderObject: ...

    async def delete_exact(
        self,
        expected: ObjectMetadata,
        *,
        created_by_invocation: bool,
    ) -> bool: ...
