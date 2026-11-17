## Context

See `proposal.md` for motivation and `specs/object-storage-integration/spec.md` for normative behavior. The foundation stage already provisions a private SeaweedFS S3 gateway and constructs a lifespan-owned boto3 client from strict S3 settings. The database stage already provides immutable `file_assets`, owner/report-scoped `report_sources`, version-bound `pdf_exports`, and their aggregate foreign keys. It intentionally does not perform object I/O.

The implementation must bridge those two completed stages without treating S3 as an authorization system or introducing a distributed-transaction illusion. Boto3 is synchronous while FastAPI is asynchronous. File content and filenames are untrusted, storage failures can occur before or after a provider accepted a request, and no concrete authentication provider has been selected; public handlers must depend on the repository's authenticated-principal interface boundary. The existing API contract permits a streamed PDF or a signed redirect; this change selects verified backend streaming.

## Goals / Non-Goals

**Goals:**

- Give CSV source and PDF export flows one typed storage port with a production S3-compatible adapter and deterministic fake.
- Preserve exact bytes, compute and verify SHA-256 and byte length, and make logical retries converge without overwriting different content.
- Bind only verified objects to existing owner-scoped PostgreSQL aggregates and make crash windows recoverable by retry.
- Return verified CSV content to internal processing and a safe, authorized PDF stream to the existing download contract.
- Bound memory, blocking work, network timeouts, response metadata, and test cleanup.

**Non-Goals:**

- Implement CSV parsing, mapping, PDF rendering, general report/source/export CRUD, a concrete identity provider, public object access, signed URLs, object browsing, retention deletion, cloud provisioning, or bucket lifecycle rules.
- Share assets across reports or deduplicate distinct logical source/export commands merely because their bytes match.
- Promise atomic commit across PostgreSQL and S3; the design instead provides explicit verification, compensation, and retry convergence.

## Decisions

### 1. Introduce a narrow storage package with two real consumers

Add `backend/app/storage/` with value objects and a protocol for `put_if_absent`, `head`, `get`, and `delete_exact`, plus an S3-compatible adapter and an orchestration service. The protocol accepts already validated internal object identities and metadata; it does not accept arbitrary buckets, caller-selected keys, ACLs, or listing requests. Source and PDF domain services call the same orchestration service, satisfying the repository rule that an abstraction must have at least two real consumers.

The existing lifespan-owned boto3 client remains the provider client. Configure it with botocore connect/read timeouts, bounded standard retries, and path-style addressing needed by local SeaweedFS. Because boto3 calls and response bodies are synchronous, run each bounded provider operation in AnyIO's worker thread pool and always close response bodies. Do not block the event loop and do not create a new client per request.

Using boto3 directly in route handlers was rejected because it would duplicate key construction, error handling, blocking-I/O handling, and redaction. Replacing boto3 with another async SDK was rejected because the pinned dependency already supports the required S3 contract and adding a second provider client would increase lockfile and compatibility surface.

### 2. Build versioned deterministic keys only from trusted scope and logical identities

The storage service, not callers, builds keys in these forms:

```text
v1/{app_env}/owners/{owner_id}/reports/{report_id}/sources/{source_identity}/original.csv
v1/{app_env}/owners/{owner_id}/reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/report.pdf
```

UUIDs are serialized canonically and `app_env` is a validated fixed enum. `source_identity` is the stable identity reserved by the idempotent source command before storage I/O; `version_id` and `export_id` already exist for PDF work. Untrusted original/display filenames never enter a key. Provider metadata records schema version, owner ID, report ID, purpose, logical ID, content type, byte size, and lowercase SHA-256. PostgreSQL stores the configured environment and bucket with the key so historical metadata is explicit even if configuration later changes.

The `v1` prefix permits a future key-layout migration without interpreting old keys. Random keys were rejected because a crash after S3 success but before PostgreSQL commit would make the object undiscoverable by retry. Content-addressed keys were rejected because identical bytes from separate commands must remain separate owner/report/source or export assets and may carry different safe metadata.

### 3. Prepare bounded seekable content before provider I/O

Introduce purpose-specific validated limits in settings and examples: `SOURCE_CSV_MAX_BYTES`, `GENERATED_PDF_MAX_BYTES`, and `OBJECT_STORAGE_TIMEOUT_SECONDS`. Values are positive and bounded; secret values remain `SecretStr`. The storage service copies an input stream once into a `SpooledTemporaryFile`, incrementally computes SHA-256 and byte length, rejects a limit breach without uploading, then rewinds the prepared file. CSV acceptance rules such as supported media type and UTF-8 decoding remain the source workflow's responsibility; storage receives an already accepted `text/csv` object. PDF storage requires `application/pdf`, a non-empty body, and the PDF workflow's prior artifact validation.

The prepared descriptor contains purpose, trusted logical scope, safe filename, content type, size, digest, and a seekable handle. Small files remain in bounded memory and larger accepted files spill to the OS temporary directory. All handles are context-managed and closed on success, failure, or cancellation.

Buffering the complete file in bytes was rejected because configured upload limits can still be large enough to create avoidable memory pressure. Streaming directly to S3 before knowing the checksum was rejected because retries could not safely compare an uncertain existing object and a limit failure could occur after remote bytes were written.

### 4. Create or verify an immutable object with a conditional write

For a logical write, the adapter first performs `HEAD` on the exact key:

1. If no object exists, send a conditional `PutObject` using `If-None-Match: *`, the exact content length/type, and the required integrity/ownership metadata.
2. If the condition loses a race or `HEAD` found an object, compare every required metadata field, content length, and content type with the prepared descriptor.
3. For a newly written object, immediately retrieve it into a second bounded temporary stream and recompute length and SHA-256. Mark the write verified only when the full bytes match. For an existing exact-metadata retry, also retrieve and hash before adoption; metadata alone is not sufficient proof.
4. A mismatch is an immutable-key collision or integrity failure. Never overwrite, adopt, or delete an object that does not exactly match the command.

Conditional creation prevents concurrent different commands from replacing each other. A provider error is normalized into `storage_timeout`, `storage_unavailable`, `storage_forbidden`, `object_collision`, or `integrity_failed`; provider messages and request URLs are retained only inside redacted debug instrumentation, never public output. The live SeaweedFS test is the compatibility gate for conditional writes and metadata round trips.

Relying on ETag was rejected because multipart and S3-compatible ETag semantics are not a portable SHA-256 contract. Trusting caller-supplied checksum metadata without reading the object was rejected because it cannot detect truncated or corrupted stored content.

### 5. Use retryable choreography instead of a distributed transaction

The application service sequence is:

1. Authorize/lock the owner-scoped aggregate and reserve or load its stable logical identity using the existing idempotency semantics.
2. Prepare and create-or-verify the object outside a long-running PostgreSQL transaction.
3. In one short database transaction, insert or load the one `FileAsset`, validate all metadata, and bind it to the CSV source or PDF export aggregate.
4. For PDFs, transition the matching attempt/export to `succeeded` only in the same transaction that binds the generated asset. For CSVs, attach the source and asset and update the report's current-source pointer in the same transaction.
5. If the database transaction fails after this invocation created the object, issue a best-effort `delete_exact` only when a fresh `HEAD` still matches the exact owner, purpose, logical identity, size, and checksum. Never delete an object found before the invocation or one whose metadata changed.

A process crash can leave an unbound but correctly scoped object. The same logical retry computes the same key, verifies its full bytes, and completes the database binding. PostgreSQL uniqueness and owner/report aggregate foreign keys remain the final authority against duplicate or cross-aggregate bindings. Repositories gain focused owner-scoped functions to load asset/source/export tuples and insert the bindings; lifecycle decisions remain in domain services.

Holding a database transaction open during network I/O was rejected because provider latency would retain locks and connections. Writing PostgreSQL first was rejected because readers could observe metadata for a missing object. Unconditionally deleting after database failure was rejected because the invocation may have discovered a valid object created by an earlier attempt.

### 6. Verify a complete object before processing or responding

Owner-scoped retrieval services query PostgreSQL by `owner_id`, `report_id`, and source or export identity, joining the bound `FileAsset`. A missing row and a cross-owner row both return the same domain `resource_not_found` without any S3 call. An object key or asset ID is never accepted as caller authorization.

Retrieval streams the provider body into a bounded temporary file while computing SHA-256 and length, compares the result plus provider content type with PostgreSQL, closes the provider body, then rewinds the verified file. Internal CSV preview/processing receives this context-managed verified handle. The PDF download application service additionally requires `PdfExport.state == "succeeded"`, purpose `generated_pdf`, and the exact export/version/asset aggregate binding.

The thin `GET /api/v1/reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/download` handler obtains an `AuthenticatedPrincipal`, calls the service, and returns `StreamingResponse` with `application/pdf`, exact `Content-Length`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, and an attachment `Content-Disposition` built from the persisted safe filename. A background/finalizer closes the temporary file after the response. Queued/running/failed exports map to the approved `409 export_not_ready`; storage failures use a sanitized stable error or persisted failure as appropriate.

Streaming directly from the provider response was rejected because an integrity mismatch discovered late could expose partial untrusted bytes. A `303` presigned redirect was deferred because backend streaming satisfies the approved API contract with a smaller credential/URL leakage surface and permits verification before delivery.

### 7. Keep filenames and observability safe by construction

CSV `original_filename` remains untrusted provenance in PostgreSQL; `display_filename` and `FileAsset.safe_filename` use the existing safe-filename policy. Generated PDFs receive a server-created filename such as `report-{version_number}.pdf`. Content-Disposition uses an ASCII fallback plus RFC 5987 encoding from the safe filename, strips control/path characters, and never incorporates the raw object key or original filename.

Storage logs contain only a request/correlation ID, operation name, purpose, outcome code, and elapsed-time bucket. They omit file content, original filenames, bucket, key, endpoint, credentials, provider response bodies, and exception strings that may contain signed request data. Tests pass sentinel secrets and object identifiers through every error path and assert they do not appear in responses or captured ordinary logs.

Logging raw provider exceptions was rejected because botocore messages can include endpoint and request details. Returning provider status codes directly was rejected because they are not a stable public contract and could reveal whether a private object exists.

### 8. Verify three layers with fail-closed cleanup

Unit/contract tests use a deterministic in-memory fake storage adapter to cover exact bytes, size limits, digesting, conditional races, collisions, error normalization, compensation eligibility, response headers, and redaction. PostgreSQL integration tests use the existing isolated `_test` database guard to cover owner filters, source/PDF bindings, uniqueness, retry convergence, transaction rollback, and state transitions.

Add an opt-in live marker and command for local SeaweedFS. It requires explicit test settings, creates UUID-named objects under `v1/test/...`, proves anonymous direct GET/list denial, exercises conditional PUT/HEAD/GET/delete behavior and CSV/PDF round trips, and records every exact key it created. Cleanup deletes only those recorded keys after rechecking the `test` environment prefix; it never empties a bucket or uses an unresolved prefix. Normal `backend:check` uses fakes and does not require S3 or PostgreSQL; the live command is documented separately and can be composed with the existing isolated database verification where needed.

## Risks / Trade-offs

- **[Two-system crash window leaves an orphaned object]** → Deterministic logical keys make the object discoverable by retry; exact-match adoption completes the binding, and best-effort deletion is allowed only for an object created and still matched by the failing invocation.
- **[Full pre-upload and post-download verification adds I/O and temporary disk use]** → Files are bounded, spooled, and verified for correctness; this is acceptable for MVP CSV/PDF sizes and can later be optimized with a proven provider checksum contract without changing behavior.
- **[Synchronous boto3 can exhaust worker threads under load]** → Bound file sizes, provider timeouts, SDK retry counts, and AnyIO's thread limiter; add saturation/load evidence before raising concurrency.
- **[Conditional S3 behavior differs across compatible providers]** → Keep the adapter contract narrow and make the live SeaweedFS suite a required compatibility check; fail closed when conditional or metadata semantics are unsupported.
- **[Temporary disk exhaustion]** → Enforce purpose-specific limits before accepting more bytes, close/unlink every spool deterministically, surface a sanitized unavailable failure, and monitor only aggregate failure codes.
- **[A streamed response holds a verified temporary file]** → Close it through response finalization and test disconnect/cancellation paths; use `private, no-store` and no range support in this change.
- **[No signed URLs can increase backend bandwidth]** → Accept the cost for MVP security and integrity; a future reviewed change may add short-lived redirects within the existing API contract.

## Migration Plan

1. Add and document the non-secret size/timeout settings with fail-fast validation, while retaining existing S3 credential and HTTPS rules.
2. Add the storage port, S3 adapter, deterministic fake, and dependency wiring; keep readiness using the same lifespan-owned client.
3. Add owner-scoped repository functions and domain services for CSV asset attachment, PDF asset completion, and verified retrieval. The existing schema is sufficient, so do not create a migration unless implementation finds a concrete approved invariant that cannot be enforced.
4. Mount the thin PDF download handler behind the authenticated-principal dependency and stable error mapper; do not add an original CSV download endpoint.
5. Run fake, backend, isolated PostgreSQL, and opt-in live SeaweedFS verification before enabling the integration in a non-local environment.

Rollback removes the new handlers/services and restores the prior runtime wiring. Existing `file_assets`, source bindings, export bindings, and private objects remain compatible immutable data and MUST NOT be bulk-deleted during rollback. If a forward schema migration becomes necessary after review, it must include its own safe downgrade analysis; none is planned by this design.
