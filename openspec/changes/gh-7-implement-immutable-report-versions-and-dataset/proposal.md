## Why

The database foundation already rejects updates to stored datasets and versions, but the application has no domain workflow that builds a version from its exact current dataset, draft content, charts, and analysis. Issue #7 requires that complete binding so later edits and exports cannot silently change saved history.

## What Changes

- Add a transactional domain workflow that commits a confirmed canonical dataset as an immutable revision and keeps older revisions addressable when later source, mapping, normalization, or period changes produce a new dataset.
- Create an owner-authorized, idempotent report version from one expected active draft revision and the exact confirmed dataset revision, metric result set, validated analysis result, edited content, and chart configuration. Reject missing, stale, cross-report, or inconsistent references.
- Extend the version snapshot contract to include explicit dataset identity and safe, deterministic chart configuration, with a schema version that preserves validation of existing snapshots.
- Preserve database-enforced update/delete rejection and owner-scoped reads; restoring history creates a new mutable draft and never edits a dataset or version. PDF consumers remain bound to the saved version identity.
- Add focused unit and PostgreSQL integration verification for immutable revisions, coherent snapshots, concurrent/idempotent saves, ownership, and historical stability.

## Capabilities

### New Capabilities

- `immutable-report-versions-and-dataset-revisions`: Commit and retain immutable dataset revisions and complete, provenance-bound report versions.

### Modified Capabilities

None. This change implements the approved lifecycle, database, and API contracts and adds a focused persistence/domain contract for the issue; it does not change their externally defined routes.

## Impact

- Affects `backend/app/domain/`, `backend/app/db/`, an Alembic migration if the new snapshot binding needs relational fields, and focused backend tests.
- Uses existing PostgreSQL models, repository helpers, idempotency records, and private source/file metadata. No new external service or public file URL is required.
- Does not implement API routes, CSV parsing, KPI arithmetic, AI generation, PDF rendering, or frontend views, which remain separate stages.

## Acceptance Criteria

- A confirmed dataset revision and its canonical rows cannot be updated or deleted directly; a later confirmation produces a separately identifiable revision while prior versions retain their exact dataset.
- A saved report version cannot be updated or deleted directly and references its exact dataset, content, chart configuration, and analysis results, with source/import/metric provenance sufficient to reproduce the report.
- Version creation requires the current expected draft revision, compatible owner/report and input identities, and an idempotency key; concurrent or repeated requests cannot create conflicting snapshots, duplicate versions, or version-number gaps.
- History reads and restoration preserve earlier versions and datasets; cross-owner identifiers cannot reveal or change either resource. A PDF export remains bound to the selected saved version.

## Verification

- Run focused snapshot/domain unit tests and PostgreSQL integration tests for dataset/version immutability, exact reference binding, owner isolation, idempotency, concurrent saves, restoration, and historical PDF binding.
- Run the backend stage suite including formatting, lint, type checks, existing database integration tests, and migration upgrade verification if a migration is introduced. Report any unavailable gate.
- Run `openspec validate gh-7-implement-immutable-report-versions-and-dataset --strict --json` and require no issues.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa4zo","issueId":"I_kwDOVnzly88AAAABd54rzw","branch":"feature/database","baseCommit":"475c8396fc2822f34d1b62d5dc71c65ce6d83f28","changeId":"gh-7-implement-immutable-report-versions-and-dataset","projectNumber":2,"issueNumber":7} -->
