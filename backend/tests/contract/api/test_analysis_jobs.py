"""Analysis-job HTTP contract with a deterministic persisted-state stand-in."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.analysis_job_schemas import (
    AnalysisAttemptDetail,
    AnalysisJobDetail,
    AnalysisJobEnvelope,
    AnalysisJobSummary,
    AnalysisResultItemPublic,
    AnalysisResultPublic,
    CreateAnalysisJobRequest,
    JobFailure,
    RetryAnalysisJobRequest,
)
from app.api.analysis_jobs import services
from app.api.dependencies import AuthenticatedPrincipal, get_authenticated_principal
from app.api.report_schemas import ErrorEnvelope, Page
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict
from app.domain.assets import ResourceNotFound
from app.domain.reports import InvalidCursor
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeJobs:
    def __init__(self, owner: UUID, report: UUID) -> None:
        self.owner, self.report = owner, report
        self.job_id = uuid4()
        self.result_id = uuid4()
        self.state = "queued"
        self.ordinal = 1
        self.created = datetime.now(UTC)
        self.keys: dict[str, CreateAnalysisJobRequest] = {}
        self.retry_keys: set[str] = set()

    def _owner(self, owner: UUID, report: UUID) -> None:
        if (owner, report) != (self.owner, self.report):
            raise ResourceNotFound

    def _detail(self) -> AnalysisJobDetail:
        failure = (
            JobFailure(
                code="provider_unavailable",
                message="Analysis could not be completed.",
                retryable=True,
            )
            if self.state == "failed"
            else None
        )
        result = (
            AnalysisResultPublic(
                id=self.result_id,
                model_identifier="provider-actual-model",
                prompt_version="analysis-prompt-v1",
                request_provenance=(
                    "response=resp_safe;prompt=analysis-prompt-v1;"
                    "context=analysis-context-v1;digest=sha256:" + "a" * 64
                ),
                created_at=self.created,
                summary=[
                    AnalysisResultItemPublic(
                        section="summary",
                        ordinal=1,
                        classification="observation",
                        content="Performance was stable.",
                    )
                ],
                findings=[],
                anomalies=[],
                recommendations=[],
                data_gaps=[],
            )
            if self.state == "succeeded"
            else None
        )
        return AnalysisJobDetail(
            id=self.job_id,
            report_id=self.report,
            state=self.state,
            attempt_count=self.ordinal,
            created_at=self.created,
            updated_at=self.created,
            failure=failure,
            dataset_id=uuid4(),
            metric_result_set_id=uuid4(),
            draft_id=uuid4(),
            draft_revision=1,
            result_id=self.result_id if self.state == "succeeded" else None,
            result=result,
            attempts=[
                AnalysisAttemptDetail(
                    ordinal=self.ordinal,
                    state=self.state,
                    queued_at=self.created,
                    started_at=self.created if self.state != "queued" else None,
                    finished_at=self.created if self.state in {"succeeded", "failed"} else None,
                    failure=failure,
                )
            ],
        )

    async def create(
        self, owner: UUID, report: UUID, command: CreateAnalysisJobRequest, key: str
    ) -> tuple[AnalysisJobDetail, bool]:
        self._owner(owner, report)
        if key in self.keys and self.keys[key] != command:
            raise IdempotencyConflict
        if command.expected_revision != 1:
            raise ConcurrencyConflict
        replayed = key in self.keys
        self.keys[key] = command
        return self._detail(), replayed

    async def detail(self, owner: UUID, report: UUID, job_id: UUID) -> AnalysisJobDetail:
        self._owner(owner, report)
        if job_id != self.job_id:
            raise ResourceNotFound
        return self._detail()

    async def list(
        self, owner: UUID, report: UUID, limit: int, cursor: str | None
    ) -> tuple[list[AnalysisJobSummary], Page]:
        self._owner(owner, report)
        if cursor:
            raise InvalidCursor
        return [
            AnalysisJobSummary.model_validate(
                self._detail().model_dump(
                    exclude={
                        "dataset_id",
                        "metric_result_set_id",
                        "draft_id",
                        "draft_revision",
                        "attempts",
                        "result_id",
                        "result",
                    }
                )
            )
        ][:limit], Page(
            limit=limit,
            has_more=False,
            next_cursor=None,
        )

    async def retry(
        self, owner: UUID, report: UUID, job_id: UUID, command: RetryAnalysisJobRequest, key: str
    ) -> tuple[AnalysisJobDetail, bool]:
        await self.detail(owner, report, job_id)
        if key in self.retry_keys:
            return self._detail(), True
        if self.state != "failed" or command.expected_attempt_count != self.ordinal:
            raise ConcurrencyConflict
        self.retry_keys.add(key)
        self.ordinal += 1
        self.state = "queued"
        return self._detail(), False


def test_analysis_job_http_states_replay_retry_pagination_and_redaction(settings: Settings) -> None:
    owner, report = uuid4(), uuid4()
    fake = FakeJobs(owner, report)
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(id=owner)
    app.dependency_overrides[services] = lambda: fake
    base = f"/api/v1/reports/{report}/analysis-jobs"
    with TestClient(app) as client:
        created = client.post(
            base, json={"expected_revision": 1}, headers={"Idempotency-Key": "first"}
        )
        assert created.status_code == 202
        AnalysisJobEnvelope.model_validate(created.json())
        assert created.json()["data"]["id"] == str(fake.job_id)
        assert created.json()["data"]["state"] == "queued"
        assert created.json()["data"]["attempts"][0]["queued_at"]
        replay = client.post(
            base, json={"expected_revision": 1}, headers={"Idempotency-Key": "first"}
        )
        assert replay.headers["Idempotency-Replayed"] == "true"
        conflict = client.post(
            base, json={"expected_revision": 2}, headers={"Idempotency-Key": "first"}
        )
        assert (conflict.status_code, conflict.json()["error"]["code"]) == (
            409,
            "idempotency_conflict",
        )
        ErrorEnvelope.model_validate(conflict.json())
        stale = client.post(
            base, json={"expected_revision": 2}, headers={"Idempotency-Key": "second"}
        )
        assert stale.status_code == 409
        assert client.post(base, json={"expected_revision": 1}).status_code == 422
        assert (
            client.post(
                base,
                json={"expected_revision": 1, "provider_payload": "private"},
                headers={"Idempotency-Key": "bad"},
            ).status_code
            == 422
        )
        for state in ("running", "succeeded", "failed"):
            fake.state = state
            response = client.get(f"{base}/{fake.job_id}")
            assert response.status_code == 200 and response.json()["data"]["state"] == state
            if state == "failed":
                assert response.json()["data"]["failure"]["code"] == "provider_unavailable"
            if state == "succeeded":
                result = response.json()["data"]["result"]
                assert result["model_identifier"] == "provider-actual-model"
                assert result["prompt_version"] == "analysis-prompt-v1"
                assert result["summary"][0]["content"] == "Performance was stable."
                assert "resp_safe" in result["request_provenance"]
                assert "numeric_source_identity" not in result
        page = client.get(base, params={"limit": 1})
        assert page.status_code == 200 and page.json()["page"]["limit"] == 1
        assert (
            client.get(base, params={"cursor": "bad"}).json()["error"]["code"] == "invalid_cursor"
        )
        assert client.get(f"{base}/{uuid4()}").status_code == 404
        foreign = client.get(f"/api/v1/reports/{uuid4()}/analysis-jobs/{fake.job_id}")
        missing = client.get(f"{base}/{uuid4()}")
        assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]
        app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
            id=uuid4()
        )
        foreign_owner = client.get(f"{base}/{fake.job_id}")
        foreign_retry = client.post(
            f"{base}/{fake.job_id}/retry",
            json={"expected_attempt_count": 1},
            headers={"Idempotency-Key": "foreign"},
        )
        assert foreign_owner.status_code == foreign_retry.status_code == 404
        app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
            id=owner
        )
        rejected = client.post(
            f"{base}/{fake.job_id}/retry",
            json={"expected_attempt_count": 2},
            headers={"Idempotency-Key": "retry-bad"},
        )
        assert rejected.status_code == 409
        retried = client.post(
            f"{base}/{fake.job_id}/retry",
            json={"expected_attempt_count": 1},
            headers={"Idempotency-Key": "retry"},
        )
        assert retried.status_code == 202 and retried.json()["data"]["attempt_count"] == 2
        assert (
            client.post(
                f"{base}/{fake.job_id}/retry",
                json={"expected_attempt_count": 1},
                headers={"Idempotency-Key": "retry"},
            ).headers["Idempotency-Replayed"]
            == "true"
        )
        assert (
            client.post(
                f"{base}/{fake.job_id}/retry",
                json={"expected_attempt_count": 2},
                headers={"Idempotency-Key": "retry-again"},
            ).status_code
            == 409
        )
        for response in (
            created,
            replay,
            stale,
            foreign,
            foreign_owner,
            foreign_retry,
            rejected,
            retried,
        ):
            for forbidden in (
                "private",
                "provider_payload",
                "credential",
                "stack trace",
                "object_key",
                "OPENAI_API_KEY",
                "<untrusted_analysis_data>",
                "raw source",
            ):
                assert forbidden not in response.text
        paths = client.get("/openapi.json").json()["paths"]
        collection = paths["/api/v1/reports/{report_id}/analysis-jobs"]
        detail = paths["/api/v1/reports/{report_id}/analysis-jobs/{job_id}"]
        retry = paths["/api/v1/reports/{report_id}/analysis-jobs/{job_id}/retry"]
        assert "AnalysisJobEnvelope" in str(collection["post"]["responses"]["202"])
        assert "AnalysisJobListEnvelope" in str(collection["get"]["responses"]["200"])
        assert "AnalysisJobEnvelope" in str(detail["get"]["responses"]["200"])
        assert "AnalysisJobEnvelope" in str(retry["post"]["responses"]["202"])
        assert "ErrorEnvelope" in str(retry["post"]["responses"]["409"])
