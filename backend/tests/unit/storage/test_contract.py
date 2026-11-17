from __future__ import annotations

from dataclasses import replace

import pytest

from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.fake import FakeObjectStorage
from tests.unit.storage.helpers import prepared_csv


@pytest.mark.asyncio
async def test_fake_contract_create_exact_retry_get_and_exact_delete() -> None:
    fake = FakeObjectStorage()
    coordinator = StorageCoordinator(fake)
    first = await prepared_csv()
    replay = await prepared_csv()
    try:
        created = await coordinator.create_or_verify(first)
        existing = await coordinator.create_or_verify(replay)
        assert created.created is True
        assert existing.created is False
        verified = await coordinator.retrieve_verified(
            expected=first.metadata,
            safe_filename=first.safe_filename,
            max_bytes=first.metadata.byte_size,
        )
        first.file.seek(0)
        assert verified.file.read() == first.file.read()
        verified.close()
        assert await coordinator.compensate(existing) is False
        assert await coordinator.compensate(created) is True
        assert await fake.head(first.metadata.identity) is None
    finally:
        first.close()
        replay.close()


@pytest.mark.asyncio
async def test_fake_contract_collision_integrity_and_each_stable_failure() -> None:
    fake = FakeObjectStorage()
    coordinator = StorageCoordinator(fake)
    prepared = await prepared_csv()
    try:
        different = replace(prepared.metadata, content_type="application/octet-stream")
        fake.replace_metadata(different, b"different")
        with pytest.raises(StorageError) as collision:
            await coordinator.create_or_verify(prepared)
        assert collision.value.code is StorageErrorCode.COLLISION

        fake.replace_metadata(prepared.metadata, b"tampered")
        with pytest.raises(StorageError) as integrity:
            await coordinator.create_or_verify(prepared)
        assert integrity.value.code is StorageErrorCode.INTEGRITY_FAILED

    finally:
        prepared.close()


@pytest.mark.parametrize("operation", ["put_if_absent", "head", "get", "delete_exact"])
@pytest.mark.parametrize("code", list(StorageErrorCode))
@pytest.mark.asyncio
async def test_fake_contract_exposes_each_stable_failure_for_every_operation(
    operation: str,
    code: StorageErrorCode,
) -> None:
    fake = FakeObjectStorage()
    prepared = await prepared_csv()
    fake.failures[operation] = code
    try:
        with pytest.raises(StorageError) as failure:
            if operation == "put_if_absent":
                await fake.put_if_absent(prepared)
            elif operation == "head":
                await fake.head(prepared.metadata.identity)
            elif operation == "get":
                await fake.get(prepared.metadata.identity)
            else:
                await fake.delete_exact(prepared.metadata, created_by_invocation=True)
        assert failure.value.code is code
        assert str(failure.value) == code.value
    finally:
        prepared.close()


@pytest.mark.asyncio
async def test_delete_never_removes_preexisting_or_mismatched_object() -> None:
    fake = FakeObjectStorage()
    prepared = await prepared_csv()
    try:
        await fake.put_if_absent(prepared)
        assert await fake.delete_exact(prepared.metadata, created_by_invocation=False) is False
        mismatch = replace(prepared.metadata, checksum_sha256="0" * 64)
        assert await fake.delete_exact(mismatch, created_by_invocation=True) is False
        assert await fake.head(prepared.metadata.identity) == prepared.metadata
    finally:
        prepared.close()
