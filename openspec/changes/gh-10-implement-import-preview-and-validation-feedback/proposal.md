## Why

CSV attachment currently returns an unvalidated sample, but owners cannot submit a mapping revision or see which rows and columns prevent confirmation. Issue #10 calls for an import review response that shows the source shape, total record count, and actionable validation feedback before the later confirmation step.

## What Changes

- Keep the existing bounded, owner-authorized CSV preview as the source of column ordinals, original headers, sample rows, and total data-record count; make its relationship to the reviewed revision explicit.
- Add owner-authorized import-configuration revision and validation operations using the `/api/v1` paths already declared in the API contract.
- Validate the complete current CSV against the mapping, normalization policy, and inclusive report period; return a revision-bound summary and stable issues with row and column locations and clear blocking severity.
- Persist validation results and issues for the exact revision while preserving the immutable original; reject stale review attempts and keep confirmation unavailable whenever errors remain.
- Add focused processing, API contract, and PostgreSQL tests for feedback, authorization, revision conflicts, and the confirmation gate.

## Capabilities

### New Capabilities

- `import-preview-and-validation-feedback`: Runtime mapping review, complete-dataset validation, persisted revision-bound issues, and safe feedback for CSV imports.

### Modified Capabilities

None. The existing active source-ingestion, import/KPI, lifecycle, database, and API contracts already define this behavior. There are no archived main specs under `openspec/specs/` to modify.

## Impact

- Affects `backend/app/api/`, `backend/app/domain/`, `backend/app/processing/`, existing import tables and repositories, and backend tests. Existing source preview and storage retrieval provide the input boundary; no frontend or AI work is in this stage.
- The change does not implement import confirmation, canonical dataset creation, KPI calculation, or analysis. Those operations remain gated on an error-free, explicitly reviewed revision.

## Acceptance Criteria

- An authenticated owner can retrieve CSV column names by ordinal, bounded sample rows with one-based record indexes, and the total data-record count; a header-only CSV reports zero records and a blocking `empty_dataset` issue during validation.
- The owner can submit or revise a one-to-one mapping and explicit normalization settings using an expected revision. Validation checks every record of the exact current source and configuration revision, rather than only sampled rows.
- Validation returns a stable code, severity, safe message, and applicable canonical field, source-column ordinal, and one-based record index for each issue. The response reports error and warning totals and whether confirmation is blocked. Mapping, row, period, duplicate, unmapped-column, and mixed-currency cases follow the existing import contract.
- An error blocks confirmation; warnings are visible but do not block it and must be acknowledged later. Changed source, mapping, normalization policy, or report period makes prior validation and confirmation ineligible for current use.
- Missing or foreign report/source pairs are indistinguishable `404` responses; stale revisions return a safe conflict; responses and logs do not reveal internal object keys, credentials, unrestricted source content, or submitted cell values in issue messages.

## Verification

- Unit tests cover parsing and normalization, mapping errors, row/column locations, record counts, duplicate headers, missing or invalid values, ambiguous dates, period bounds, duplicate rows, mixed currencies, warning versus error totals, and full-dataset checks beyond the sample limit.
- API contract tests cover preview and validation schemas, error envelopes, ownership, stale revisions, safe redaction, and generated OpenAPI alignment.
- PostgreSQL integration tests cover owner-scoped configuration and persisted issue reads, revision compare-and-set, source/period invalidation, and rejection of confirmation when errors exist. Run migration upgrade verification only if a schema change is required.
- Run the focused backend suites, backend lint and type checks, then the stage-level backend suite. Record any unavailable gate at implementation handoff. Require `openspec validate gh-10-implement-import-preview-and-validation-feedback --strict --json` to report zero issues.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhJbSj0","issueId":"I_kwDOVnzly88AAAABf-RTjg","branch":"feature/backend","baseCommit":"9af9fcfe78fb536cbcd2d6488986a661e13160a8","changeId":"gh-10-implement-import-preview-and-validation-feedback","projectNumber":2,"issueNumber":10} -->
