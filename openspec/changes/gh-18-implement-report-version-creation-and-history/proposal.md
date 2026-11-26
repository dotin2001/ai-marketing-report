## Why

The database and domain layers can save and restore immutable report versions, but owners cannot create, inspect, or restore them through the public API. This change completes the version boundary after editable drafts and before PDF export.

## What Changes

- Expose owner-authorized version creation from the exact active draft revision, with scoped idempotency and a complete immutable snapshot.
- Expose paginated, stable version history and a version detail that preserves reproducibility while withholding private storage references and unrestricted source content.
- Restore a selected version into a new mutable active draft using the expected current draft revision and an idempotency key, leaving all history unchanged.
- Cover stale and duplicate requests, incompatible snapshot bindings, authorization, immutability, and concurrent numbering with API and PostgreSQL tests.

## Capabilities

### New Capabilities

- `report-version-creation-and-history`: Public creation, owner-scoped history and detail, and retry-safe draft restoration for immutable report versions.

### Modified Capabilities

None. This change implements the version behavior already established in the active API, database, and immutable-version specifications.

## Impact

The backend gains version request and response schemas, thin `/api/v1/reports/{report_id}/versions` routes, a domain service for read and transaction orchestration, and contract and PostgreSQL tests. Existing `backend/app/domain/versions.py`, snapshot models, repository functions, and database constraints are reused or corrected where verification finds a contract gap. PDF rendering, export orchestration, frontend history UI, and new environment variables are outside this change.

The issue acceptance intent is preserved: create numbered snapshots from drafts, list and retrieve versions, and create a new draft from an existing version without modifying it. Verification requires focused version API and PostgreSQL tests, the backend stage suite, and strict OpenSpec validation before implementation handoff.

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLp08E","issueId":"I_kwDOVnzly88AAAABiSf7Cg","branch":"feature/backend","baseCommit":"6a49307e2cde0599f1350c63f502a224b92dbea9","changeId":"gh-18-implement-report-version-creation-and-history","projectNumber":2,"issueNumber":18} -->
