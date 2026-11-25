## 1. Worker Configuration

- [x] 1.1 Add a pinned Celery dependency and lock it; verify `cd backend && uv sync --locked` succeeds.
- [x] 1.2 Add validated broker, publish timeout, task time limit, and stale-running timeout settings with safe example values; verify `cd backend && python -m pytest tests/test_config.py` passes.
- [x] 1.3 Configure an analysis-specific Celery application and documented worker startup command using the existing Redis service; verify the worker imports and registers the task without connecting during module import.

## 2. Durable Analysis Lifecycle

- [x] 2.1 Extend the PostgreSQL claim to compare the expected attempt ordinal and add bounded queued/stale-running selectors or transitions needed for recovery; verify concurrent and delayed-message cases in `tests/integration/db/test_analysis_jobs.py`.
- [x] 2.2 Implement the owner-scoped analysis-job domain service for current-input identity, transactional creation, retry, and persisted list/detail reads; verify isolated PostgreSQL tests cover stale input, uniqueness, idempotency, and owner isolation.
- [x] 2.3 Implement post-commit publish plus bounded queued-row reconciliation, leaving committed jobs queued on broker failure; verify deterministic tests cover repeated dispatch and recovery without extra attempts.
- [x] 2.4 Implement the worker task using opaque IDs, transactional claim, validated-result completion, sanitized failure, and the explicit unavailable-executor outcome; verify `tests/unit/jobs/test_analysis_worker.py` covers success, failure, redelivery, and stale completion with a deterministic runner.
- [x] 2.5 Add stale-running detection after the configured timeout and prevent late completion from changing its terminal state; verify PostgreSQL tests cover a worker interruption and late result.

## 3. API and Contract

- [x] 3.1 Add Pydantic analysis-job request/response schemas and thin `/api/v1` create, list, detail, and retry routes; verify `tests/contract/api/test_analysis_jobs.py` covers HTTP `202` IDs, all four states, timestamps, safe errors, pagination, and owner-safe `404`.
- [x] 3.2 Extend contract tests for equivalent replay, key conflict, retry eligibility, old attempt ordinals, queued broker failure, and forbidden data in responses/logs; verify `cd backend && python -m pytest tests/contract/api/test_analysis_jobs.py` passes.
- [x] 3.3 Update generated OpenAPI expectations and existing API error-contract tests for analysis-job routes; verify runtime responses validate against generated schemas and established error envelopes.

## 4. Verification and Handoff

- [x] 4.1 Document worker/reconciler commands, required environment variables, and operational recovery in backend or project documentation; verify commands and names agree with the configured entry points and example environment file.
- [x] 4.2 Run `cd backend && python -m pytest tests/unit/jobs/test_analysis_worker.py tests/contract/api/test_analysis_jobs.py tests/integration/db/test_analysis_jobs.py` against the required isolated PostgreSQL setup and record the result.
- [x] 4.3 Run `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and `cd backend && python -m pytest tests`; record any unavailable gates and verify no unrelated files changed.
