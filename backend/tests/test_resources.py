from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.resources import ResourceClients
from app.main import create_app


class FakeClients:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


def test_application_construction_does_not_create_clients(settings: Settings) -> None:
    factory_calls = 0

    def factory(_: Settings) -> ResourceClients:
        nonlocal factory_calls
        factory_calls += 1
        return cast(ResourceClients, FakeClients())

    create_app(settings, client_factory=factory)

    assert factory_calls == 0


def test_lifespan_creates_and_closes_clients_once(settings: Settings) -> None:
    clients = FakeClients()
    factory_calls = 0

    def factory(_: Settings) -> ResourceClients:
        nonlocal factory_calls
        factory_calls += 1
        return cast(ResourceClients, clients)

    app = create_app(settings, client_factory=factory)
    with TestClient(app):
        assert factory_calls == 1
        assert clients.close_calls == 0

    assert factory_calls == 1
    assert clients.close_calls == 1


@pytest.mark.asyncio
async def test_fake_clients_close_is_deterministic() -> None:
    clients = FakeClients()
    await clients.close()
    assert clients.close_calls == 1
