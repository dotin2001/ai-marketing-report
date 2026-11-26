"""Owner-scoped analysis-job submission, polling, and retry."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.api.analysis_job_schemas import (
    AnalysisJobEnvelope,
    AnalysisJobListEnvelope,
    CreateAnalysisJobRequest,
    RetryAnalysisJobRequest,
)
from app.api.dependencies import AuthenticatedPrincipal, get_authenticated_principal
from app.api.errors import APIError
from app.api.report_schemas import ErrorEnvelope
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict, JobNotRetryable
from app.domain.analysis_jobs import AnalysisJobServices
from app.domain.assets import ResourceNotFound
from app.domain.reports import InvalidCursor

router = APIRouter(prefix="/api/v1/reports/{report_id}/analysis-jobs", tags=["analysis-jobs"])
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 401, 404, 409, 422)
}


def services(request: Request) -> AnalysisJobServices:
    return cast(AnalysisJobServices, request.app.state.analysis_job_services)


def not_found() -> APIError:
    return APIError(404, "resource_not_found", "The requested resource was not found.")


def conflict() -> APIError:
    return APIError(409, "revision_conflict", "The analysis input or job state has changed.")


def key_conflict() -> APIError:
    return APIError(
        409, "idempotency_conflict", "The idempotency key was used for another command."
    )


def not_retryable() -> APIError:
    return APIError(409, "job_not_retryable", "The analysis job cannot be retried.")


@router.post("", status_code=202, response_model=AnalysisJobEnvelope, responses=errors)
async def create_analysis_job(
    report_id: UUID,
    command: CreateAnalysisJobRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[AnalysisJobServices, Depends(services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> AnalysisJobEnvelope:
    try:
        detail, replayed = await service.create(principal.id, report_id, command, idempotency_key)
    except ResourceNotFound:
        raise not_found() from None
    except ConcurrencyConflict:
        raise conflict() from None
    except IdempotencyConflict:
        raise key_conflict() from None
    except ValueError:
        raise APIError(400, "invalid_request", "The idempotency key is invalid.") from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return AnalysisJobEnvelope(data=detail)


@router.get("", response_model=AnalysisJobListEnvelope, responses=errors)
async def list_analysis_jobs(
    report_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[AnalysisJobServices, Depends(services)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> AnalysisJobListEnvelope:
    try:
        jobs, page = await service.list(principal.id, report_id, limit, cursor)
    except ResourceNotFound:
        raise not_found() from None
    except InvalidCursor:
        raise APIError(400, "invalid_cursor", "The cursor is invalid.") from None
    return AnalysisJobListEnvelope(data=jobs, page=page)


@router.get("/{job_id}", response_model=AnalysisJobEnvelope, responses=errors)
async def get_analysis_job(
    report_id: UUID,
    job_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[AnalysisJobServices, Depends(services)],
) -> AnalysisJobEnvelope:
    try:
        return AnalysisJobEnvelope(data=await service.detail(principal.id, report_id, job_id))
    except ResourceNotFound:
        raise not_found() from None


@router.post(
    "/{job_id}/retry", status_code=202, response_model=AnalysisJobEnvelope, responses=errors
)
async def retry_analysis_job(
    report_id: UUID,
    job_id: UUID,
    command: RetryAnalysisJobRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[AnalysisJobServices, Depends(services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> AnalysisJobEnvelope:
    try:
        detail, replayed = await service.retry(
            principal.id,
            report_id,
            job_id,
            command,
            idempotency_key,
        )
    except ResourceNotFound:
        raise not_found() from None
    except ConcurrencyConflict:
        raise conflict() from None
    except JobNotRetryable:
        raise not_retryable() from None
    except IdempotencyConflict:
        raise key_conflict() from None
    except ValueError:
        raise APIError(400, "invalid_request", "The idempotency key is invalid.") from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return AnalysisJobEnvelope(data=detail)
