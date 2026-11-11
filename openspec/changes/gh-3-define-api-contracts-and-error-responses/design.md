## Context

See `proposal.md` for motivation and `specs/api-contracts-and-error-responses/spec.md` for normative behavior. The repository is still in the requirements-foundation stage: no FastAPI, Pydantic, database, frontend, or generated OpenAPI implementation exists. The completed lifecycle and import/KPI changes define the domain vocabulary this API must serialize, including owner-scoped resources, explicit confirmation, optimistic draft revisions, immutable versions, exact-decimal metrics, persisted job states, idempotency, and sanitized failures.

This change therefore fixes the public contract before the backend and frontend are scaffolded. It must be precise enough for later Pydantic models, routes, the generated OpenAPI document, a centralized TypeScript client, and contract fixtures to agree without redefining domain behavior. Authentication remains provider-neutral, but every operation receives an authenticated principal from the eventual authentication boundary.

## Goals / Non-Goals

**Goals:**

- Publish one coherent `/api/v1` endpoint, request, response, pagination, and error vocabulary for the seven-step MVP journey.
- Make concurrency and repeated-click behavior explicit at the HTTP boundary.
- Keep exact numeric and provenance data reproducible across Python, PostgreSQL, JSON, immutable snapshots, and the frontend.
- Give later backend work an authoritative schema catalog and executable contract-test matrix.
- Keep authorization failures and background-provider failures safe and non-enumerating.

**Non-Goals:**

- Implement routes, authentication, persistence, workers, storage, Pydantic models, OpenAPI generation, or a frontend client in this planning change.
- Choose an authentication provider, public host name, CORS policy, deployment topology, or object-storage vendor.
- Add deletion, bulk mutation, search, arbitrary sorting, GraphQL, webhooks, server-sent events, or WebSockets to the MVP.
- Return full original CSV/text content through general resource responses; bounded preview and authorized download/streaming remain separate trust boundaries.
- Redefine lifecycle, import normalization, KPI arithmetic, AI output, versioning, or PDF behavior owned by the earlier requirements.

## Decisions

### 1. Treat OpenSpec as the behavioral source and generated OpenAPI as the implementation artifact

The capability spec is normative until implementation. The future backend will define strict Pydantic request/response models and generate OpenAPI 3.1 from the exact models enforced at runtime. Contract tests will compare runtime behavior with that generated document. The repository should not maintain a separate hand-written OpenAPI file before a runtime schema layer exists because duplicate schema sources would drift.

Defining only prose endpoint names was rejected because it leaves DTO composition and failure behavior ambiguous. Hand-writing OpenAPI now was rejected because there is no application model to keep it synchronized with and this stage must not jump ahead of the database/backend delivery order.

### 2. Use consistent envelopes and scalar encodings

Single resources use `{ "data": { ... } }`; collections use `{ "data": [ ... ], "page": { ... } }`; errors use `{ "error": { ... } }`; and a true no-content success uses `204`. Resource responses are not wrapped in operation-specific keys.

Shared scalar rules are:

| Concern | Public encoding |
|---|---|
| Identifier | Canonical lowercase UUID string |
| Calendar date | `YYYY-MM-DD` |
| Instant | RFC 3339 UTC with `Z` |
| Exact decimal/count total | Base-10 JSON string; counts may be strings when used as exact metric inputs |
| Revision / attempt / version number | Positive JSON integer |
| Checksum | Algorithm plus lowercase digest, e.g. `{ "algorithm": "sha256", "value": "..." }` |
| Enum | Lowercase snake-case string fixed by the v1 schema |
| Optional value | Explicit JSON `null` only when the schema declares it; otherwise omit |

Exact decimals are strings because JSON numbers cannot preserve arbitrary decimal precision across Python and JavaScript. Unknown request fields are rejected so typos do not silently change behavior. Clients must ignore unknown response fields for additive compatibility, but adding enum members or changing required fields requires an API-version compatibility review.

Returning bare arrays was rejected because they cannot carry pagination metadata. Returning decimals as JSON numbers was rejected because the frontend could introduce binary-float artifacts. A universal `200` status was rejected because resource creation, asynchronous acceptance, and no-content operations have distinct semantics.

### 3. Publish this endpoint matrix

All paths below are relative to `/api/v1`. `{report_id}` remains in nested paths even when another identifier is globally unique so ownership and parent consistency are explicit and testable.

| Method and path | Request schema | Success | Idempotency / concurrency |
|---|---|---|---|
| `POST /reports` | `CreateReportRequest` | `201 ReportDetail` | Required key |
| `GET /reports` | `PageQuery` | `200 Page<ReportSummary>` | None |
| `GET /reports/{report_id}` | None | `200 ReportDetail` | None |
| `PATCH /reports/{report_id}/draft` | `UpdateDraftRequest` | `200 DraftDetail` | `expected_revision`; key optional |
| `POST /reports/{report_id}/sources/text` | `CreateTextSourceRequest` | `201 SourceDetail` | Required key |
| `POST /reports/{report_id}/sources/csv` | Multipart `file` | `201 SourceDetail` | Required key |
| `GET /reports/{report_id}/sources/{source_id}` | None | `200 SourceDetail` | None |
| `GET /reports/{report_id}/sources/{source_id}/preview` | `PreviewQuery` | `200 SourcePreview` | None |
| `PUT /reports/{report_id}/sources/{source_id}/import-configuration` | `PutImportConfigurationRequest` | `200 ImportConfiguration` | `expected_revision`; key optional |
| `POST /reports/{report_id}/sources/{source_id}/import-configuration/validate` | `ValidateImportRequest` | `200 ImportValidation` | Derived from source/config revision |
| `POST /reports/{report_id}/sources/{source_id}/import-configuration/confirm` | `ConfirmImportRequest` | `200 ConfirmedImport` | Required key and exact revision |
| `POST /reports/{report_id}/sources/{source_id}/review-confirmation` | `ConfirmTextReviewRequest` | `200 ConfirmedSourceReview` | Required key and exact review revision |
| `GET /reports/{report_id}/datasets/current` | None | `200 DatasetDetail` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}` | None | `200 DatasetDetail` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}/rows` | `PageQuery` | `200 Page<CanonicalRow>` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}/metrics` | `MetricQuery` | `200 MetricResultSet` | None |
| `POST /reports/{report_id}/analysis-jobs` | `CreateAnalysisJobRequest` | `202 AnalysisJob` | Required key and expected draft revision |
| `GET /reports/{report_id}/analysis-jobs` | `PageQuery` | `200 Page<AnalysisJobSummary>` | None |
| `GET /reports/{report_id}/analysis-jobs/{job_id}` | None | `200 AnalysisJobDetail` | None |
| `POST /reports/{report_id}/analysis-jobs/{job_id}/retry` | `RetryAnalysisJobRequest` | `202 AnalysisJobDetail` | Required key and unchanged input |
| `POST /reports/{report_id}/versions` | `CreateVersionRequest` | `201 VersionDetail` | Required key and expected draft revision |
| `GET /reports/{report_id}/versions` | `PageQuery` | `200 Page<VersionSummary>` | None |
| `GET /reports/{report_id}/versions/{version_id}` | None | `200 VersionDetail` | None |
| `POST /reports/{report_id}/versions/{version_id}/restore` | `RestoreVersionRequest` | `200 DraftDetail` | Required key and expected current draft revision |
| `POST /reports/{report_id}/versions/{version_id}/pdf-exports` | `CreatePdfExportRequest` | `202 PdfExportDetail` | Required key |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports` | `PageQuery` | `200 Page<PdfExportSummary>` | None |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}` | None | `200 PdfExportDetail` | None |
| `POST /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/retry` | `RetryPdfExportRequest` | `202 PdfExportDetail` | Required key and same version/input |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/download` | None | `200 application/pdf` or `303` short-lived signed location | Owner reauthorized at request time |

There is no general `DELETE` in the MVP because report/source/version deletion semantics and retention policy are not defined. Analysis and export polling use persisted resource GETs rather than broker state. A text source has an explicit review-confirmation endpoint because it does not create a canonical structured dataset.

### 4. Define request schemas with strict trust boundaries

| Schema | Required fields and constraints |
|---|---|
| `CreateReportRequest` | `name` trimmed, 1–200 Unicode characters; `period.start_date`; `period.end_date >= start_date`; `objectives` 1–20 trimmed strings, each 1–2,000 characters |
| `UpdateDraftRequest` | `expected_revision >= 1`; at least one of `objectives`, `narrative`, `limitations`, or labeled `claims`; no source, metric, analysis provenance, version, owner, or stage fields |
| `CreateTextSourceRequest` | `content` as an unchanged Unicode string within the configured source-byte limit; optional safe client display label; no instruction interpretation |
| CSV multipart | Exactly one non-empty `file`; configured byte limit; declared and detected CSV media type; UTF-8 or UTF-8 with BOM; original filename retained as untrusted metadata and separately normalized for display |
| `PutImportConfigurationRequest` | `expected_revision >= 0` (`0` means no prior configuration); unique mappings of `{ source_column_ordinal >= 0, canonical_field }`; normalization with explicit date format when non-ISO and `normalization_policy_version` |
| `ValidateImportRequest` | Exact `configuration_revision` and source preview identity |
| `ConfirmImportRequest` | Exact `configuration_revision`, validation identity, canonical-data preview identity, and complete set of acknowledged warning codes/identities |
| `ConfirmTextReviewRequest` | Exact source review revision and explicit acknowledgement that extracted figures remain unvalidated claims |
| `CreateAnalysisJobRequest` | `dataset_id`, `canonical_data_identity`, `metric_result_set_id`, `objectives_revision`, `expected_draft_revision` |
| `RetryAnalysisJobRequest` | Expected semantic input identity and last observed attempt ordinal |
| `CreateVersionRequest` | `expected_draft_revision` |
| `RestoreVersionRequest` | `expected_current_draft_revision` |
| `CreatePdfExportRequest` | Explicit supported `template_version` |
| `RetryPdfExportRequest` | Expected immutable input identity and last observed attempt ordinal |

Narrative values follow the AI contract sections: `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`. Each item is a structured object with stable identity, editable text where allowed, classification (`observation`, `hypothesis`, or `user_claim` where applicable), and metric/claim references. The later backend change may tune maximum lengths through reviewed configuration, but it may not make an unbounded request or silently truncate accepted content.

Using only `If-Match` was rejected because command bodies, audit records, browser recovery, and Pydantic validation all need the expected revision as domain data. ETags may be added as an HTTP optimization later, but the v1 mutation contract relies on explicit request fields.

### 5. Separate summary, detail, and immutable snapshot views

The future schema layer should compose response models from the following field groups. This is schema composition, not ORM reuse: database models must not be returned directly.

| Response model | Required public fields |
|---|---|
| `ReportSummary` | `id`, `name`, `period`, `stage`, active draft `{ id, revision }`, current source/dataset/analysis references when present, latest version `{ id, version_number }` when present, `created_at`, `updated_at` |
| `ReportDetail` | All summary fields plus `objectives`, `active_draft: DraftDetail`, current source/import/dataset/metric/job summaries, and safe available-operation indicators derived from persisted state |
| `DraftDetail` | `id`, `report_id`, `revision`, `objectives`, structured editable narrative, labeled claims, limitations, current metric-result-set and analysis-result references, `created_at`, `updated_at` |
| `SourceDetail` | `id`, `report_id`, `type`, byte size, checksum, media type/encoding, safe display filename and separately labeled untrusted original filename for CSV, review/configuration revision, `created_at`; never an object key |
| `SourcePreview` | Source/preview identities, bounded columns and rows or bounded text excerpt, original headers, ordinal and record provenance, `truncated`, returned/total counts when known, mapping suggestions labeled unconfirmed, claims labeled unvalidated |
| `ImportConfiguration` | `id`, report/source identities, revision, mappings, normalization settings and policy version, latest validation identity/summary, status `editing`, `validated`, or `confirmed`, timestamps |
| `ImportValidation` | Configuration and preview identities, deterministic summary counts, ordered `ValidationIssue[]`, canonical-data preview identity only when errors are absent, validation time |
| `ConfirmedImport` | Configuration/source identities and revisions, warning acknowledgement, canonical dataset identity, row count, period, currencies, confirming principal reference, confirmation time |
| `DatasetDetail` | `id`, `report_id`, source and confirmed-configuration identities/revisions, canonical-data identity, row count, inclusive period, currencies, normalization-policy version, confirmation provenance, `created_at` |
| `CanonicalRow` | Stable row identity, one-based source record index, mapped canonical values only, and source-column ordinal provenance; never unmapped values |
| `MetricResultSet` | Dataset/canonical identity, calculation version/time, ordered `MetricResult[]`, and scope metadata |
| `AnalysisJobSummary` | `id`, `report_id`, semantic input identity, state, attempt count, result presence, safe failure summary when failed, `created_at`, `updated_at` |
| `AnalysisJobDetail` | Summary plus captured dataset/metric/objective/draft identities, current attempt timestamps, ordered safe attempt summaries, validated `AnalysisResult` only when succeeded |
| `VersionSummary` | `id`, `report_id`, `version_number`, source draft identity/revision, template version, provenance summary, latest PDF export summary, `created_at` |
| `VersionDetail` | Summary plus immutable render snapshot: report metadata, safe source references/checksums, confirmed import identity, metrics, AI provenance/output, edited narrative, limitations, labeled claims, template version; never internal storage references |
| `PdfExportSummary` | `id`, report/version identities, template/input identity, state, attempt count, safe succeeded/failed indicator, `created_at`, `updated_at` |
| `PdfExportDetail` | Summary plus attempt timestamps/summaries, succeeded file metadata `{ filename, content_type, byte_size, checksum, download_available }` or sanitized failure |

`MetricResult` is a discriminated union on `availability`. `available` requires `value` and `unit` and forbids `reason`; `unavailable` requires one canonical reason and forbids `value`. Both variants retain exact input totals, scope, period, identities, version, and calculation time.

`AnalysisResult` contains the five structured output sections plus model identifier, prompt version, request provenance, and metric references. It does not include the raw provider response or unrestricted prompt. `JobFailure` contains only stable `code`, safe `message`, and `retryable`. Initial analysis failure codes are `provider_timeout`, `provider_refusal`, `provider_unavailable`, `incomplete_response`, `invalid_structured_output`, and `stale_result`; PDF failure codes are `render_failed`, `storage_unavailable`, `invalid_snapshot`, and `artifact_validation_failed`.

Returning one giant report graph on every list call was rejected for cost and accidental disclosure. Returning bare foreign keys without provenance was rejected because clients could not distinguish current mutable references from immutable snapshot identities.

### 6. Use signed opaque keyset cursors

`PageQuery` has `cursor?: string` and `limit?: integer` with default `25`, minimum `1`, and maximum `100`. The response metadata is:

```json
{
  "limit": 25,
  "has_more": true,
  "next_cursor": "opaque-or-null"
}
```

The server cursor payload is integrity-protected and binds the principal, route, parent identifiers, normalized filters, ordering, and last keyset boundary. It is opaque to clients and never authorizes access by itself. Reports, analysis jobs, and PDF exports use `(created_at DESC, id DESC)`; versions use `(version_number DESC, id DESC)`; immutable dataset rows use `(source_record_index ASC, row_id ASC)`. The implementation fetches `limit + 1` rows to derive `has_more` without a total-count query.

Offset pagination was rejected because concurrent inserts can duplicate or skip rows and large offsets degrade. Returning total counts by default was rejected because they add unnecessary work and may complicate owner-scoped query plans. Client-selected sort expressions were rejected for the MVP because they expand cursor compatibility and indexing scope.

### 7. Bind idempotency keys to canonical semantic requests

`Idempotency-Key` accepts 1–128 visible ASCII characters matching `[A-Za-z0-9._:-]+`. The server stores a cryptographic fingerprint of the canonical validated command, never the raw body, under a uniqueness boundary of principal, operation, parent resource, and key. Idempotency records remain for the lifetime of their logical result in the MVP. Same key plus same fingerprint returns the original status and representation with `Idempotency-Replayed: true`; same key plus another fingerprint returns `idempotency_conflict`.

The domain transaction must persist the idempotency record and logical mutation atomically. A worker attempt is not itself the idempotent result: analysis and PDF commands resolve to their persisted logical job/export. Retry keys distinguish user retry commands while uniqueness and legal state transitions prevent duplicate attempts under redelivery.

Process-local locks were rejected because they do not survive multiple API processes or retries. Comparing raw JSON bytes was rejected because equivalent object key order or formatting would appear different. Expiring keys quickly was rejected because version/export duplication remains dangerous after a browser retry window.

### 8. Use one safe error envelope with code-specific context allowlists

The envelope is:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "The request contains invalid fields.",
    "request_id": "opaque-correlation-id",
    "retryable": false,
    "details": [
      {
        "code": "invalid_period",
        "message": "End date must not precede start date.",
        "path": ["period", "end_date"]
      }
    ],
    "context": {}
  }
}
```

`details` is always an array and `context` is always an object, even when empty, so clients do not branch on shape. Request-property paths use JSON property names and zero-based array indexes. Import validation issues use their domain locations separately: optional `canonical_field`, zero-based `source_column_ordinal`, and one-based `source_record_index`. Messages never echo the rejected value.

| Error code | HTTP | Retryable | Allowed context |
|---|---:|---:|---|
| `invalid_request` | 400 | false | Empty |
| `invalid_cursor` | 400 | false | Empty |
| `unauthenticated` | 401 | false | Empty |
| `resource_not_found` | 404 | false | Requested resource type only |
| `revision_conflict` | 409 | false | Resource type/id, expected revision, current revision |
| `idempotency_conflict` | 409 | false | Operation name only |
| `lifecycle_conflict` | 409 | false | Current stage/state and allowed stages/states |
| `stale_input` | 409 | false | Safe current input identities/revisions |
| `warning_acknowledgement_required` | 409 | false | Unacknowledged warning identities/codes |
| `job_not_retryable` | 409 | false | Current job state |
| `export_not_ready` | 409 | true only for queued/running | Current export state |
| `payload_too_large` | 413 | false | Maximum accepted bytes |
| `unsupported_media_type` | 415 | false | Allowed media types |
| `unsupported_encoding` | 415 | false | Allowed encodings |
| `validation_failed` | 422 | false | Empty; field information belongs in details |
| `rate_limited` | 429 | true | Rate-limit scope; `Retry-After` header is authoritative |
| `internal_error` | 500 | false | Empty |
| `dependency_unavailable` | 503 | true | Empty; `Retry-After` required |

An authorization failure does not enter validation and never returns `revision_conflict` or another metadata-bearing response for a foreign resource. Persisted background failures appear in job resources, not as a later translation of the original accepted HTTP request into a provider-specific status.

Using framework-default validation bodies was rejected because their shape and type names can change and may reveal implementation details. One code per individual Pydantic rule was rejected as the top-level code because clients need a stable category plus structured field details. Returning `403` for a foreign report was rejected because it confirms resource existence.

### 9. Verify schemas at boundaries, not only by snapshotting documentation

The later backend change should create contract tests grouped by resource family and cross-cutting behavior. At minimum they must assert:

| Suite | Required evidence |
|---|---|
| Reports/drafts | Valid creation; every invalid creation field; owner isolation; stage serialization; successful and stale revision saves; protected-field rejection; no implicit version |
| Sources/imports | Text and CSV success; upload size/type/encoding failures; safe filenames; bounded previews; mapping schema; validation issue locations; warning acknowledgement; stale confirmation; no source-value echo |
| Datasets/metrics | Current/detail/row authorization; row pagination; exact decimal strings; available/unavailable union exclusivity; currency and period metadata |
| Analysis jobs | `202` creation; all four states; result schema; every sanitized failure code; equivalent replay; key conflict; unchanged-input retry; stale retry rejection |
| Versions | Sequential snapshot response; stale revision; replay without sequence gap; ordered pagination; immutable detail; restoration creates a new draft |
| PDF exports | `202` creation; all four states; same-version retry; succeeded file metadata; not-ready download; authorized stream/redirect; no object key |
| Pagination | Default/min/max limits; deterministic first/middle/final pages; empty page; invalid/tampered/cross-owner cursor; inserts before a keyset boundary |
| Errors/redaction | Every baseline code/status/retryability/context allowlist; request ID; multi-field validation order; no credential, token, signed URL, stack trace, provider payload, object key, or submitted source value |
| OpenAPI | Every operation/status/header/media type references the runtime model; example requests validate; response instances validate; no undocumented framework-default error body |

Schema snapshots alone were rejected because they can pass while runtime handlers return different data. End-to-end browser tests alone were rejected because they cannot efficiently cover the error matrix or prove schema exclusion.

## Risks / Trade-offs

- **[Risk] The contract is defined before database and backend scaffolding exist** → Keep the models resource-oriented and provider-neutral, then require later changes to conform rather than silently rewriting this capability.
- **[Risk] Deep detail resources can become large** → Keep list models shallow, paginate canonical rows and job/export history, bound previews, and retrieve full immutable version detail only by explicit ID.
- **[Risk] Strict request models may reject additive client experiments** → Centralize the client, version the API path, and make contract changes through reviewed OpenSpec deltas.
- **[Risk] Exact decimal strings require explicit frontend parsing/formatting** → Generate client types that keep decimals as strings and use display-only decimal formatting without round-tripping through JavaScript numbers.
- **[Risk] Rich error context can become an enumeration or data-leak channel** → Authorize before building context and enforce per-code context models plus redaction fixtures.
- **[Risk] Indefinite idempotency records add storage cost** → Store compact fingerprints and resource references; preserving no-duplicate guarantees is more important than early cleanup in the MVP.
- **[Trade-off] Polling persisted jobs adds request traffic** → It keeps PostgreSQL authoritative and works before introducing another delivery channel; polling cadence and caching can be tuned later without changing resource semantics.
- **[Trade-off] Fixed ordering limits client flexibility** → It makes pagination deterministic and indexable; search and alternate sorts can be separate reviewed features.

## Migration Plan

1. Apply only the requirements/documentation alignment tasks in this change; do not scaffold application code ahead of the database and backend stages.
2. Review the endpoint, request, response, and error matrices against the lifecycle and import/KPI capabilities and resolve any terminology conflict through the owning OpenSpec artifact.
3. Run strict OpenSpec validation, traceability uniqueness, issue-acceptance coverage, and whitespace checks.
4. After human approval and completion, archive the capability so later database, backend, processing, job/AI, version/PDF, and frontend changes can reference it.
5. During the focused backend change, implement strict Pydantic boundary models, thin routes, error normalization, idempotency persistence, and generated OpenAPI together with the named contract suites.
6. During frontend work, generate or hand-maintain one centralized typed client from the approved OpenAPI surface and keep unknown response fields forward-compatible.

There is no runtime deployment or production-data migration in this planning change. Before archive, rollback is revision or removal of these unimplemented artifacts; after archive but before implementation, any behavior change requires a reviewed delta rather than an undocumented edit.
