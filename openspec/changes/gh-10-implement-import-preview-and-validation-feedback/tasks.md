## 1. Persistence and revision identity

- [x] 1.1 Add an Alembic migration and model fields for validation source checksum, period snapshot and revision, and total data-record count; verify upgrade against the isolated PostgreSQL migration suite and safe handling of preexisting validation rows.
- [x] 1.2 Add owner-scoped repository operations to create the first import configuration, append revisions with expected-revision compare-and-set, persist ordered validation issues, and read the exact validation result; verify incomplete mappings, duplicate mapping rejection, stale writes, and ownership in PostgreSQL integration tests.

## 2. Complete-data processing

- [x] 2.1 Implement versioned normalization of mapped dates, campaign names, ISO currency codes, counts, and exact-decimal spend from original CSV strings; verify missing, ambiguous, invalid, negative, and out-of-period cases in `backend/tests/unit/processing/test_normalization.py`.
- [x] 2.2 Implement deterministic full-dataset issue generation for required/duplicate mappings, empty dataset, unmapped columns, invalid rows, exact duplicate canonical rows, and mixed currencies; verify stable codes, severities, record and column locations, issue order, and counts in `backend/tests/unit/processing/test_csv_import.py`.
- [x] 2.3 Verify validation inspects rows beyond `SOURCE_PREVIEW_MAX_ROWS`, preserves repeated-header ordinals, reports a header-only file as `empty_dataset`, and never drops or imputes invalid mapped values in processing unit tests.

## 3. Import review service and API

- [x] 3.1 Add a domain service that authorizes report/current CSV source, retrieves verified original bytes, validates against the captured configuration and period, rechecks freshness transactionally, and persists a revision-bound result without confirming or creating metrics; verify source/period races and no downstream side effects in PostgreSQL and storage-fake tests.
- [x] 3.2 Add Pydantic request/response schemas and `PUT .../import-configuration` plus `POST .../validate` routes under `/api/v1/reports/{report_id}/sources/{source_id}`; verify response envelope, complete safe issues, `confirmation_blocked`, revision conflicts, and OpenAPI alignment in API contract tests.
- [x] 3.3 Verify absent and foreign report/source pairs produce the same `404`, structural mapping errors return located `422` details, and issue messages and responses contain no cell values, object keys, or credentials in API contract tests.
- [x] 3.4 Verify the existing preview still returns bounded columns, indexed samples, total record count, truncation, and unvalidated status for CSV and pasted text in source-route contract tests.

## 4. Stage verification and handoff

- [x] 4.1 Run the focused processing, API contract, and isolated PostgreSQL integration suites and resolve failures; record the exact commands and results in the implementation handoff.
- [x] 4.2 Run backend lint, mypy, the stage-level backend test suite, migration upgrade verification, and `openspec validate gh-10-implement-import-preview-and-validation-feedback --strict --json`; record any unavailable gate and require zero OpenSpec validation issues.
