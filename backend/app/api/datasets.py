"""Authorized reads of confirmed datasets, canonical rows, and KPI results."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dataset_schemas import CanonicalRowsEnvelope, DatasetEnvelope, MetricsEnvelope
from app.api.dependencies import AuthenticatedPrincipal, get_authenticated_principal
from app.api.errors import APIError
from app.api.report_schemas import ErrorEnvelope
from app.domain.assets import ResourceNotFound
from app.domain.dataset_reads import DatasetReadServices

router = APIRouter(prefix="/api/v1/reports/{report_id}/datasets", tags=["datasets"])
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (401, 404, 422)
}


def services(request: Request) -> DatasetReadServices:
    return cast(DatasetReadServices, request.app.state.dataset_read_services)


def not_found() -> APIError:
    return APIError(404, "resource_not_found", "The requested resource was not found.")


@router.get("/current", response_model=DatasetEnvelope, responses=errors)
async def current_dataset(
    report_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[DatasetReadServices, Depends(services)],
) -> DatasetEnvelope:
    try:
        return DatasetEnvelope(data=await service.detail(principal.id, report_id))
    except ResourceNotFound:
        raise not_found() from None


@router.get("/{dataset_id}", response_model=DatasetEnvelope, responses=errors)
async def dataset_detail(
    report_id: UUID,
    dataset_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[DatasetReadServices, Depends(services)],
) -> DatasetEnvelope:
    try:
        return DatasetEnvelope(data=await service.detail(principal.id, report_id, dataset_id))
    except ResourceNotFound:
        raise not_found() from None


@router.get("/{dataset_id}/rows", response_model=CanonicalRowsEnvelope, responses=errors)
async def dataset_rows(
    report_id: UUID,
    dataset_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[DatasetReadServices, Depends(services)],
    offset: int = 0,
    limit: int = 50,
) -> CanonicalRowsEnvelope:
    try:
        await service.detail(principal.id, report_id, dataset_id)
        if offset < 0 or limit < 1 or limit > 100:
            raise APIError(422, "invalid_pagination", "Pagination is invalid.")
        rows, next_offset, total = await service.rows(
            principal.id, report_id, dataset_id, offset, limit
        )
    except ResourceNotFound:
        raise not_found() from None
    return CanonicalRowsEnvelope(data=rows, next_offset=next_offset, total_records=total)


@router.get("/{dataset_id}/metrics", response_model=MetricsEnvelope, responses=errors)
async def dataset_metrics(
    report_id: UUID,
    dataset_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[DatasetReadServices, Depends(services)],
    scope: str | None = None,
    campaign_name: str | None = None,
    currency: str | None = None,
) -> MetricsEnvelope:
    try:
        # Resolve the owner boundary before checking user filters.
        await service.detail(principal.id, report_id, dataset_id)
        if scope not in (None, "report", "campaign") or (campaign_name and scope != "campaign"):
            raise APIError(422, "invalid_metric_filter", "The metric filter is invalid.")
        if currency is not None and (
            len(currency) != 3 or not currency.isalpha() or not currency.isupper()
        ):
            raise APIError(422, "invalid_metric_filter", "The currency filter is invalid.")
        details, result_set_id = await service.metrics(
            principal.id, report_id, dataset_id, scope, campaign_name, currency
        )
    except ResourceNotFound:
        raise not_found() from None
    return MetricsEnvelope(data=details, result_set_id=result_set_id)
