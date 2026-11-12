"""Lifespan-owned clients used by the readiness contract."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


class ObjectStorageClient(Protocol):
    def head_bucket(self, *, Bucket: str) -> object: ...

    def close(self) -> object: ...


@dataclass(slots=True)
class ResourceClients:
    postgresql: AsyncEngine
    redis: Redis
    object_storage: ObjectStorageClient

    async def close(self) -> None:
        await self.postgresql.dispose()
        await self.redis.aclose()
        result = self.object_storage.close()
        if inspect.isawaitable(result):
            await result


def create_resource_clients(settings: Settings) -> ResourceClients:
    """Construct clients without opening sockets or issuing probes."""

    postgresql = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=False,
    )
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
    )
    object_storage: Any = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        use_ssl=settings.s3_use_ssl,
    )
    return ResourceClients(
        postgresql=postgresql,
        redis=redis,
        object_storage=object_storage,
    )
