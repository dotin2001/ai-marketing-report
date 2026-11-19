## Why

Reports can be created, but owners cannot yet attach a CSV or pasted table through the API. Issue #9 requires a bounded, owner-authorized intake path that preserves each original source and makes it available for review before later mapping or analysis.

## What Changes

- Add authenticated, idempotent source attachment for one CSV file or unchanged pasted text on an existing report, with an owner-scoped source record and checksum.
- Validate upload size, declared and detected CSV content, UTF-8 encoding, CSV structure, and record limits; apply a byte limit to pasted text. Reject malformed or over-limit input without making a source current.
- Preserve original CSV bytes through the storage abstraction and original pasted Unicode in PostgreSQL. Retain the original CSV filename separately as labeled untrusted metadata and provide a normalized display name; neither value determines storage identity.
- Expose owner-authorized source detail and bounded previews, including source-column ordinals and original headers for CSV and a safe excerpt for pasted tabular text. Keep preview data explicitly unconfirmed and unvalidated.
- Make accepted sources enter `source_review` and invalidate current dataset, metrics, and analysis eligibility without changing immutable history. Add focused API, processing, storage, and PostgreSQL verification.

## Capabilities

### New Capabilities

- `source-ingestion`: Runtime CSV and pasted-text intake, immutable preservation, source metadata and previews, limits, safe errors, ownership, idempotency, and lifecycle effects. This implements the source endpoints already declared by the active API contract and the intake envelope declared by the active import specification.

### Modified Capabilities

None. There are no archived main specs under `openspec/specs/`; this change realizes existing active contracts without changing their requirements.

## Impact

- Affects `backend/app/api/`, `backend/app/domain/`, `backend/app/processing/`, storage integration, configuration, documentation, and backend tests. Existing source and asset tables are expected to suffice; use Alembic if a schema change proves necessary.
- CSV mapping, normalization, user confirmation, KPI calculation, AI analysis, frontend upload UI, and PDF export remain separate stages. Pasted tables remain untrusted text and do not create canonical metric inputs.

## Acceptance Criteria

- An authenticated report owner can upload one supported CSV or submit pasted tabular content; each accepted request creates one immutable source/import-intake record, preserves the exact original input and checksum, and makes that source current in `source_review`.
- CSV intake enforces configured byte and record limits, declared and detected CSV type, UTF-8 with optional BOM, and a parseable header. A header-only CSV remains reviewable but has a blocking `empty_dataset` issue at confirmation under the existing import contract. Pasted input enforces its configured byte limit and preserves Unicode content unchanged. Empty input, malformed syntax, unsupported encoding or type, and over-limit submissions are rejected with safe error codes and no current or partial source.
- The owner can retrieve source detail and a bounded, explicitly unconfirmed preview. CSV columns retain ordinal and original-header identity, rows retain one-based record indexes, and text preview remains labeled as unvalidated source content. The response contains no internal object key or unrestricted content.
- Missing or foreign reports and sources return indistinguishable owner-safe `404`; equivalent keyed replays return the original source, while a key reused with different input returns `409 idempotency_conflict` without another source or object.
- New source attachment invalidates current confirmation, dataset, metric, and analysis eligibility while preserving prior immutable resources. No intake request confirms mapping, calculates metrics, or starts a job.

## Verification

- Focused parser and API contract tests cover byte/row boundaries, UTF-8/BOM, malformed CSV, duplicate headers, content-type mismatch, formula-like cells, preview truncation, redaction, and request/response OpenAPI alignment.
- Isolated PostgreSQL integration and deterministic storage-fake tests cover ownership, exact preservation/checksums, idempotency under replay and concurrency, atomic current-source transition, compensation on failed persistence, and lifecycle invalidation. Run live storage tests only through their opt-in test-scoped configuration.
- Run backend lint, type check, relevant unit/contract/integration suites, and migration verification if a migration is needed; record any unavailable gate during implementation handoff. Run `openspec validate gh-9-implement-csv-upload-and-pasted-table-ingestion --strict --json` and require zero issues.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhJbR8Q","issueId":"I_kwDOVnzly88AAAABf-QzbQ","branch":"feature/backend","baseCommit":"4df5753b2f4fba5d18b93a5fbc6e4e969abfed74","changeId":"gh-9-implement-csv-upload-and-pasted-table-ingestion","projectNumber":2,"issueNumber":9} -->
