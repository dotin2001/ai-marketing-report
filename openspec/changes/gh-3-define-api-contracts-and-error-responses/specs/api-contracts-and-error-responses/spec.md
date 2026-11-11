## Purpose

Define a stable, owner-authorized `/api/v1` contract so backend, frontend, workers, and tests exchange the same report resources, pagination metadata, validation details, job states, and safe error responses.

## ADDED Requirements

### Requirement: Versioned transport and serialization contract
Every MVP HTTP endpoint SHALL be rooted at `/api/v1`. JSON success responses containing one resource SHALL use `{ "data": <resource> }`; JSON collection responses SHALL use `{ "data": [<resource>], "page": <page-metadata> }`; successful operations with no representation SHALL return `204` without a body. Public identifiers SHALL be lowercase canonical UUID strings, calendar dates SHALL use `YYYY-MM-DD`, instants SHALL use RFC 3339 UTC with a `Z` suffix, and exact decimal values SHALL be base-10 JSON strings rather than binary JSON numbers. Response schemas MUST NOT expose credentials, provider payloads, unrestricted prompts or source content, internal object keys, or signed URLs outside the authorized download operation. Mutation schemas SHALL reject unknown fields with the standard validation response.

#### Scenario: Resource serialization is stable
- **WHEN** an authenticated owner retrieves a report resource containing identities, dates, timestamps, and exact metric values
- **THEN** the API returns the resource in the single-resource success envelope using the required canonical string formats
- **AND** the representation contains no internal storage key, provider detail, credential, or unrestricted untrusted content

#### Scenario: Mutation contains an unknown field
- **WHEN** a client submits a mutation body containing a property not declared by that operation's request schema
- **THEN** the API rejects the request with HTTP `422` and error code `validation_failed`
- **AND** a validation detail identifies the unknown property without echoing its value

### Requirement: Authenticated ownership boundary
Every report, source, import configuration, dataset, metric result, draft, analysis job, version, PDF export, retry, and download operation SHALL require an authenticated principal and SHALL authorize the target through its report owner. An unauthenticated request SHALL return HTTP `401` with code `unauthenticated`. A missing resource and a resource owned by another principal SHALL both return the same HTTP `404` response with code `resource_not_found`, and neither case may cause state mutation or background work.

#### Scenario: Unauthenticated request is rejected
- **WHEN** a request to an `/api/v1` resource has no valid authenticated principal
- **THEN** the API returns the standard error envelope with HTTP `401` and code `unauthenticated`
- **AND** it does not return protected resource data or start work

#### Scenario: Cross-owner lookup is indistinguishable from absence
- **WHEN** an authenticated principal requests a report-linked identifier owned by another principal
- **THEN** the API returns the same HTTP `404` `resource_not_found` shape used for an unknown identifier
- **AND** the response reveals no ownership, resource, job, version, source, or export metadata

### Requirement: Report and mutable-draft contracts
The report API SHALL provide `POST /api/v1/reports`, `GET /api/v1/reports`, `GET /api/v1/reports/{report_id}`, and `PATCH /api/v1/reports/{report_id}/draft`. Report creation SHALL accept `name`, `period` with inclusive `start_date` and `end_date`, and a non-empty `objectives` array. A report representation SHALL include `id`, `name`, `period`, `objectives`, derived `stage`, `active_draft`, current safe resource references, and `created_at` and `updated_at`. The active-draft representation SHALL include `id`, `revision`, editable narrative fields, labeled claims and limitations, current metric and analysis references, and timestamps. Draft updates SHALL accept `expected_revision` plus only editable fields, atomically increment the revision, and SHALL NOT create a version or permit direct mutation of source records or deterministic metrics.

#### Scenario: Valid report is created
- **WHEN** an authenticated principal posts a non-blank name, valid inclusive period, at least one non-blank objective, and an idempotency key
- **THEN** the API returns HTTP `201` with one owner-scoped report in stage `created` and an active draft at revision `1`
- **AND** no version, source, analysis job, or PDF export is created

#### Scenario: Report creation fields are invalid
- **WHEN** the name or an objective is blank, the objectives array is empty, or `end_date` precedes `start_date`
- **THEN** the API returns HTTP `422` with code `validation_failed` and one safe detail for each invalid field
- **AND** it creates no report or draft

#### Scenario: Draft revision is current
- **WHEN** the owner patches editable draft content using the current `expected_revision`
- **THEN** the API returns HTTP `200` with the saved content and the atomically incremented draft revision
- **AND** no immutable report version is created

#### Scenario: Draft revision is stale
- **WHEN** the owner patches a draft using an `expected_revision` that is no longer current
- **THEN** the API returns HTTP `409` with code `revision_conflict` and safe conflict metadata containing the expected and current revisions
- **AND** it preserves both the stored draft and the submitted client content without overwriting deterministic metrics or sources

### Requirement: Immutable source and import-review contracts
The source API SHALL provide `POST /api/v1/reports/{report_id}/sources/text`, `POST /api/v1/reports/{report_id}/sources/csv`, `GET /api/v1/reports/{report_id}/sources/{source_id}`, and `GET /api/v1/reports/{report_id}/sources/{source_id}/preview`. Text creation SHALL accept unchanged `content`; CSV creation SHALL use multipart form data with one file and SHALL enforce configured size, media-type, and UTF-8 encoding limits. Source representations SHALL expose safe provenance including `id`, `report_id`, `type`, byte size, checksum, media type or encoding, safe display filename when applicable, and creation time, while retaining any untrusted original filename only in an explicitly labeled metadata field. Preview responses SHALL be bounded and SHALL identify truncation, source-column ordinals and original headers, one-based data-record indexes, and labeled pasted claims without presenting them as validated metrics.

The import-review API SHALL provide `PUT /api/v1/reports/{report_id}/sources/{source_id}/import-configuration`, `POST .../validate`, and `POST .../confirm`. Configuration requests SHALL carry `expected_revision`, source-column-ordinal mappings, explicit normalization settings, and a normalization-policy version. Validation responses SHALL include the configuration revision, validation summary, preview identity, and all stable row or field issues. Confirmation SHALL accept only the exact validated revision, warning acknowledgement, and an idempotency key; it SHALL return the confirmed configuration and current canonical dataset identity only when no blocking error exists. Pasted text SHALL use the same explicit review-and-confirm gate without creating canonical metric input from its claims.

#### Scenario: CSV upload is accepted for review
- **WHEN** the owner uploads a CSV within configured size, content-type, and encoding limits
- **THEN** the API returns HTTP `201` with immutable source metadata and a bounded preview reference
- **AND** it does not expose an object key or treat any file content or filename as instructions

#### Scenario: CSV upload is rejected safely
- **WHEN** a CSV exceeds the size limit, has an unsupported media type, or cannot be decoded under the supported encoding contract
- **THEN** the API returns `payload_too_large`, `unsupported_media_type`, or `unsupported_encoding` with the corresponding HTTP status and safe details
- **AND** it creates no confirmed import, canonical dataset, job, public object reference, or partial current source

#### Scenario: Import validation returns blocking and warning details
- **WHEN** the owner validates a configuration containing mapping, value, row, period, duplicate, unmapped-column, or mixed-currency issues
- **THEN** the API returns a validation representation whose issues use the canonical issue codes, severities, fields, source-column ordinals, and one-based record indexes
- **AND** warnings remain distinguishable from errors and no original cell value is echoed in an error response

#### Scenario: Exact reviewed import is confirmed
- **WHEN** the owner confirms the current validated configuration revision with no errors and acknowledges its warnings
- **THEN** the API returns HTTP `200` with the confirmed configuration and canonical dataset identity bound to the reviewed source and policy revisions
- **AND** calculation is permitted only for that identity

#### Scenario: Invalid or stale import confirmation is rejected
- **WHEN** confirmation references a stale configuration revision, omits required warning acknowledgement, or validation contains blocking errors
- **THEN** the API returns `revision_conflict`, `warning_acknowledgement_required`, or `validation_failed` as applicable
- **AND** no configuration, dataset, or metric result from that request becomes current

### Requirement: Confirmed dataset and metric-result contracts
The dataset API SHALL provide `GET /api/v1/reports/{report_id}/datasets/current`, `GET /api/v1/reports/{report_id}/datasets/{dataset_id}`, `GET /api/v1/reports/{report_id}/datasets/{dataset_id}/rows`, and `GET /api/v1/reports/{report_id}/datasets/{dataset_id}/metrics`. A dataset representation SHALL include `id`, `report_id`, source and confirmed-configuration identities and revisions, canonical-data identity, row count, inclusive period, currencies present, normalization-policy version, confirmation provenance, and creation time. Dataset rows SHALL be owner-authorized and paginated; each row SHALL contain only canonical mapped values plus safe source ordinals and record indexes.

Every metric representation SHALL be a discriminated available or unavailable result. Both variants SHALL include metric identity and name, exact aggregate input totals as decimal strings, aggregation scope, period, applicable currency, represented currencies, canonical-data identity, calculation version, and calculation time. An available result SHALL set `availability` to `available` and include `value` and `unit`; an unavailable result SHALL set `availability` to `unavailable`, omit `value`, and include exactly one reason from `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, or `incomparable_period` plus safe supporting fields.

#### Scenario: Confirmed dataset detail is returned
- **WHEN** the owner requests a current or identified confirmed dataset
- **THEN** the API returns its reproducibility metadata and safe resource references
- **AND** the response does not include unmapped values, unrestricted original content, or another report's data

#### Scenario: Available metric is serialized exactly
- **WHEN** a requested metric has valid aggregate inputs and a positive denominator
- **THEN** the API returns `availability: available` with an exact decimal-string value, defined unit, aggregate inputs, scope, currency metadata, identities, and calculation version
- **AND** presentation rounding does not alter the stored or serialized result

#### Scenario: Unavailable metric is explicit
- **WHEN** a requested metric lacks an input, has a zero denominator, has invalid input, crosses currencies, or fails period comparability
- **THEN** the API returns `availability: unavailable` with exactly one stable reason and supporting fields
- **AND** it omits the numeric value and never substitutes zero, infinity, `NaN`, or an invented value

### Requirement: Persisted analysis-job contracts
The analysis API SHALL provide `POST /api/v1/reports/{report_id}/analysis-jobs`, `GET /api/v1/reports/{report_id}/analysis-jobs`, `GET /api/v1/reports/{report_id}/analysis-jobs/{job_id}`, and `POST .../{job_id}/retry`. Creation SHALL accept the confirmed dataset identity, metric-result-set identity, objectives revision, expected draft revision, and an idempotency key. An analysis-job representation SHALL include `id`, `report_id`, semantic input identity, state exactly `queued`, `running`, `succeeded`, or `failed`, attempt count, safe current-attempt timestamps, result reference when succeeded, sanitized failure when failed, and created and updated timestamps. A successful result representation SHALL contain `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`, observation-versus-hypothesis labels, model identifier, prompt version, request provenance, and metric references. Failure representations MUST use a stable safe failure code and message and MUST NOT include raw provider responses, prompts containing customer content, stack traces, or credentials.

#### Scenario: Analysis job is created idempotently
- **WHEN** the owner submits a valid current semantic input with an idempotency key while the report is `analysis_ready`
- **THEN** the API returns HTTP `202` with one persisted job in `queued` and the captured input identity
- **AND** an equivalent replay resolves to the same logical job

#### Scenario: Analysis job state is polled
- **WHEN** the owner retrieves a queued, running, succeeded, or failed analysis job
- **THEN** the API returns the authoritative persisted state, attempts, safe timestamps, and the result or sanitized failure appropriate to that state
- **AND** the client is not required to infer state from broker delivery or missing fields

#### Scenario: Failed analysis is retried for unchanged input
- **WHEN** the owner retries a failed job whose captured semantic input remains current
- **THEN** the API returns HTTP `202` with the same logical job identity and a new or requeued persisted attempt
- **AND** retry does not overwrite a newer draft result or create a duplicate current analysis

#### Scenario: Stale analysis retry is rejected
- **WHEN** the job's source, dataset, metrics, objectives, or relevant draft revision is no longer current
- **THEN** the API returns HTTP `409` with code `stale_input` and safe current identity metadata
- **AND** it does not queue work or attach the stale result

### Requirement: Immutable report-version contracts
The version API SHALL provide `POST /api/v1/reports/{report_id}/versions`, `GET /api/v1/reports/{report_id}/versions`, `GET /api/v1/reports/{report_id}/versions/{version_id}`, and `POST .../{version_id}/restore`. Version creation SHALL accept `expected_draft_revision` and an idempotency key. A version summary SHALL include `id`, `report_id`, sequential `version_number`, source draft identity and revision, template version, provenance summary, PDF export summary, and creation time. Version detail SHALL expose the immutable, owner-authorized report snapshot needed to reproduce the report and PDF, including report metadata, source checksums and safe references, confirmed-import identity, metric results, validated AI provenance, edited narrative, limitations, labeled claims, and template version, while excluding internal object keys and unrestricted source content. Restoration SHALL create a new mutable active draft from the selected snapshot and SHALL NOT alter history.

#### Scenario: Current draft is versioned once
- **WHEN** the owner submits the current draft revision with a new idempotency key
- **THEN** the API returns HTTP `201` with one sequential immutable version containing the required reproducibility snapshot
- **AND** an equivalent replay returns the same version without consuming another version number

#### Scenario: Stale draft cannot be versioned
- **WHEN** version creation references a draft revision that is not current
- **THEN** the API returns HTTP `409` with code `revision_conflict` and safe revision metadata
- **AND** it creates no partial version or sequence gap

#### Scenario: Historical version is restored as a draft
- **WHEN** the owner restores a selected version using an idempotency key and the expected current draft revision
- **THEN** the API returns the new active draft identity and revision populated from the immutable snapshot
- **AND** every existing version and PDF export remains unchanged

### Requirement: Version-bound PDF export contracts
The PDF API SHALL provide `POST /api/v1/reports/{report_id}/versions/{version_id}/pdf-exports`, `GET /api/v1/reports/{report_id}/versions/{version_id}/pdf-exports`, `GET /api/v1/reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}`, `POST .../{export_id}/retry`, and `GET .../{export_id}/download`. Creation SHALL accept the template version and an idempotency key. A PDF-export representation SHALL include `id`, `report_id`, `version_id`, immutable input identity, template version, state exactly `queued`, `running`, `succeeded`, or `failed`, attempt count, timestamps, safe file metadata and checksum only when succeeded, and sanitized failure only when failed. Retry SHALL remain bound to the same version and template input identity. Download SHALL authorize ownership at request time and SHALL return an authorized stream or redirect to a short-lived signed URL without returning credentials or using an object key as authorization.

#### Scenario: PDF export is queued for an immutable version
- **WHEN** the owner requests an export for a version and template using an idempotency key
- **THEN** the API returns HTTP `202` with one persisted export in `queued` bound to that exact version snapshot
- **AND** later draft changes cannot change its input

#### Scenario: Failed export is retried safely
- **WHEN** the owner retries a failed export
- **THEN** the API returns HTTP `202` with the same logical export and a new or requeued persisted attempt
- **AND** it creates no report version and does not bind the export to another version

#### Scenario: Completed export is downloaded by its owner
- **WHEN** the owner requests download for an export in `succeeded`
- **THEN** the API returns an authorized PDF stream or a redirect to a short-lived signed URL
- **AND** the JSON resource never exposes the internal object key or storage credentials

#### Scenario: Incomplete export cannot be downloaded
- **WHEN** download is requested for an export in `queued`, `running`, or `failed`
- **THEN** the API returns HTTP `409` with code `export_not_ready` and the current persisted export state
- **AND** it returns no signed URL or file bytes

### Requirement: Cursor pagination and deterministic collections
Every collection endpoint SHALL accept an optional opaque `cursor` and integer `limit`, defaulting to `25` and constrained to `1` through `100`. Collection responses SHALL include `page.limit`, `page.has_more`, and nullable `page.next_cursor`. Ordering SHALL be deterministic and documented per collection: reports, analysis jobs, and PDF exports by `(created_at DESC, id DESC)`; versions by `(version_number DESC, id DESC)`; and dataset rows by `(source_record_index ASC, row_id ASC)`. A cursor SHALL be scoped to the authenticated principal, route, parent resource, filters, ordering, and page boundary; clients MUST NOT need to parse it. Invalid, expired, mismatched, or tampered cursors SHALL return HTTP `400` with code `invalid_cursor`.

#### Scenario: First collection page has a continuation
- **WHEN** an owner requests a collection with more matching resources than the requested limit and no cursor
- **THEN** the API returns the first deterministically ordered page with `has_more: true` and an opaque `next_cursor`
- **AND** the page contains no resource owned by another principal

#### Scenario: Final collection page is explicit
- **WHEN** a valid cursor reaches the final page
- **THEN** the API returns the remaining resources with `has_more: false` and `next_cursor: null`
- **AND** replaying the same cursor yields the same page boundary while the referenced records remain available

#### Scenario: Cursor is invalid for the request
- **WHEN** a client changes the parent resource, filter, ordering, or owner context associated with a cursor or tampers with it
- **THEN** the API returns HTTP `400` with code `invalid_cursor`
- **AND** it does not reveal cursor internals or resources from the original scope

### Requirement: Idempotent mutation contract
Report creation, source attachment, import confirmation, analysis creation and retry, version creation and restoration, and PDF export creation and retry SHALL require an `Idempotency-Key` header. The key SHALL be a non-empty client-generated value within documented length and character limits and SHALL be scoped to the authenticated principal, operation, and parent resource. The server SHALL bind the key to a canonical request fingerprint. An equivalent replay SHALL return the original logical result and set `Idempotency-Replayed: true`; reuse with a different semantic request SHALL return HTTP `409` with code `idempotency_conflict`. Replays MUST NOT duplicate sources, confirmations, jobs, versions, attempts, exports, or side effects.

#### Scenario: Equivalent mutation is replayed
- **WHEN** the same owner repeats an idempotent mutation with the same key and semantically equivalent request
- **THEN** the API returns the original logical resource and indicates the replay in the response header
- **AND** no additional domain resource or background operation is created

#### Scenario: Idempotency key is reused for different input
- **WHEN** the same scoped key is submitted with a different canonical request fingerprint
- **THEN** the API returns HTTP `409` with code `idempotency_conflict`
- **AND** neither the original result nor the new request is mutated

### Requirement: Standard error and validation response
Every JSON error SHALL use `{ "error": { "code", "message", "request_id", "retryable", "details", "context" } }`. `code` SHALL be stable and machine-readable; `message` SHALL be safe for users; `request_id` SHALL be an opaque correlation identifier; `retryable` SHALL describe whether repeating the operation without user correction can reasonably succeed; `details` SHALL be an array; and `context` SHALL be an object containing only fields allowed for that error code. Each validation detail SHALL contain stable `code`, safe `message`, and `path` as an array of request-property names or indexes, with optional `canonical_field`, `source_column_ordinal`, and one-based `source_record_index`. Error responses MUST NOT echo submitted source values, filenames beyond a safely normalized display name, authorization tokens, signed URLs, credentials, stack traces, database errors, prompts, or provider payloads.

The stable baseline mapping SHALL include: `invalid_request` and `invalid_cursor` as HTTP `400`; `unauthenticated` as `401`; `resource_not_found` as `404`; `revision_conflict`, `idempotency_conflict`, `lifecycle_conflict`, `stale_input`, `warning_acknowledgement_required`, `job_not_retryable`, and `export_not_ready` as `409`; `payload_too_large` as `413`; `unsupported_media_type` and `unsupported_encoding` as `415`; `validation_failed` as `422`; `rate_limited` as `429`; `internal_error` as `500`; and `dependency_unavailable` as `503`. HTTP `429` and retryable `503` responses SHALL include `Retry-After`. Provider, worker, rendering, and storage failures that belong to a persisted job SHALL normally be represented by that job's `failed` state rather than leaked as request errors.

#### Scenario: Structural validation fails
- **WHEN** a request has multiple invalid fields
- **THEN** the API returns HTTP `422` with code `validation_failed` and one or more deterministic validation details using property paths
- **AND** the response omits submitted values and creates no partial resource

#### Scenario: Lifecycle gate rejects a validly shaped request
- **WHEN** a structurally valid request is not allowed in the report's current stage or job state
- **THEN** the API returns HTTP `409` with code `lifecycle_conflict`, `job_not_retryable`, or another specific conflict code and safe current-state context
- **AND** the client can render the conflict without inferring domain state from the message

#### Scenario: Dependency fails during a synchronous request
- **WHEN** a required dependency is temporarily unavailable before a persisted job or resource can be accepted
- **THEN** the API returns HTTP `503` with code `dependency_unavailable`, `retryable: true`, and `Retry-After`
- **AND** it sanitizes the underlying provider or infrastructure error

#### Scenario: Persisted background attempt fails
- **WHEN** an accepted analysis or PDF attempt later encounters a provider, rendering, or storage failure
- **THEN** polling returns the logical job in `failed` with a stable sanitized failure code and retryability
- **AND** the API does not convert that persisted outcome into a raw provider HTTP error

### Requirement: Contract publication and verification
The future backend implementation SHALL generate an OpenAPI document from the same validated request and response schemas used at runtime. The document SHALL describe every endpoint, status, request body, success schema, error envelope, enum, pagination field, idempotency header, revision field, upload limit category, and download response defined by this capability. Contract verification SHALL cover every resource family requested by the MVP: reports and drafts, sources and imports, datasets and metrics, analysis jobs, versions, and PDF exports. It SHALL also cover pagination boundaries, validation detail locations, owner-safe `404` behavior, revision and idempotency conflicts, all legal job states, decimal/date/time serialization, and sensitive-field exclusion.

#### Scenario: Generated OpenAPI matches runtime validation
- **WHEN** the backend contract suite exercises a declared valid and invalid payload for each mutation
- **THEN** runtime acceptance or rejection and response serialization conform to the generated OpenAPI schemas
- **AND** no hand-maintained duplicate schema is required to explain a different behavior

#### Scenario: Error taxonomy has contract coverage
- **WHEN** the contract suite enumerates the stable error-code baseline
- **THEN** each code has at least one applicable endpoint fixture asserting HTTP status, envelope fields, retryability, and allowed context
- **AND** redaction fixtures prove forbidden credentials, internal keys, provider payloads, and submitted source values are absent

#### Scenario: Issue-requested API surface is complete
- **WHEN** the implementation is reviewed against the API contract matrix
- **THEN** request and response schemas exist for reports, imports, datasets, analysis jobs, versions, and PDF exports
- **AND** standardized pagination, error codes, and validation responses are all represented by executable contract tests
