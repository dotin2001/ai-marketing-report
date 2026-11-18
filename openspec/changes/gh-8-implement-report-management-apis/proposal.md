## Why

The database already stores owner-scoped reports and revisioned drafts, but the HTTP API exposes no report management routes. Issue #8 requires clients to create, list, retrieve, and update report metadata with validation and pagination.

## What Changes

- Implement authenticated `/api/v1/reports` creation, listing, detail retrieval, and report metadata update, using the existing single-resource and collection envelopes.
- Validate trimmed report names, inclusive reporting periods, and non-empty bounded objectives; retain objectives in the active draft and update them through its revisioned draft command.
- Add `PATCH /api/v1/reports/{report_id}` for name and/or period changes. This extends the earlier API matrix, which only defines draft updates. Period changes invalidate current confirmation and derived analysis while preserving historical datasets and versions.
- Apply owner-safe reads, deterministic cursor pagination, creation idempotency, and revision-aware updates. Replays and rejected requests cause no partial writes.
- Add executable report API, domain, and PostgreSQL verification plus generated OpenAPI checks.

## Capabilities

### New Capabilities

- `report-management-apis`: Runtime report creation, owner-scoped listing/detail, metadata and objective updates, validation, idempotency, pagination, and safe responses. It extends the report routes in the existing `api-contracts-and-error-responses` change without changing unrelated resource families.

### Modified Capabilities

None. The repository's main `openspec/specs/` contains no archived capability to modify; the new delta explicitly extends the active API contract with metadata update behavior for review.

## Impact

- Affects `backend/app/api/`, `backend/app/domain/`, `backend/app/db/`, backend tests, and generated OpenAPI. A migration is needed only if the existing schema cannot enforce the planned concurrency or idempotency behavior.
- Reuses the current PostgreSQL report, draft, objective, and idempotency models. No frontend, import-processing, AI, versioning, or PDF implementation is part of this change.
- Authentication remains the existing provider-neutral principal dependency; production identity integration is a separate prerequisite for deployment.

## Acceptance Criteria

- An authenticated owner can create a report with a valid name, inclusive period, and at least one objective; the response contains a revision-1 active draft in `created` stage and no implicit source, job, version, or export.
- Owners can list reports in deterministic cursor pages and retrieve a detail; foreign and missing report IDs produce the same safe `404`, and unauthenticated requests produce `401`.
- Owners can update name and period through the metadata route and objectives through the existing revisioned draft route. Invalid names, dates, objectives, unknown fields, empty updates, stale revisions, and conflicting creation keys are rejected without changing persisted state.
- A changed period invalidates current confirmation and analysis eligibility without mutating historical immutable resources; a name-only edit preserves current input validity. Repeated equivalent creation returns the same report.
- Responses, errors, pagination, and generated OpenAPI conform to the approved v1 contract and contain no secret or internal storage data.

## Verification

- Run focused report API contract tests, domain unit tests, and isolated PostgreSQL integration tests for ownership, validation, pagination boundaries/cursor misuse, revision conflicts, idempotency/replay, period invalidation, and transaction rollback.
- Run the backend stage checks (format/lint, type check, unit tests, PostgreSQL integration tests, and migration upgrade verification if a migration is added); exercise generated OpenAPI against runtime report responses.
- Run `openspec validate gh-8-implement-report-management-apis --strict --json` and require no issues. Report any unavailable gate.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhJbRno","issueId":"I_kwDOVnzly88AAAABf-QhPA","branch":"feature/backend","baseCommit":"913dc9485faf93a885a0b98f67ec0dec94a11bb0","changeId":"gh-8-implement-report-management-apis","projectNumber":2,"issueNumber":8} -->
