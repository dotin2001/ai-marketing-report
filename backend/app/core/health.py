"""Read-only, independently fakeable dependency probes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.resources import ObjectStorageClient, ResourceClients

logger = logging.getLogger(__name__)

DependencyName = str
Probe = Callable[[], Awaitable[None]]


class ProbeProvider(Protocol):
    def probes(self) -> Mapping[DependencyName, Probe]: ...


async def probe_postgresql(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def probe_redis(client: Redis) -> None:
    if not await client.ping():
        raise RuntimeError("redis ping was not acknowledged")


async def probe_object_storage(client: ObjectStorageClient, bucket: str) -> None:
    await asyncio.to_thread(client.head_bucket, Bucket=bucket)


@dataclass(frozen=True, slots=True)
class ResourceProbeProvider:
    clients: ResourceClients
    bucket: str

    def probes(self) -> Mapping[DependencyName, Probe]:
        return {
            "postgresql": lambda: probe_postgresql(self.clients.postgresql),
            "redis": lambda: probe_redis(self.clients.redis),
            "object_storage": lambda: probe_object_storage(
                self.clients.object_storage,
                self.bucket,
            ),
        }


async def _run_one(name: DependencyName, probe: Probe, timeout_seconds: float) -> tuple[str, str]:
    try:
        await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("dependency_unavailable dependency=%s category=timeout", name)
        return name, "unavailable"
    # Provider exception details are deliberately suppressed at this trust boundary.
    except Exception:
        logger.warning("dependency_unavailable dependency=%s category=check_failed", name)
        return name, "unavailable"
    return name, "ready"


async def check_readiness(
    provider: ProbeProvider,
    timeout_seconds: float,
) -> dict[DependencyName, str]:
    probes = provider.probes()
    results = await asyncio.gather(
        *(_run_one(name, probe, timeout_seconds) for name, probe in probes.items())
    )
    return dict(results)
