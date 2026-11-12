from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.health import probe_object_storage, probe_postgresql, probe_redis
from app.core.resources import ObjectStorageClient


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class FakeConnectionContext(AbstractAsyncContextManager[FakeConnection]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeConnectionContext:
        return FakeConnectionContext(self.connection)


class FakeRedis:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0

    async def ping(self) -> bool:
        self.calls += 1
        return self.result


class FakeObjectStorage:
    def __init__(self) -> None:
        self.buckets: list[str] = []

    def head_bucket(self, *, Bucket: str) -> object:
        self.buckets.append(Bucket)
        return {}

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_postgresql_probe_executes_only_select_one() -> None:
    engine = FakeEngine()

    await probe_postgresql(cast(AsyncEngine, engine))

    assert engine.connection.statements == ["SELECT 1"]


@pytest.mark.asyncio
async def test_redis_probe_executes_only_ping() -> None:
    client = FakeRedis()

    await probe_redis(cast(Redis, client))

    assert client.calls == 1


@pytest.mark.asyncio
async def test_redis_probe_rejects_unacknowledged_ping() -> None:
    with pytest.raises(RuntimeError, match="not acknowledged"):
        await probe_redis(cast(Redis, FakeRedis(result=False)))


@pytest.mark.asyncio
async def test_object_storage_probe_reads_bucket_metadata_only() -> None:
    client = FakeObjectStorage()

    await probe_object_storage(cast(ObjectStorageClient, client), "private-test-bucket")

    assert client.buckets == ["private-test-bucket"]


@pytest.mark.parametrize("failure", [PermissionError("denied"), ConnectionError("offline")])
@pytest.mark.asyncio
async def test_object_storage_probe_propagates_provider_failures(failure: Exception) -> None:
    class FailingObjectStorage(FakeObjectStorage):
        def head_bucket(self, *, Bucket: str) -> Any:
            raise failure

    with pytest.raises(type(failure)):
        await probe_object_storage(
            cast(ObjectStorageClient, FailingObjectStorage()),
            "private-test-bucket",
        )
