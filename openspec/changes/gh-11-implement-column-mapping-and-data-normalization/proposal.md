## Why

Owners can now revise column mappings and inspect full-file normalization errors, but cannot confirm an error-free review or turn its normalized rows into a current canonical dataset. Issue #11 calls for mapping and normalization to produce usable, owner-confirmed data while requiring ambiguous values to be resolved explicitly.

## What Changes

- Complete the CSV mapping and normalization path by adding explicit confirmation of the exact current validation, including warning acknowledgement and an idempotency key.
- Rebuild normalized canonical rows from the immutable source using the reviewed mapping and policy, verify they match the error-free validation, and atomically persist confirmation and the current canonical dataset with reproducible provenance.
- Treat ambiguous dates and other invalid mapped values as blocking errors until the owner changes the explicit normalization settings or source and validates a new revision; preserve valid duplicate rows and warnings under the existing rules.
- Expose the confirmed import and canonical dataset identity through the established owner-authorized `/api/v1` import contract, with safe stale-input, warning, conflict, and replay responses.
- Add focused processing, API contract, and PostgreSQL tests for confirmation, normalization fidelity, ownership, idempotency, and invalidation.

## Capabilities

### New Capabilities

- `confirmed-column-mapping-and-normalized-data`: Runtime completion of reviewed CSV mapping and normalization through explicit confirmation and canonical dataset commitment.

### Modified Capabilities

None. The active import/KPI, API, lifecycle, and database specifications already define the required behavior; no archived main specification exists under `openspec/specs/` to modify.

## Impact

- Affects `backend/app/domain/import_review.py`, `backend/app/domain/datasets.py`, processing and repository code as needed, `backend/app/api/sources.py` and Pydantic schemas, plus focused backend tests. It reuses immutable source retrieval, revision-bound validation, and existing confirmed-import and canonical-dataset tables.
- No frontend, KPI calculation, AI, PDF, or new source format is included. A migration is needed only if a proven schema gap prevents exact atomic confirmation.

## Acceptance Criteria

- The owner can map source columns one-to-one to required dimensions and at least one supported measure, choose an explicit supported date format when needed, validate every row, and confirm only the exact current error-free revision. Suggested mappings alone never confirm data.
- Dates normalize to ISO calendar dates; campaign names trim surrounding whitespace; currencies normalize to supported uppercase ISO 4217 codes; counts remain non-negative whole integers; spend remains a non-negative exact decimal in the row currency. Ambiguous dates, invalid or missing mapped values, and out-of-period dates block confirmation without guessing, imputing, dropping rows, or creating current data.
- Confirmation acknowledges every warning from the exact validation. Unmapped columns remain only in the immutable original; duplicate canonical rows remain included; mixed currencies remain distinct. Canonical rows retain source record and mapping provenance, and the dataset identity binds source checksum, mapping and policy revision, period, and canonical values.
- Stale source, mapping, policy, or period state, missing acknowledgement, and blocking errors cannot create a current confirmation or dataset. Equivalent retries return the original result without duplicate confirmations or datasets; conflicting keys fail safely.
- Absent and foreign resources have indistinguishable owner-safe responses. Responses and logs exclude cell values in errors, unrestricted source content, object keys, credentials, and provider details.

## Verification

- Extend `backend/tests/unit/processing/test_normalization.py` and `test_csv_import.py` with exact canonical-row output, ambiguous date resolution, invalid-value rejection, repeated headers, unmapped and duplicate rows, mixed currencies, and source-record provenance.
- Add `backend/tests/contract/api/test_import_confirmation_routes.py` for confirmation request and response schemas, exact warning acknowledgement, stale and blocked states, replay/key conflict, owner-safe errors, redaction, and OpenAPI alignment.
- Add `backend/tests/integration/processing/test_confirmed_import.py` for PostgreSQL-backed atomic confirmation and canonical commitment, source/policy/period invalidation, duplicate delivery, ownership, historical preservation, and rollback on failure. Verify migration upgrade if schema changes.
- At implementation handoff, run the focused suites, `backend/.venv/bin/ruff check backend`, `backend/.venv/bin/ruff format --check backend/app backend/tests backend/alembic`, `backend/.venv/bin/mypy backend/app`, and the full backend test suite against an isolated PostgreSQL test database. Report any unavailable gate. Require `openspec validate gh-11-implement-column-mapping-and-data-normalization --strict --json` to have zero issues.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhJbTF8","issueId":"I_kwDOVnzly88AAAABf-Rxxg","branch":"feature/backend","baseCommit":"a75f09bbf336924a75ab3274cb276e9b433e45bd","changeId":"gh-11-implement-column-mapping-and-data-normalization","projectNumber":2,"issueNumber":11} -->
