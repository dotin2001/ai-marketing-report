"""One bounded PostgreSQL recovery pass for queued and stale running analysis jobs."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.session import create_session_factory
from app.domain.analysis_jobs import AnalysisJobServices
from app.domain.pdf_exports import PdfExportServices
from app.jobs.analysis_worker import fail_stale_running
from app.jobs.pdf_worker import fail_stale_running_pdf


async def main() -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        sessions = create_session_factory(engine)
        service = AnalysisJobServices(
            sessions, settings.report_cursor_signing_key.get_secret_value()
        )
        await fail_stale_running(sessions, settings.analysis_stale_running_seconds)
        await service.reconcile()
        pdf_service = PdfExportServices(
            sessions, settings.report_cursor_signing_key.get_secret_value()
        )
        await fail_stale_running_pdf(sessions, settings.pdf_stale_running_seconds)
        await pdf_service.reconcile()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
