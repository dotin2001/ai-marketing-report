"""FastAPI application factory for the foundation service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings
from app.core.health import ResourceProbeProvider
from app.core.resources import ResourceClients, create_resource_clients

ClientFactory = Callable[[Settings], ResourceClients]


def create_app(
    settings: Settings | None = None,
    client_factory: ClientFactory = create_resource_clients,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clients = client_factory(resolved_settings)
        app.state.resource_clients = clients
        app.state.probe_provider = ResourceProbeProvider(
            clients=clients,
            bucket=resolved_settings.s3_bucket,
        )
        app.state.health_check_timeout_seconds = resolved_settings.health_check_timeout_seconds
        try:
            yield
        finally:
            await clients.close()

    application = FastAPI(
        title="AI Marketing Report Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application
