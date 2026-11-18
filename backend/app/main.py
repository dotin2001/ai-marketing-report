"""FastAPI application factory for the foundation service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.errors import APIError, api_error_handler, request_validation_handler
from app.api.health import router as health_router
from app.api.pdf_downloads import router as pdf_download_router
from app.api.reports import router as report_router
from app.core.config import Settings
from app.core.health import ResourceProbeProvider
from app.core.resources import ResourceClients, create_resource_clients
from app.db.session import create_session_factory
from app.domain.assets import AssetServices
from app.domain.reports import ReportServices
from app.storage.coordinator import StorageCoordinator
from app.storage.keys import TrustedKeyBuilder
from app.storage.s3 import S3ObjectStorage

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
        app.state.object_storage = S3ObjectStorage(clients.object_storage)
        if hasattr(clients, "postgresql"):
            app.state.report_services = ReportServices(
                sessions=create_session_factory(clients.postgresql),
                cursor_secret=resolved_settings.report_cursor_signing_key.get_secret_value(),
            )
            app.state.asset_services = AssetServices(
                sessions=create_session_factory(clients.postgresql),
                coordinator=StorageCoordinator(app.state.object_storage),
                keys=TrustedKeyBuilder(
                    environment=resolved_settings.app_env,
                    bucket=resolved_settings.s3_bucket,
                ),
                source_csv_max_bytes=resolved_settings.source_csv_max_bytes,
                generated_pdf_max_bytes=resolved_settings.generated_pdf_max_bytes,
            )
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
    application.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type]
    application.include_router(health_router)
    application.include_router(pdf_download_router)
    application.include_router(report_router)
    return application
