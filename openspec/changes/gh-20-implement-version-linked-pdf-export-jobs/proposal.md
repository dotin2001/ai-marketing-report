## Why

Saved versions and a snapshot-only PDF renderer exist, but owners cannot request a persisted export job for a specific version. Connecting rendering, storage, and job state makes a completed PDF retrievable while allowing a failed export to be retried without changing the saved version.

## What Changes

- Add owner-authorized PDF export creation, listing, detail, and retry under the version-scoped `/api/v1` routes already defined by the API contract.
- Persist one logical export per immutable version, snapshot identity, and template; run bounded Celery attempts that render the saved version and attach a verified generated-PDF asset.
- Expose queued, running, succeeded, and failed states with safe attempt and file metadata; recover queued or stale running work without duplicate exports, versions, or conflicting assets.
- Keep the existing authorized PDF download route bound to the completed export and version.

## Capabilities

### New Capabilities

- `version-linked-pdf-export-jobs`: Version-bound export creation, durable execution, safe retry, status, and delivery.

### Modified Capabilities

None. This implements the established API, database, lifecycle, rendering, and storage requirements without changing their contracts.

## Impact

The change affects backend PDF export schemas, routes, domain orchestration, Celery delivery and recovery, existing export repositories and asset storage, dependency wiring, and backend tests. It may require a migration only if verification finds an unrepresentable invariant; any such schema change must use Alembic. No frontend or report-version snapshot format change is planned.

Issue #20 acceptance criteria are preserved: generate each PDF from a specific saved version, upload and link the result to that version, and leave the version intact after failure so the same export can be retried. Verification must cover exact-version content after later draft edits, successful storage and authorized download, failed rendering or storage with safe status, same-version retry, duplicate requests and worker redelivery, ownership, PostgreSQL constraints, the backend stage suite, and strict OpenSpec validation.

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLp1hs","issueId":"I_kwDOVnzly88AAAABiSggRA","branch":"feature/backend","baseCommit":"f5135709a5c09bb4ea0052e7db3638aab112278c","changeId":"gh-20-implement-version-linked-pdf-export-jobs","projectNumber":2,"issueNumber":20} -->
