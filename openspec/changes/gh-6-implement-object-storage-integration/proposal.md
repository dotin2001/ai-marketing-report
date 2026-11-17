## Why

The application already has private S3-compatible local infrastructure and database identities for file assets, but it has no production storage boundary that can durably write or retrieve original CSV files and generated PDFs. Implementing that boundary now completes the next dependency-ordered backend foundation while keeping object access private, owner-authorized, and independent of provider-specific details.

## What Changes

- Add a backend object-storage abstraction for immutable CSV and PDF objects, with deterministic environment/owner/report-scoped keys, streaming upload and retrieval, explicit metadata, SHA-256 integrity verification, bounded timeouts, and sanitized provider failures.
- Persist each successfully stored object's internal key, bucket/environment identity, safe filename, content type, byte size, checksum, purpose, and report ownership in the existing PostgreSQL `file_assets` model, and bind source CSV assets or generated PDF assets to their existing aggregate records.
- Coordinate storage and PostgreSQL so callers never observe a database record for an upload that did not complete, retries reuse or reconcile the same logical object safely, and failures after an object write are recoverable without exposing or silently adopting an untracked object.
- Provide owner-scoped retrieval for internal CSV processing/preview flows and authorized PDF downloads through a verified backend stream with safe response headers.
- Enforce private-bucket behavior, object metadata validation, checksum/size checks, and redaction of credentials, internal keys, source contents, and provider errors from public responses and logs.
- Add deterministic fake-adapter tests plus isolated PostgreSQL and live local S3-compatible integration coverage for upload, persistence, retrieval, authorization, retry/reconciliation, integrity failures, privacy, and streamed-download behavior.

## Capabilities

### New Capabilities

- `object-storage-integration`: Private immutable storage and owner-authorized retrieval of original CSV and generated PDF assets, with PostgreSQL metadata, integrity, idempotency, and failure-handling requirements.

### Modified Capabilities

None.

## Impact

- Affects backend storage adapters, domain services, owner-scoped repositories, source/PDF workflows, dependency wiring, API download handling, configuration, and tests.
- Reuses the existing boto3 dependency, strict S3 settings, SeaweedFS local service, `file_assets`, `report_sources`, and `pdf_exports` schema; no database migration is expected unless implementation discovery proves an approved invariant cannot be represented.
- Preserves the existing `/api/v1` resource and error contracts: object keys remain internal, original CSV retrieval is limited to authorized backend processing/preview paths, and completed PDF downloads remain the only public binary download operation in scope.
- Does not implement CSV parsing, PDF rendering, report lifecycle endpoints beyond the storage/download integration seam, public buckets, arbitrary object browsing/deletion, cloud provisioning, or a new authentication provider.

## Acceptance Criteria

- Original CSV files and generated PDFs are stored and retrievable through the backend object-storage abstraction.
- File metadata and internal object keys are saved in PostgreSQL and remain bound to the owning report and the correct source or PDF export aggregate.
- Stored files remain private; general API responses and logs do not expose internal object keys, credentials, provider details, or signed URLs.
- Retrieval is authorized through the report owner, cross-owner and missing resources are indistinguishable, and completed PDF downloads use an authorized backend stream.

## Verification

- Run focused unit and contract tests for key construction, filename/content-disposition safety, streaming checksum and size validation, provider error normalization, redaction, and retry/reconciliation behavior using deterministic fakes.
- Run isolated PostgreSQL integration tests for owner-scoped asset persistence, source/PDF bindings, uniqueness/idempotency constraints, rollback behavior, and owner-safe lookup failures.
- Run an opt-in live SeaweedFS integration suite that stores and retrieves CSV/PDF bytes, verifies metadata and SHA-256 integrity, proves anonymous/direct access is denied, checks an authorized streamed PDF download, and removes only test-scoped objects during cleanup.
- Run the backend stage checks and the relevant foundation/environment checks to confirm dependency wiring, configuration validation, type safety, and existing health behavior remain green.
- Run `openspec validate gh-6-implement-object-storage-integration --strict --json` and require a valid result with no issues; verify exactly one traceability marker exists in `proposal.md` and no traceability marker exists in another artifact.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa4mU","issueId":"I_kwDOVnzly88AAAABd54h8A","branch":"feature/database","baseCommit":"87cb414d7589e4adcad0f44a41c9f26b405e20e1","changeId":"gh-6-implement-object-storage-integration","projectNumber":2,"issueNumber":6} -->
