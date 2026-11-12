from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.health import Probe
from app.core.resources import ResourceClients
from app.main import create_app


class FakeClients:
    async def close(self) -> None:
        return None


class StaticProbeProvider:
    def __init__(self, probes: Mapping[str, Probe]) -> None:
        self._probes = probes

    def probes(self) -> Mapping[str, Probe]:
        return self._probes


def passing_probe(delay: float = 0) -> Callable[[], Awaitable[None]]:
    async def probe() -> None:
        if delay:
            await asyncio.sleep(delay)

    return probe


def failing_probe(message: str = "provider failed") -> Callable[[], Awaitable[None]]:
    async def probe() -> None:
        raise RuntimeError(message)

    return probe


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(
        settings,
        client_factory=lambda _: cast(ResourceClients, FakeClients()),
    )
    with TestClient(app) as test_client:
        yield test_client


def set_probes(client: TestClient, probes: Mapping[str, Probe], timeout: float = 0.1) -> None:
    app = cast(FastAPI, client.app)
    app.state.probe_provider = StaticProbeProvider(probes)
    app.state.health_check_timeout_seconds = timeout


def all_probes(probe: Probe | None = None) -> dict[str, Probe]:
    selected = probe or passing_probe()
    return {
        "postgresql": selected,
        "redis": selected,
        "object_storage": selected,
    }


def test_liveness_never_invokes_dependency_probes(client: TestClient) -> None:
    calls = 0

    async def explode() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("must not run")

    set_probes(client, all_probes(explode))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == 0


def test_readiness_reports_all_dependencies_ready(client: TestClient) -> None:
    set_probes(client, all_probes())

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {
            "postgresql": "ready",
            "redis": "ready",
            "object_storage": "ready",
        },
    }


@pytest.mark.parametrize("failed_name", ["postgresql", "redis", "object_storage"])
def test_readiness_reports_each_single_failure(client: TestClient, failed_name: str) -> None:
    probes = all_probes()
    probes[failed_name] = failing_probe()
    set_probes(client, probes)

    response = client.get("/health/ready")

    assert response.status_code == 503
    expected = {name: "ready" for name in probes}
    expected[failed_name] = "unavailable"
    assert response.json() == {"status": "not_ready", "dependencies": expected}


def test_readiness_reports_multiple_failures(client: TestClient) -> None:
    set_probes(
        client,
        {
            "postgresql": failing_probe(),
            "redis": passing_probe(),
            "object_storage": failing_probe(),
        },
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"] == {
        "postgresql": "unavailable",
        "redis": "ready",
        "object_storage": "unavailable",
    }


def test_readiness_timeouts_are_concurrent_and_bounded(client: TestClient) -> None:
    set_probes(client, all_probes(passing_probe(delay=0.2)), timeout=0.04)

    started = time.monotonic()
    response = client.get("/health/ready")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert set(response.json()["dependencies"].values()) == {"unavailable"}
    assert elapsed < 0.12


def test_successful_readiness_probes_run_concurrently(client: TestClient) -> None:
    active = 0
    maximum_active = 0

    async def observed_probe() -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.02)
        active -= 1

    set_probes(client, all_probes(observed_probe), timeout=0.2)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert maximum_active == 3


def test_health_responses_and_logs_redact_provider_details(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    forbidden = [
        "recognizable-password",
        "postgresql://user:recognizable-password@secret-host/db",
        "private-bucket-name",
        "owners/123/private-object.csv",
        "/Users/customer/private/source.csv",
        "driver connection refused at secret-host",
    ]
    set_probes(client, all_probes(failing_probe(" | ".join(forbidden))))

    with caplog.at_level(logging.WARNING):
        response = client.get("/health/ready")

    observed = f"{response.text}\n{caplog.text}"
    assert response.status_code == 503
    assert "dependency=postgresql" in caplog.text
    for secret in forbidden:
        assert secret not in observed
