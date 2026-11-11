## Why

The MVP lifecycle and data-processing rules are defined, but the repository does not yet have an implementation-ready HTTP contract for the frontend and backend to share. Defining the versioned resource schemas, pagination, validation failures, and stable error envelope now prevents later backend and frontend stages from making incompatible assumptions or leaking internal state.

## What Changes

- Define the `/api/v1` contract for owner-scoped reports and drafts, immutable sources and import review, confirmed datasets and metric results, persisted analysis jobs, immutable report versions, and version-bound PDF exports.
- Define request, success-response, and resource-summary/detail schemas with UUID identities, ISO 8601 UTC timestamps, decimal-string serialization, explicit revisions, lifecycle and job states, provenance, and safe links or actions.
- Standardize collection pagination on opaque cursors and deterministic ordering, including first, next, and exhausted-page behavior.
- Standardize one JSON error envelope with stable machine-readable codes, safe human-readable messages, request correlation, field/row issue details, retryability, and current-resource metadata for conflicts.
- Define HTTP status and domain-error mappings for malformed input, authentication and owner-scoped absence, lifecycle conflicts, optimistic-concurrency failures, idempotent mutations, unavailable metrics, rate limits, and sanitized dependency failures.
- Define contract and OpenAPI verification required before backend implementation, including success, validation, authorization, conflict, idempotency, pagination, state-serialization, and sensitive-data regression cases.
- Keep this change planning-only: it does not add FastAPI or frontend code, database migrations, dependencies, infrastructure, or external-system mutations.

## Capabilities

### New Capabilities

- `api-contracts-and-error-responses`: Versioned HTTP resources and operations for the complete MVP workflow, common serialization and pagination rules, stable success/error envelopes, validation details, idempotency and concurrency headers, authorization-safe failures, and required contract verification.

### Modified Capabilities

None.

## Impact

- Constrains the future FastAPI route and Pydantic schema layer, generated OpenAPI document, centralized frontend API client, and contract-test fixtures.
- Reuses the existing lifecycle, import, KPI, ownership, immutability, job-state, and retry requirements without changing their domain behavior.
- Requires later persistence and service changes to expose only owner-authorized resource views and sanitized failure data; raw provider errors, storage keys, credentials, and unrestricted source content remain outside public schemas.
- Introduces no runtime or data migration impact in this planning change.

## Verification

- Review every issue-requested resource family against the endpoint and schema matrix in the design and capability spec.
- Verify every mutating operation declares its revision and/or idempotency semantics and every collection declares deterministic cursor pagination.
- Verify all validation, authorization, conflict, lifecycle, and dependency failures use the standard error envelope and expose no protected resource existence or internal provider/storage details.
- Run `openspec validate gh-3-define-api-contracts-and-error-responses --strict --json` and require a valid result with no issues before handoff.
- Run a single-marker traceability check and whitespace review over this change directory.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa284","issueId":"I_kwDOVnzly88AAAABd53G4Q","branch":"feature/set_up","baseCommit":"22ffb6b3e193e5888e71cfef2aeef27d73578cd7","changeId":"gh-3-define-api-contracts-and-error-responses","projectNumber":2,"issueNumber":3} -->
