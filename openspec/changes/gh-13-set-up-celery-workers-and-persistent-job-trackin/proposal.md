## Why

The database can record analysis-job attempts, but the application has no Celery worker or analysis-job API to deliver, observe, or retry them. Issue #13 establishes the durable execution boundary needed before AI analysis can run asynchronously.

## What Changes

- Configure a Celery application and worker against the existing Redis service, with PostgreSQL as the sole job-status authority.
- Add owner-authorized `/api/v1` analysis-job creation, listing, detail, and retry operations that return the persistent logical job UUID and expose queued, running, succeeded, and failed states, attempt timestamps, and sanitized failures.
- Coordinate durable job creation, broker dispatch, transactional worker claims and terminal transitions, redelivery, retry, and recovery of queued work without duplicate logical results or attempts.
- Add focused contract, PostgreSQL integration, and worker tests plus documented worker commands and configuration.

## Capabilities

### New Capabilities

- `persistent-analysis-job-orchestration`: Owner-scoped API and Celery delivery for durable analysis jobs, attempts, state transitions, retries, and safe recovery.

### Modified Capabilities

None. Existing API and database specifications already define the public job shape and core invariants; this change implements them without changing their requirements.

## Impact

- Backend API schemas/routes, domain service, Celery jobs package, existing job repositories, configuration, dependency lockfile, local worker startup documentation, and tests.
- Reuses existing Redis and PostgreSQL services and analysis job/attempt tables. Any demonstrated schema gap must use Alembic.
- AI prompt/provider integration, generated narrative, PDF execution, frontend polling UI, and deployment are outside this change. A successful analysis transition requires a validated result from a registered executor; this change must not manufacture one.

## Acceptance Criteria

- An authorized creation request returns HTTP `202` with a stable persistent job ID; status reads show PostgreSQL-backed `queued`, `running`, `succeeded`, or `failed` state, timestamps, attempt history, and safe processing errors. Foreign and missing jobs are indistinguishable.
- The worker claims a queued attempt once, persists its start and completion, and records either a validated result or a sanitized failure. Duplicate delivery and concurrent workers cannot create duplicate results or conflicting terminal states.
- Equivalent creation/retry requests replay the same logical operation. Retry adds one attempt only for an eligible failed job with unchanged semantic input; stale input and non-retryable states fail safely.
- Broker failure after durable acceptance leaves discoverable queued work for recovery; Redis is never queried as the status source. No credentials, customer content, provider payloads, stack traces, or internal storage keys appear in responses or logs.

## Verification

- Add runtime API contract coverage in `backend/tests/contract/api/test_analysis_jobs.py` for `202` IDs, all states, owner isolation, pagination, idempotency, retry conflicts, and redaction.
- Add isolated PostgreSQL and deterministic worker tests for claim races, delivery replay, queue/retry recovery, timestamps, successful validated-result persistence, sanitized failure, and stale completion.
- At implementation handoff run the focused contract, worker, and PostgreSQL suites, then `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and the stage-level backend test suite; report unavailable gates.
- Planning gate: `openspec validate gh-13-set-up-celery-workers-and-persistent-job-trackin --strict --json` must return valid with no issues, and proposal traceability must have exactly one versioned marker.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLpzTc","issueId":"I_kwDOVnzly88AAAABiSeHYg","branch":"feature/backend","baseCommit":"daa011add5e20ac77289c275b619ae268434c236","changeId":"gh-13-set-up-celery-workers-and-persistent-job-trackin","projectNumber":2,"issueNumber":13} -->
