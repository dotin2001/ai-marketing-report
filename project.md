# AI Marketing Report Assistant

## Project Status

The repository is in the requirements-foundation stage. No application code or stage-specific infrastructure has been implemented. Each implementation stage will receive its own focused OpenSpec change rather than one umbrella change for the whole application.

## Product Goal

Build a web application that turns pasted marketing report content or a CSV upload into a validated, explainable, editable, versioned report. Deterministic Python code calculates metrics; AI interprets those results; immutable versions preserve provenance; PDFs are rendered from the exact saved version.

## MVP User Journey

1. Create a report with a name, reporting period, and analysis objectives.
2. Paste source content or upload a CSV file while preserving the original input.
3. Preview the parsed data, map supported columns, normalize values, and resolve blocking validation errors.
4. Calculate available KPIs in Python and run AI analysis as a background job.
5. Review metrics, charts, limitations, and AI narrative; edit narrative content and save a mutable draft.
6. create an immutable version and request PDF generation for that exact version.
7. Review version history, download completed PDFs, retry failed exports, or create a new draft from an older version.

## MVP Scope

- Pasted text and CSV input.
- One documented marketing CSV schema with user-correctable mapping.
- Preview, normalization, and field-level validation.
- Deterministic CTR, CPC, CPM, and CPL calculations when their inputs are available.
- AI-generated summary, findings, anomalies, recommendations, and data gaps.
- Editable report drafts, basic charts, one report layout, and one PDF template.
- Immutable version history and authorized PDF downloads.
- Persistent background-job status and safe retries.

## Non-goals

- Advertising-platform integrations, OCR, or arbitrary document extraction.
- Currency conversion, user-defined formulas, or unsupported KPI inference.
- Custom template builders or multiple PDF themes.
- Collaboration, comments, scheduled reporting, or automatic distribution.
- AI-generated arithmetic or invented source figures.

## Technology Baseline

| Area | Technology |
|---|---|
| Frontend | Next.js App Router, TypeScript |
| UI | Tailwind CSS, shadcn/ui |
| API | FastAPI, Pydantic |
| Processing | Python, pandas |
| Database | PostgreSQL |
| ORM and migrations | SQLAlchemy, Alembic |
| AI | OpenAI Python SDK, Responses API, Structured Outputs |
| Background work | Celery, Redis |
| PDF | Versioned HTML/CSS rendered with Playwright |
| File storage | S3-compatible object storage |

The OpenAI model is selected through `OPENAI_MODEL`. Model-specific options must be supported by the configured model or omitted. The implementation should use the current Python SDK Structured Outputs helper for the Responses API and Pydantic validation; official documentation must be rechecked when the AI integration is implemented.

## System Architecture

```text
+--------------------+          +----------------------+
| Next.js frontend   |  HTTPS   | FastAPI application  |
| forms, preview,    | <------> | authz, domain rules, |
| editor, history    |          | API and persistence  |
+--------------------+          +----------+-----------+
                                           |
                      +--------------------+--------------------+
                      |                    |                    |
                      v                    v                    v
             +----------------+   +----------------+   +----------------+
             | PostgreSQL     |   | S3-compatible  |   | Redis          |
             | metadata,      |   | original files |   | Celery broker  |
             | state, versions|   | and PDFs       |   |                |
             +----------------+   +----------------+   +-------+--------+
                                                                  |
                                                                  v
                                                        +----------------+
                                                        | Celery workers |
                                                        | pandas, OpenAI,|
                                                        | Playwright PDF |
                                                        +----------------+
```

PostgreSQL is authoritative for state. Redis delivers work but is not the job-status source of truth. Object storage holds binary originals and PDFs; PostgreSQL holds their ownership-aware references and metadata.

## Component Responsibilities

### Frontend

- Guides the user through report creation, import, mapping, validation, analysis, editing, versioning, export, and history.
- Polls or subscribes to persisted job status and presents explicit retry actions.
- Keeps unsaved edits separate from background results and does not manufacture domain state locally.

### FastAPI application

- Authenticates the caller and enforces report ownership on every operation.
- Validates API contracts, coordinates transactions, and applies report lifecycle rules.
- Creates idempotent jobs and versions, exposes status, and authorizes object downloads.
- Keeps provider credentials and internal storage details private.

### Processing layer

- Parses and normalizes CSV data with pandas.
- Produces validation issues and a confirmed canonical dataset.
- Calculates KPIs from aggregate inputs and records unavailable reasons.

### Celery workers

- Claim persisted queued jobs through transactional state transitions.
- Run AI analysis or PDF rendering using immutable or revision-checked inputs.
- Persist success or sanitized failure details and tolerate redelivery.

### Storage

- PostgreSQL stores report metadata, mappings, normalization settings, draft content, metrics, jobs, version snapshots, and export state.
- S3-compatible storage stores original CSV objects and generated PDF objects.

## Core Domain Model

- **User identity**: authenticated principal used for ownership. The concrete authentication provider remains a design decision; ownership enforcement is not optional.
- **Report**: owner-scoped UUID, name, inclusive reporting-period dates, one or more objectives, active-draft identity and revision, derived workflow stage, and created/updated timestamps. The end date cannot precede the start date.
- **Source**: immutable UUID and report-owner association; pasted-text or CSV type; creation time, byte size, checksum, media type or encoding; and either unchanged pasted content or an authorized object reference. CSV metadata retains the untrusted original filename separately from a safely normalized display filename.
- **Confirmed import configuration**: report/source identity, configuration revision and input revision, user-confirmed column mapping and normalization settings, validation summary, canonical-data identity or snapshot, confirmation timestamp, and provenance sufficient to reproduce the confirmed input.
- **Draft**: mutable identity, report owner, revision, objectives and narrative content, current metric/analysis references, labeled claims and limitations, and created/updated timestamps. Its revision is the compare-and-set boundary for optimistic saves.
- **Metric result**: immutable identity linked to the confirmed input; deterministic metric name, value and unit when available, input totals, aggregation scope, period, currency where applicable, calculation version, unavailable reason, and calculation timestamp.
- **Analysis result**: immutable identity linked to its logical job and semantic input identity; schema-validated `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`; observation-versus-hypothesis labels; model identifier, prompt version, request provenance, and creation timestamp.
- **Logical job and attempt**: owner/report association, job type, semantic input identity, idempotency key, persisted state, current result reference, and created/updated timestamps belong to the logical operation. Each attempt records its ordinal, queue/start/finish timestamps and sanitized failure details without exposing provider internals.
- **Report version**: owner-scoped immutable UUID and sequential version number created atomically from one exact draft revision. Its creation timestamp and snapshot preserve report metadata, source references and checksums, confirmed configuration and canonical-data identity, metric inputs/results, AI and request provenance, edited narrative, limitations, labeled claims, and template version.
- **Version-bound PDF export**: owner and immutable-version identity, template/input identity, idempotency key, logical state and persisted attempts, timestamps, and either sanitized failure details or an authorized generated-object reference, metadata, and checksum. Internal object keys are never public authorization tokens.

## Lifecycle and State Rules

The user-facing report stage is derived from persisted report, current-source confirmation, metric, job, draft, and version facts. It is separate from analysis-job and PDF-export states.

| Current stage | Event and gate | Resulting stage |
|---|---|---|
| `created` | Attach an immutable pasted or CSV source | `source_review` |
| `source_review` | Explicitly confirm the current source review or valid mapping/normalization configuration, then finish deterministic metrics | `analysis_ready` |
| `analysis_ready` | Accept one logical analysis job for the current semantic input | `analysis_pending` |
| `analysis_pending` | Attach a validated result only when its captured input identity is still current | `reviewing` |
| `analysis_pending` | Current analysis fails | `analysis_ready`, retaining the failed job and prior valid result |
| `analysis_pending` | Source, configuration, objectives, or relevant draft revision changes | Reject the late result as stale and return to `source_review` or `analysis_ready` according to whether confirmation remains valid |
| `reviewing` | Atomically version the current draft revision | `versioned` |
| `versioned` | Save a narrative-only edit or clone history into a new active draft | `reviewing` |
| `reviewing` or `versioned` | Change source, mapping, normalization, reporting period, or objectives in a way that invalidates analysis | `source_review` or `analysis_ready`, according to whether the current confirmation remains valid |

PDF queueing, running, success, failure, and retry never change the report stage because each export belongs to an immutable version. New inputs and drafts never remove or alter prior versions or their exports.

### Editing and invalidation

- Draft saves require the expected revision and atomically advance it. A stale revision produces a stable concurrency error and preserves both stored and submitted content; polling and recoverable failures must preserve unsaved local edits.
- Users may edit narrative content, objectives, and other permitted draft fields. Original sources and deterministic metric values are non-editable. Saving a draft never creates an immutable version.
- Analysis freshness uses a semantic identity containing the report, source checksum or identity, import-configuration revision, canonical-data identity, metric-result identity and calculation version, objectives revision, and relevant draft revision. A timestamp alone is insufficient.
- A worker may persist the outcome of a stale attempt, but it cannot attach that result as current or overwrite newer draft content. Changed semantic inputs require a new logical analysis operation.
- Versions and completed PDFs are immutable. Restoring an older version copies its snapshot into a new revisioned active draft rather than mutating, renumbering, or replacing history.

### Logical analysis and PDF jobs

Both logical job types use exactly `queued`, `running`, `succeeded`, and `failed`. PostgreSQL is authoritative for state and attempts; Redis/Celery only delivers work. Idempotency keys, database uniqueness, and transactional transitions make repeated clicks and broker redelivery safe. Attempts retain retry-specific timestamps and sanitized failures, while clients receive stable safe errors rather than provider details.

- An analysis operation binds to one confirmed semantic input identity and one metric result. Retry may add an attempt or safely requeue the failed logical job only while that identity remains unchanged; it cannot create duplicate current results, replace a prior valid result on failure, or overwrite newer work.
- A PDF operation binds to one immutable report version, snapshot input identity, and template version. Retry adds an attempt or safely requeues that same logical export; it cannot create a report version, switch versions, or render from a mutable draft.

## CSV and Metric Baseline

The MVP structured-data envelope is a comma-delimited CSV with one header record and one or more data records, decoded as UTF-8 with an optional byte-order mark. The seven fields below are the complete canonical schema. `date`, `campaign_name`, and `currency` are required dimensions; the four measures are optional columns, but at least one measure must be mapped. Once a measure is mapped, every data record must contain a valid value for it.

| Field | Presence | Canonical type | Unit / semantics | Normalization |
|---|---|---|---|---|
| `date` | Required | ISO calendar date | `YYYY-MM-DD`, without time or timezone | Accept an explicitly configured format or unambiguous ISO date; never infer from locale or runtime defaults |
| `campaign_name` | Required | Non-empty Unicode string | Campaign label | Remove surrounding whitespace only; an empty result is invalid |
| `currency` | Required | ISO 4217 alphabetic code | Row currency | Uppercase and validate against the versioned supported-code list |
| `impressions` | Optional column | Non-negative base-10 integer | Impression count | Accept a plain whole count; reject negative, fractional, boolean, unit-bearing, or non-finite values |
| `clicks` | Optional column | Non-negative base-10 integer | Click count | Accept a plain whole count; reject negative, fractional, boolean, unit-bearing, or non-finite values |
| `spend` | Optional column | Non-negative finite base-10 exact decimal | Major unit of the row currency | Parse without binary floating-point coercion or implicit scaling; reject symbols, percentages, booleans, and locale-dependent forms |
| `leads` | Optional column | Non-negative base-10 integer | Lead count | Accept a plain whole count; reject negative, fractional, boolean, unit-bearing, or non-finite values |

### Mapping, normalization, and confirmation

The import boundary keeps the original source immutable and untrusted. Processing follows this deterministic sequence:

1. Decode and parse the immutable source while identifying each source column by ordinal and original header and each data record by a one-based record index. Ordinals keep repeated header names distinct.
2. Apply an editable mapping revision. A source-column ordinal maps to at most one canonical field, and each canonical field receives at most one source column. Suggested mappings remain editable and never count as confirmation.
3. Normalize mapped values with a versioned policy, preserving each original value and its provenance. Missing mapped values are blocking errors; normalization never imputes, forward-fills, interpolates, silently drops a row, or substitutes zero.
4. Validate the mapping and normalized records against the inclusive report period. Unmapped source columns remain in the immutable original but are excluded from canonical data and calculation.
5. Derive the canonical-data identity from the canonical rows, source identity and checksum, mapping revision, normalization-policy revision, and report period.
6. Explicitly confirm only the exact error-free revision the owner reviewed, including its warnings. Calculation may use only that confirmed canonical-data identity.

Any behavior-affecting change to the source, mapping, normalization configuration or policy, or report period invalidates the previous confirmation, canonical-data identity, and derived metrics. The changed revision must be validated and explicitly confirmed again.

Dates that are ambiguous or invalid, unsupported currency codes, negative measures, fractional counts, non-finite values, currency or unit symbols, percentages, booleans, locale-dependent numeric forms, and blank cells in mapped fields are errors. A measure column that is not mapped is an absent KPI input rather than a row error, provided another supported measure is mapped.

### Validation issues and confirmation gate

Every validation issue has a stable machine-readable `code`, `severity` (`error` or `warning`), safe human-readable message, and, when applicable, canonical field, source-column ordinal, and one-based source-record index.

| Category | Stable codes | Severity and deterministic effect |
|---|---|---|
| Mapping and dataset shape | `missing_required_mapping`, `missing_measure_mapping`, `duplicate_mapping`, `empty_dataset` | Error; blocks confirmation and produces no current canonical dataset or metric result |
| Mapped values and period | `missing_value`, `invalid_date`, `ambiguous_date`, `blank_campaign_name`, `unsupported_currency`, `invalid_count`, `invalid_spend`, `negative_measure`, `out_of_period` | Error; blocks the entire revision, and no invalid row is silently dropped or partially calculated |
| Unmapped source column | `unmapped_column` | Warning; display and acknowledge it, preserve the source column in the immutable original, and exclude it from canonical data and arithmetic |
| Exact duplicate canonical row | `duplicate_row` | Warning identifying both record indexes; include both rows unless the user replaces or changes the source, because the system never silently deduplicates |
| Multiple currencies | `mixed_currency` | Warning; include all valid rows for non-monetary CTR, partition spend metrics by currency, and make a requested cross-currency spend result unavailable |

All errors block confirmation. Warnings are displayed and acknowledged but do not block it because their inclusion or exclusion behavior is fixed above. Confirmation persists the owner and report, source identity and checksum, mapping and normalization-policy revisions, validation summary and warning acknowledgement, canonical-data identity, row count, inclusive reporting period, currencies present, and confirmation time.

### Deterministic KPI results

Calculation sums canonical inputs within the requested scope before dividing once:

| KPI | Formula | Unit | Default scope |
|---|---|---|---|
| CTR | `aggregate clicks / aggregate impressions * 100` | `percent` | Whole confirmed report-period dataset, including multiple currency groups |
| CPC | `aggregate spend / aggregate clicks` | `<currency>/click` | One currency partition |
| CPM | `aggregate spend / aggregate impressions * 1000` | `<currency>/1000_impressions` | One currency partition |
| CPL | `aggregate spend / aggregate leads` | `<currency>/lead` | One currency partition |

The calculation context provides at least 28 significant decimal digits. Every available quotient that is non-terminating is serialized with at least 12 significant decimal digits. Exact aggregate numerator and denominator totals, canonical-data identity, calculation version, and calculation time are retained; presentation rounding is separate and never changes a stored result. Row-ratio averaging, intermediate display rounding, AI arithmetic, unsupported input inference, and invented substitutes are prohibited.

Every requested supported KPI produces an explicit result. An available result contains the metric name, decimal value, unit, exact aggregate inputs, aggregation scope, inclusive reporting period, applicable currency, canonical-data identity, calculation version, and calculation time. A zero numerator with a present positive denominator is an available value of zero.

An unavailable result contains the same identity, scope, period, input, and calculation-version provenance, omits the numeric value, and has exactly one primary reason: `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, or `incomparable_period`, plus supporting field or scope details. It never presents zero, infinity, `NaN`, or an invented value as a substitute. `invalid_input` prevents a current result from attaching even though confirmation ordinarily catches it first.

CTR may be report-wide across currencies because it has no monetary input, and its provenance lists the represented currencies. CPC, CPM, and CPL are calculated separately for each currency with sufficient inputs. A requested report-wide spend metric over multiple currencies is unavailable with `incompatible_currency`; spend is never summed across currencies, converted implicitly, or assigned a preferred currency.

Period comparison is available only when both results have equivalent durations and boundaries under the selected comparison policy and compatible metric definitions, calculation versions, mappings, normalization policies, aggregation scopes, and currency scopes. Otherwise it is unavailable with `incomparable_period`, identifies the mismatch, and cannot feed a deterministic or AI-generated comparative conclusion. Pasted claims, filenames, comments, metadata, and unmapped values remain unvalidated source material and never enter canonical totals or arithmetic.

## AI Contract

AI receives validated metrics, explicit limitations, report objectives, and bounded source excerpts or claims. Source text is delimited and treated as untrusted data, never as instructions. Computed values and user-provided claims are labeled separately.

Structured output contains:

- `summary`
- `findings`
- `anomalies`
- `recommendations`
- `data_gaps`

The backend validates the result with Pydantic before persistence or display. Analysis must distinguish direct observations from causal hypotheses, avoid unsupported period comparisons, and avoid inventing figures. Provider errors, refusals, incomplete responses, and schema failures produce a failed job that can be retried.

## MVP Acceptance Criteria

### Steps 1–3: create, import, and confirm

- **Step 1 — create:** An authenticated user can create an owner-scoped report only with a non-empty name, an inclusive period whose end is not before its start, and at least one objective. Success creates one revisioned draft in `created` without a version or job; invalid input returns stable field-level errors and creates nothing.
- **Step 2 — preserve and preview:** Pasted text is stored unchanged with provenance and checksum. A CSV within configured size, content-type, and encoding limits is stored immutably through the storage abstraction with safe filename handling and an authorized preview; rejected files create no confirmed import, job, or public object reference. Both source types are treated as untrusted data and enter `source_review`; pasted claims remain labeled rather than becoming validated metrics.
- **Step 3 — map, normalize, and confirm:** CSV preview supports user-correctable mapping to `date`, `campaign_name`, `currency`, `impressions`, `clicks`, `spend`, and `leads`. Required dimensions and at least one measure must be mapped; measures normalize to non-negative numbers and currencies to valid uppercase ISO 4217 codes. Missing/duplicate mappings, unmapped columns, bad rows, ambiguous dates, unsupported currencies, and mixed-currency risks are explicit warnings or blocking errors. Only explicit confirmation after blocking errors are resolved persists the configuration/canonical-data identity and permits analysis. Pasted text receives an equivalent explicit source-review confirmation gate.

### Step 4: calculate and analyze

- Deterministic Python calculates aggregate CTR, CPC, CPM, and CPL; it never averages row ratios. Missing, invalid, incompatible, or zero-denominator inputs yield an unavailable metric with a reason, never zero, infinity, `NaN`, or an invented substitute. Spend metrics stay within one ISO 4217 currency group, no conversion is implicit, and incompatible periods are not compared.
- An owner-authorized, persisted, idempotent logical analysis job captures the current semantic input and moves through the shared job states. AI receives only computed metrics, explicit limitations and objectives, plus bounded, delimited untrusted excerpts or labeled claims; AI does not perform arithmetic or invent figures.
- Success requires the structured output schema and persists model, prompt, request, and numeric-source provenance before attachment. Timeouts, refusals, incomplete or invalid schemas, and provider errors become explicit sanitized failures with retry. Retry remains bound to unchanged input, and a stale result may be recorded but cannot attach to or overwrite newer work.

### Steps 5–7: review, version, export, and reopen

- **Step 5 — review and edit:** The owner sees computed metrics/charts with units and availability, limitations and data gaps, editable narrative, labeled claims, and AI provenance. Narrative saves use the expected revision; conflicts do not overwrite content, and a successful draft save creates no version.
- **Step 6 — version and export:** An owner-authorized, idempotent transaction creates one sequential immutable version from the exact current draft revision with the complete reproducibility snapshot. PDF generation is a separate persisted logical job rendered only from that version and template. Later draft changes cannot alter the saved version or completed PDF; failed export retry targets the same version without creating another.
- **Step 7 — history and restoration:** The owner receives ordered immutable history with creation/provenance summaries and persisted PDF status. Completed PDFs download only through an authorized backend response or short-lived signed URL. Retry remains bound to the selected historical version, and restoring history creates a new revisioned active draft while every historical version and PDF remains unchanged.

## Version and PDF Invariants

Each immutable report version preserves:

- Report metadata, reporting period, exact source draft revision, and sequential version identity.
- Source references and checksums.
- Confirmed mappings, normalization settings, validation summary, and canonical-data identity.
- Calculated metrics, inputs, scopes, currencies, calculation version, and availability metadata.
- Validated AI analysis, user-edited narrative content, limitations, and labeled claims.
- AI model identifier, prompt version, and request provenance.
- Report template version.
- Creation timestamp.

PDF export is a separate version-bound logical operation. Rendering consumes only the version snapshot; a failed export leaves the version intact, and export retry targets the same version without creating or switching a report version.

## Access Control

All user-visible resources inherit ownership from the report. The backend must verify the authenticated principal for reads, writes, jobs, version access, and downloads. Object keys are not authorization tokens. Downloads use a short-lived signed URL or an authorized backend response.

The concrete authentication mechanism must be selected before backend implementation. Until then, APIs should depend on an authenticated-principal interface so ownership rules do not depend on a specific provider.

## Versioned API Contract

The public MVP API is rooted at `/api/v1`. The OpenSpec capability is normative until the backend exists; Stage 2 must implement strict Pydantic request and response models and generate OpenAPI 3.1 from those same runtime models rather than maintaining a separate hand-written schema.

### Envelopes and scalar serialization

- A single JSON resource uses `{ "data": <resource> }`.
- A JSON collection uses `{ "data": [<resource>], "page": { "limit", "has_more", "next_cursor" } }`.
- A successful operation with no representation returns `204` with no body.
- Every JSON error uses `{ "error": { "code", "message", "request_id", "retryable", "details", "context" } }`.
- Public identifiers are canonical lowercase UUID strings. Calendar dates are `YYYY-MM-DD`; instants are RFC 3339 UTC strings with a `Z` suffix.
- Exact decimals and exact metric input totals are base-10 JSON strings. Revisions, attempt ordinals, version numbers, and other counters are positive JSON integers, except that `expected_revision: 0` explicitly means that no prior import configuration exists.
- Checksums use `{ "algorithm": "sha256", "value": "<lowercase-digest>" }`. Enums are lowercase snake-case strings fixed by the v1 schema.
- A nullable field is present as JSON `null` only where its schema declares nullability; otherwise an absent optional value is omitted. Clients ignore unknown response fields for additive compatibility, but mutation schemas reject unknown request fields with `422 validation_failed`.

All response models are ownership-safe views, never ORM models. General JSON responses must not expose credentials, authorization tokens, raw provider payloads, database errors, internal object keys, unrestricted prompts, unrestricted source content, or signed URLs. An authorized PDF download may return a `303` with a short-lived signed location, but that location is not part of a general resource representation.

### Endpoint matrix

Paths in this table are relative to `/api/v1`. Nested paths retain `report_id` and, where relevant, `version_id` even when the child identifier is globally unique so owner authorization and parent consistency remain explicit and testable. Every operation requires an authenticated principal and authorizes through the report owner. An unknown identifier and a cross-owner identifier both return the same `404 resource_not_found` shape and neither starts work nor mutates state.

| Method and path | Request | Success | Repetition/concurrency contract |
|---|---|---|---|
| `POST /reports` | `CreateReportRequest` | `201 ReportDetail` | Required idempotency key |
| `GET /reports` | `PageQuery` | `200 Page<ReportSummary>` | None |
| `GET /reports/{report_id}` | None | `200 ReportDetail` | None |
| `PATCH /reports/{report_id}/draft` | `UpdateDraftRequest` | `200 DraftDetail` | Required expected revision; idempotency key optional |
| `POST /reports/{report_id}/sources/text` | `CreateTextSourceRequest` | `201 SourceDetail` | Required idempotency key |
| `POST /reports/{report_id}/sources/csv` | Multipart `file` | `201 SourceDetail` | Required idempotency key |
| `GET /reports/{report_id}/sources/{source_id}` | None | `200 SourceDetail` | None |
| `GET /reports/{report_id}/sources/{source_id}/preview` | `PreviewQuery` | `200 SourcePreview` | None |
| `PUT /reports/{report_id}/sources/{source_id}/import-configuration` | `PutImportConfigurationRequest` | `200 ImportConfiguration` | Required expected revision; idempotency key optional |
| `POST /reports/{report_id}/sources/{source_id}/import-configuration/validate` | `ValidateImportRequest` | `200 ImportValidation` | Bound to source and configuration revisions |
| `POST /reports/{report_id}/sources/{source_id}/import-configuration/confirm` | `ConfirmImportRequest` | `200 ConfirmedImport` | Required idempotency key and exact reviewed revision |
| `POST /reports/{report_id}/sources/{source_id}/review-confirmation` | `ConfirmTextReviewRequest` | `200 ConfirmedSourceReview` | Required idempotency key and exact review revision |
| `GET /reports/{report_id}/datasets/current` | None | `200 DatasetDetail` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}` | None | `200 DatasetDetail` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}/rows` | `PageQuery` | `200 Page<CanonicalRow>` | None |
| `GET /reports/{report_id}/datasets/{dataset_id}/metrics` | `MetricQuery` | `200 MetricResultSet` | None |
| `POST /reports/{report_id}/analysis-jobs` | `CreateAnalysisJobRequest` | `202 AnalysisJob` | Required idempotency key and expected draft revision |
| `GET /reports/{report_id}/analysis-jobs` | `PageQuery` | `200 Page<AnalysisJobSummary>` | None |
| `GET /reports/{report_id}/analysis-jobs/{job_id}` | None | `200 AnalysisJobDetail` | None |
| `POST /reports/{report_id}/analysis-jobs/{job_id}/retry` | `RetryAnalysisJobRequest` | `202 AnalysisJobDetail` | Required idempotency key and unchanged semantic input |
| `POST /reports/{report_id}/versions` | `CreateVersionRequest` | `201 VersionDetail` | Required idempotency key and expected draft revision |
| `GET /reports/{report_id}/versions` | `PageQuery` | `200 Page<VersionSummary>` | None |
| `GET /reports/{report_id}/versions/{version_id}` | None | `200 VersionDetail` | None |
| `POST /reports/{report_id}/versions/{version_id}/restore` | `RestoreVersionRequest` | `200 DraftDetail` | Required idempotency key and expected current draft revision |
| `POST /reports/{report_id}/versions/{version_id}/pdf-exports` | `CreatePdfExportRequest` | `202 PdfExportDetail` | Required idempotency key |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports` | `PageQuery` | `200 Page<PdfExportSummary>` | None |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}` | None | `200 PdfExportDetail` | None |
| `POST /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/retry` | `RetryPdfExportRequest` | `202 PdfExportDetail` | Required idempotency key and same immutable version/input identity |
| `GET /reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/download` | None | `200 application/pdf` or `303` short-lived signed location | Owner is reauthorized at download time |

The MVP has no general `DELETE`, bulk mutation, arbitrary sort, or unrestricted source-content endpoint. Job polling reads persisted PostgreSQL state rather than broker state. A text source uses its explicit review-confirmation endpoint and its claims never create a canonical structured dataset.

### Strict request schemas and mutation boundaries

All mutation models reject undeclared fields. Accepted content is bounded by reviewed configuration and is never silently truncated. Expected revisions are command data, not optional transport hints; ETags may be added later as an optimization but do not replace the v1 revision fields.

| Request schema | Required public fields and constraints |
|---|---|
| `CreateReportRequest` | Trimmed `name` of 1–200 Unicode characters; inclusive `period.start_date` and `period.end_date` with end not before start; `objectives` containing 1–20 trimmed strings of 1–2,000 characters each |
| `UpdateDraftRequest` | `expected_revision >= 1` and at least one of `objectives`, structured `narrative`, `limitations`, or labeled `claims`; never accepts owner, stage, source rows, deterministic metrics, analysis provenance, version identity, or job/export state |
| `CreateTextSourceRequest` | Unchanged Unicode `content` within the configured source-byte limit and an optional safe display label; the content is stored as untrusted data and never interpreted as instructions |
| CSV multipart upload | Exactly one non-empty `file` within the configured byte limit; declared and detected CSV media type; UTF-8 with optional BOM; untrusted original filename retained separately from its normalized display filename |
| `PutImportConfigurationRequest` | `expected_revision >= 0`, where `0` means no prior configuration; unique mappings of `{ source_column_ordinal >= 0, canonical_field }`; explicit normalization settings, including date format for non-ISO dates; `normalization_policy_version` |
| `ValidateImportRequest` | Exact `configuration_revision` and source preview identity |
| `ConfirmImportRequest` | Exact configuration revision, validation identity, canonical-data preview identity, and the complete acknowledged warning-code/identity set |
| `ConfirmTextReviewRequest` | Exact source review revision and explicit acknowledgement that extracted figures remain unvalidated claims |
| `CreateAnalysisJobRequest` | Current `dataset_id`, `canonical_data_identity`, `metric_result_set_id`, `objectives_revision`, and `expected_draft_revision` |
| `RetryAnalysisJobRequest` | Expected semantic input identity and last observed attempt ordinal |
| `CreateVersionRequest` | `expected_draft_revision` for the exact active draft snapshot |
| `RestoreVersionRequest` | `expected_current_draft_revision`; restoration copies the selected immutable snapshot into a new active draft |
| `CreatePdfExportRequest` | Explicit supported `template_version`; the parent path supplies the immutable report version |
| `RetryPdfExportRequest` | Expected immutable input identity and last observed attempt ordinal; the version and template binding cannot change |

Ordinal mapping is one-to-one: a source-column ordinal maps to at most one canonical field and each canonical field receives at most one ordinal. Suggested mappings remain editable and unconfirmed. Source attachment creates an immutable source; later review/configuration commands refer to it rather than modifying its content. Confirmation succeeds only for the exact error-free revision the owner reviewed and acknowledged.

Draft narrative follows the five AI sections: `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`. Items use stable identities, bounded editable text where permitted, classification as `observation`, `hypothesis`, or `user_claim` where applicable, and metric/claim references. Mutable requests cannot set deterministic values, provenance, ownership, lifecycle state, immutable snapshot fields, or internal storage/provider fields. Pasted text, filenames, comments, and claims remain labeled unvalidated source material and cannot enter canonical rows or metric inputs.

### Summary, detail, and discriminated response models

List responses stay shallow; detail responses add only the owner-authorized provenance needed for their operation. Database models are never serialized directly.

| Response model | Required public field groups |
|---|---|
| `ReportSummary` | `id`, `name`, `period`, derived `stage`, active draft `{ id, revision }`, safe current source/dataset/analysis references when present, latest version `{ id, version_number }` when present, `created_at`, `updated_at` |
| `ReportDetail` | Summary fields plus `objectives`, `active_draft: DraftDetail`, current source/import/dataset/metric/job summaries, and available-operation indicators derived from persisted state |
| `DraftDetail` | `id`, `report_id`, positive `revision`, objectives, structured editable narrative, labeled claims, limitations, current metric-result-set and analysis-result references, timestamps |
| `SourceDetail` | `id`, `report_id`, type, byte size, checksum, media type or encoding, safe display filename and separately labeled untrusted original filename for CSV, review/configuration revision, `created_at`; never an object key |
| `SourcePreview` | Source and preview identities; bounded columns and rows or bounded text excerpt; original headers; source-column ordinals and one-based record indexes; `truncated`; returned/total counts when known; mapping suggestions labeled unconfirmed; claims labeled unvalidated |
| `ImportConfiguration` | Configuration/report/source identities, revision, mappings, normalization settings and policy version, latest validation identity/summary, status `editing`, `validated`, or `confirmed`, timestamps |
| `ImportValidation` | Configuration and preview identities, deterministic summary counts, ordered validation issues, canonical-data preview identity only when errors are absent, validation time |
| `ConfirmedImport` | Configuration/source identities and revisions, warning acknowledgement, canonical dataset identity, row count, inclusive period, currencies, confirming principal reference, confirmation time |
| `ConfirmedSourceReview` | Source/review identities and revision, explicit unvalidated-claim acknowledgement, confirming principal reference, confirmation time; no canonical dataset or metric identity |
| `DatasetDetail` | `id`, `report_id`, source and confirmed-configuration identities/revisions, canonical-data identity, row count, inclusive period, currencies, normalization-policy version, confirmation provenance, `created_at` |
| `CanonicalRow` | Stable row identity, one-based source record index, mapped canonical values only, and source-column ordinal provenance; never unmapped values |
| `MetricResultSet` | Dataset/canonical identity, calculation version/time, ordered discriminated metric results, scope metadata |
| `AnalysisJobSummary` | `id`, `report_id`, semantic input identity, persisted state, attempt count, result presence, safe failure summary only when failed, timestamps |
| `AnalysisJobDetail` | Summary plus captured dataset/metric/objective/draft identities, current-attempt timestamps, ordered safe attempt summaries, and validated analysis result only when succeeded |
| `VersionSummary` | `id`, `report_id`, sequential `version_number`, source draft identity/revision, template version, provenance summary, latest PDF export summary, `created_at` |
| `VersionDetail` | Summary plus immutable render snapshot: report metadata, safe source references/checksums, confirmed-import identity, metrics, validated AI provenance/output, edited narrative, limitations, labeled claims, and template version; never internal storage references or unrestricted source content |
| `PdfExportSummary` | `id`, report/version identities, immutable template/input identity, persisted state, attempt count, safe succeeded/failed indicator, timestamps |
| `PdfExportDetail` | Summary plus attempt timestamps/summaries and either succeeded file metadata `{ filename, content_type, byte_size, checksum, download_available }` or sanitized failure |

`MetricResult` is discriminated by `availability`. Both variants contain metric identity/name, exact aggregate input totals as decimal strings, aggregation scope, inclusive period, applicable currency, represented currencies, canonical-data identity, calculation version, and calculation time. `available` requires `value` and `unit` and forbids `reason`. `unavailable` requires exactly one reason from `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, or `incomparable_period`, includes only safe supporting fields, and forbids `value`. It never substitutes zero, infinity, `NaN`, or an invented figure; a genuine zero numerator with a positive denominator remains an available value of `"0"`.

Analysis jobs and PDF exports use exactly `queued`, `running`, `succeeded`, and `failed`; clients do not infer state from missing fields or broker delivery. A succeeded analysis result contains the five structured sections, observation-versus-hypothesis labels, model identifier, prompt version, request provenance, and metric references. A `JobFailure` exposes only stable `code`, safe `message`, and `retryable`. Analysis failure codes are `provider_timeout`, `provider_refusal`, `provider_unavailable`, `incomplete_response`, `invalid_structured_output`, and `stale_result`; PDF failure codes are `render_failed`, `storage_unavailable`, `invalid_snapshot`, and `artifact_validation_failed`. Raw provider responses, customer-bearing prompts, stack traces, credentials, database errors, and internal storage data are forbidden.

### Cursor pagination

`PageQuery` accepts optional `cursor` and `limit`. `limit` defaults to `25`, has a minimum of `1`, and a maximum of `100`. Every collection returns:

```json
{
  "data": [],
  "page": {
    "limit": 25,
    "has_more": false,
    "next_cursor": null
  }
}
```

Cursors are opaque, integrity-protected keyset cursors. Their server-side payload binds the authenticated principal, route, parent identifiers, normalized filters, fixed ordering, and last keyset boundary. A cursor never grants authorization by itself and clients never parse it. Implementations fetch `limit + 1` rows to derive `has_more` without a default total-count query.

| Collection | Deterministic ordering |
|---|---|
| Reports | `(created_at DESC, id DESC)` |
| Analysis jobs | `(created_at DESC, id DESC)` |
| PDF exports | `(created_at DESC, id DESC)` |
| Report versions | `(version_number DESC, id DESC)` |
| Immutable dataset rows | `(source_record_index ASC, row_id ASC)` |

The first page omits `cursor`. A non-final page has `has_more: true` and a non-null opaque `next_cursor`. A final page returns remaining items with `has_more: false` and `next_cursor: null`; an empty collection has the same final-page metadata with an empty `data` array. Replaying the same valid cursor produces the same keyset boundary while referenced rows remain available. Invalid, expired, tampered, filter-mismatched, parent-mismatched, route-mismatched, ordering-mismatched, or cross-owner cursors return `400 invalid_cursor` with no cursor internals or original-scope resource data. Offset pagination, client-selected sorting, and default total counts are outside the MVP.

### Idempotency and optimistic concurrency

`Idempotency-Key` contains 1–128 visible ASCII characters matching `[A-Za-z0-9._:-]+`. It is required for report creation, source attachment, import or text-review confirmation, analysis creation and retry, version creation and restoration, and PDF export creation and retry. Draft and import-configuration updates always require their expected revision; they may additionally accept a key.

The key's uniqueness scope is authenticated principal, operation, parent resource, and key. After strict validation, the server computes a cryptographic fingerprint of the canonical semantic command rather than comparing raw JSON bytes or storing the raw body. The idempotency record and logical domain mutation are persisted atomically in one transaction, and the compact record remains for the lifetime of its logical result in the MVP.

- The same scoped key and same canonical fingerprint returns the original status and representation and sets `Idempotency-Replayed: true`.
- The same scoped key with different semantic input returns `409 idempotency_conflict` and changes neither request result.
- Replays cannot create additional reports, sources, confirmations, logical jobs, versions, exports, attempts, sequence gaps, or side effects.
- Analysis and PDF commands resolve to the persisted logical job or export; an individual worker attempt is not the idempotent result. A retry command has its own key, while database uniqueness and legal state transitions ensure repeated HTTP delivery or broker redelivery creates at most one intended new attempt.

Mutable drafts and import configurations use compare-and-set semantics. The domain transaction verifies the submitted `expected_revision`, performs the mutation, and increments the revision atomically. A stale value returns `409 revision_conflict` with only allowlisted expected/current metadata and leaves stored and submitted content unmerged. Analysis creation also captures the expected draft revision and full semantic input identity; analysis retry requires that identity to remain current. Version creation snapshots exactly `expected_draft_revision`, restoration compares `expected_current_draft_revision`, and PDF creation/retry stays bound to the immutable version, template, and input identity. Process-local locks, timestamp-only freshness, and quickly expired keys do not satisfy these guarantees.

### Standard errors and HTTP mapping

Every JSON error has exactly this stable outer shape:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "The request contains invalid fields.",
    "request_id": "opaque-correlation-id",
    "retryable": false,
    "details": [],
    "context": {}
  }
}
```

`code` is machine-readable, `message` is safe for users, `request_id` is an opaque correlation identifier, and `retryable` says whether repeating without user correction can reasonably succeed. `details` is always an array and `context` is always an object. Context is constructed only after owner authorization and contains only the allowlisted fields below.

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
| `export_not_ready` | 409 | true only while queued/running; false when failed | Current export state |
| `payload_too_large` | 413 | false | Maximum accepted bytes |
| `unsupported_media_type` | 415 | false | Allowed media types |
| `unsupported_encoding` | 415 | false | Allowed encodings |
| `validation_failed` | 422 | false | Empty; field locations are in `details` |
| `rate_limited` | 429 | true | Rate-limit scope; `Retry-After` is authoritative |
| `internal_error` | 500 | false | Empty |
| `dependency_unavailable` | 503 | true | Empty; `Retry-After` is required |

Missing resources and resources owned by another principal are deliberately indistinguishable: both return the same `404 resource_not_found` status, shape, message class, and resource-type-only context. Authorization runs before validation or conflict construction, so a foreign resource never produces revision, lifecycle, job, source, version, export, or ownership metadata.

Framework-default validation bodies are not public API responses. A synchronous dependency failure before a resource or job can be accepted may use sanitized `503 dependency_unavailable`. A provider, worker, renderer, or storage failure after acceptance belongs in the persisted job/export `failed` representation; it is not translated into a later raw provider HTTP error.

### Validation details, domain issues, and redaction

A structural request validation detail has stable `code`, safe `message`, and `path`. `path` is an array of JSON property names and zero-based array indexes, such as `["objectives", 0]`; it identifies the schema location without echoing the rejected value. Multiple details use deterministic schema/path ordering and a failed mutation creates no partial resource.

Import validation issues are domain results and keep their source locations distinct from request paths. Every issue has stable `code`, `severity` (`error` or `warning`), safe `message`, and, where applicable, `canonical_field`, zero-based `source_column_ordinal`, and one-based `source_record_index`. Duplicate-row warnings identify both one-based record indexes using safe location metadata. Import errors block confirmation; warnings remain visible and require acknowledgement according to the confirmation contract.

Revision, lifecycle, stale-input, acknowledgement, job, and export conflicts put only the fields allowed by the error table in `error.context`. This makes expected/current revisions, safe semantic identities, or current states distinguishable without placing submitted content into messages or details. Validation field information stays in `details`, not unrestricted context.

Error and validation serialization must never include submitted cell/source values, raw pasted content, an unsafe original filename, bearer/cookie/authorization tokens, credentials, signed URLs, internal object keys, stack traces, SQL or database errors, unrestricted prompts, or provider request/response payloads. A filename may appear only as a separately labeled safely normalized display name where that schema explicitly permits it. Logs follow the same customer-data and secret redaction boundary.

## Delivery Sequence

Complete these stages sequentially. For every stage after project instructions, create, review, validate, and approve a focused OpenSpec change before implementation. Do not combine database, backend, and frontend implementation into one change.

### Stage 0: Project instructions

- Establish repository guidance and project context.
- Keep application code and stage-specific infrastructure out of this stage.
- Use `AGENTS.md` and `project.md` as context for every later OpenSpec change.

### Stage 1: Database and local infrastructure

- Create and approve a dedicated database and local-infrastructure OpenSpec change.
- Add PostgreSQL, Redis, and S3-compatible local services.
- Scaffold SQLAlchemy and Alembic.
- Implement the initial schema, constraints, migrations, and migration verification.

### Stage 2: Backend foundation

- Create and approve a dedicated backend OpenSpec change using the database contracts from Stage 1.
- Scaffold FastAPI, configuration, authentication boundary, ownership enforcement, repositories, and error contracts.
- Implement report, source, draft, job, version, and export APIs in dependency order.

### Stage 3: Data import and calculation

- Implement source preservation, CSV parsing, preview, mapping, normalization, validation, and deterministic KPIs.
- Complete focused unit and PostgreSQL integration tests.

### Stage 4: Background jobs and AI

- Add Celery orchestration, persisted job transitions, retries, and idempotency.
- Add the Responses API adapter, prompt versioning, Structured Outputs validation, and deterministic provider fakes.

### Stage 5: Versioning and PDF

- Implement atomic immutable-version creation, history, draft cloning, Playwright rendering, storage, downloads, and retry behavior.

### Stage 6: Frontend

- Create and approve a dedicated frontend OpenSpec change after the required backend contracts are stable.
- Scaffold Next.js, Tailwind CSS, and shadcn/ui.
- Build the guided workflow, validation UI, analysis status, report editor, charts, version history, and download states.

### Stage 7: Integrated verification

- Run migration, unit, integration, worker, PDF, and browser suites.
- Verify KPI correctness, version immutability, safe repeated clicks and retries, ownership isolation, and the complete browser journey.

### Downstream verification matrix

Each focused stage owns the evidence for its behavior and must name applicable lifecycle scenarios and exact verification commands in its proposal and tasks. This allocation does not authorize an umbrella implementation; stages remain sequential, and live OpenAI or object-storage checks remain opt-in while deterministic fakes and fixed snapshots run by default.

| Owning focused stage | Required evidence before handoff |
|---|---|
| Database and local infrastructure | PostgreSQL integration tests for UUID, foreign-key, and check constraints; ownership filters; revisions; legal job transitions; unique idempotency; immutable snapshots; and migration upgrade verification |
| Backend foundation/API | Contract tests for field validation, stable error codes, owner authorization on every resource, optimistic draft conflicts, persisted-state serialization, and repeated-click idempotency |
| Data import and calculation | Unit and integration tests for original preservation; upload size/type/encoding; previews; mappings; confirmation gates; invalid rows; ISO 4217 normalization; aggregate formulas; zero denominators; missing inputs; mixed currencies; and period comparability |
| Background jobs and AI | Deterministic fake-provider and worker tests for queue/run/succeed/fail transitions, redelivery, retry, stale input, bounded untrusted context, structured-result validation, refusals/timeouts, and AI provenance |
| Versioning and PDF | Integration and fixed-snapshot rendering tests for atomic version numbers, complete immutable snapshots, repeated version clicks, exact-version PDF content, export failure/retry, authorized download, and draft cloning |
| Frontend | Component and browser tests for explicit loading, empty, validation, job, failure, unavailable, retry, and conflict states; keyboard/focus behavior; unsaved-edit preservation; and the seven-step journey |
| Integrated verification | PostgreSQL-backed and browser evidence for create/import/confirm/analyze/edit/version/export/history, ownership isolation, and safe repeated delivery, clicks, and retries |

### Stage 2 API contract verification

The focused Stage 2 backend change must create contract suites grouped by resource family. Each suite uses runtime requests and serialized responses—not documentation snapshots alone—and verifies owner authorization before metadata-bearing validation or conflict handling.

| Suite | Required evidence before backend handoff |
|---|---|
| Reports and drafts | Valid idempotent creation; every structural/field constraint; summary/detail and derived-stage serialization; unauthenticated and owner-safe `404`; successful and stale expected-revision saves; protected-field/unknown-field rejection; replay/key conflict; no implicit source, job, version, or export |
| Sources and imports | Text and CSV creation/replay; immutable source behavior; size/type/encoding failures; safe/untrusted filename separation; bounded previews; ordinal mapping structure; validation issue severities and locations; exact revision and warning acknowledgement; stale/lifecycle conflicts; cross-owner isolation; no source-value, object-key, or unrestricted-content disclosure |
| Datasets and metrics | Current/detail/row owner authorization; deterministic row pagination; canonical-only row fields; exact decimal strings; available/unavailable discriminated-union exclusivity; aggregate input, currency, scope, period, identity, and calculation provenance; no unmapped or foreign data |
| Analysis jobs | `202` idempotent creation; structural and lifecycle validation; captured semantic input and expected revision; all four persisted states; result shape and each sanitized failure code; equivalent replay/key conflict; unchanged-input retry and retry-attempt deduplication; stale retry rejection; cross-owner isolation; no prompt, provider payload, credential, or stack trace |
| Versions | `201` sequential immutable snapshot; structural and stale-revision rejection; equivalent replay without duplicate or sequence gap; owner isolation; deterministic ordering; immutable detail provenance; restoration creates a new revisioned draft and preserves all history; no internal storage reference or unrestricted source content |
| PDF exports | `202` idempotent version-bound creation; structural/lifecycle checks; all four persisted states; same-version/input retry and attempt deduplication; succeeded file metadata; failed sanitized metadata; not-ready download; owner-authorized stream/redirect; cross-owner isolation; no object key, credential, or signed URL in JSON |

Every suite must assert the single-resource or collection envelope, declared status, exact scalar encodings, unknown-field rejection, and relevant error context allowlist. Tests must also prove failed or replayed commands do not create partial resources, duplicate side effects, or work for another owner.

The Stage 2 change must also create cross-cutting suites with this evidence:

| Suite | Required evidence |
|---|---|
| Pagination | Default `25`, minimum `1`, maximum `100`, and out-of-range validation; deterministic first/middle/final and empty pages; correct `has_more`/`next_cursor`; inserts before a keyset boundary; replayed boundaries; tampered, expired, route/filter/parent/order-mismatched, and cross-owner cursors all yield safe `400 invalid_cursor` |
| Errors and redaction | Every baseline code has an applicable endpoint fixture asserting its one status, retryability rule, request ID, deterministic detail shape, and exact context allowlist; owner-safe `404`; `Retry-After` for `429` and retryable `503`; no submitted source value, unsafe filename, credential, token, signed URL, object key, stack trace, database error, unrestricted prompt, or provider payload |
| Idempotency and concurrency | Key syntax/scope; canonical-equivalent replay and replay header; different-input conflict; transaction rollback safety; current and stale expected revisions; repeated HTTP and worker delivery cannot duplicate logical resources, attempts, sequences, or side effects |
| Generated OpenAPI | Every operation, status, header, request media type, download response, enum, revision, pagination field, error envelope, and upload-limit category references the runtime model; valid/invalid examples agree with runtime acceptance; actual response instances validate; no undocumented FastAPI/framework-default validation or error body appears |

Schema snapshots alone are insufficient: the generated OpenAPI document and runtime behavior must be exercised together. Browser coverage complements but does not replace these focused fixtures.

The Stage 2 backend change is responsible for creating the named test modules and making both exact commands pass before handoff:

```sh
cd backend && python -m pytest tests/contract/api/test_reports_and_drafts.py tests/contract/api/test_sources_and_imports.py tests/contract/api/test_datasets_and_metrics.py tests/contract/api/test_analysis_jobs.py tests/contract/api/test_versions_and_pdf_exports.py
cd backend && python -m pytest tests/contract/api/test_errors_pagination_idempotency.py tests/contract/api/test_openapi_contract.py
```

These are future backend gates. This requirements-foundation change does not create `backend/`, install dependencies, or claim that the commands can run before Stage 2 implementation.

### Stage 3 import fixture matrix

The later data-import and calculation change must create fixtures covering this matrix. Each fixture is tied to at least one named scenario in the `marketing-data-import-and-kpi-calculation` capability.

| Fixture | Expected evidence | Capability scenario(s) |
|---|---|---|
| Plain UTF-8 and UTF-8 with BOM | Both parse as comma-delimited CSVs with the same ordinal/header identities and canonical values | Supported CSV is available for mapping |
| Header only | `empty_dataset` error; confirmation and calculation are blocked | Header-only dataset is rejected |
| Repeated header names | Columns remain distinct by ordinal plus original header | Supported CSV is available for mapping; Duplicate mapping is rejected |
| Incorrect suggested mapping corrected by the owner | Preview and validation use only the corrected mapping revision | Suggested mapping is corrected before confirmation |
| One valid row exercising all seven canonical fields | ISO date, trimmed Unicode campaign, uppercase ISO 4217 currency, whole counts, and exact-decimal spend retain source ordinal/record provenance | Valid row is normalized canonically |
| Blank required dimension and blank mapped measure cells | One `missing_value` or `blank_campaign_name` error per affected field/record; no imputation or zero substitution | Mapped measure cell is missing; Blocking errors prevent confirmation |
| Fractional or negative count, negative or symbolic spend, boolean, `NaN`, infinity, percentage, and locale-dependent number | Stable blocking field/record issues; no coercion or silent row removal | Invalid measure is blocked |
| Ambiguous, invalid, and out-of-period dates | `ambiguous_date`, `invalid_date`, or `out_of_period` error; no locale guess; confirmation blocked | Ambiguous date is blocked; Date falls outside the reporting period |
| Two exact duplicate canonical rows | `duplicate_row` warning names both record indexes and both rows remain included after acknowledgement | Exact duplicate canonical row is detected; Warnings are acknowledged |
| Unsupported currency | `unsupported_currency` error; affected revision cannot become current | Unsupported currency is blocked |
| Supported mixed currencies | `mixed_currency` warning; report-wide CTR includes valid rows, spend metrics partition by currency | Mixed-currency dataset produces per-currency results; CTR spans currencies without combining money |
| Unmapped extra numeric column | `unmapped_column` warning; original is retained but the values are excluded from canonical totals | Unmapped source columns remain explicit; Unmapped numeric column is excluded |
| Confirmed source, mapping, normalization, or period revised | Prior confirmation and metrics cease to be current; revalidation and explicit reconfirmation are required | Confirmed mapping changes |

### Stage 3 KPI golden-case matrix

Fixtures use a pinned fixture calculation version, `kpi-v1`, and assert exact input totals as decimal strings where applicable. A future version may use another identifier, but every fixture and result must name it.

| Golden case | Exact aggregate inputs | Scope / version | Expected result |
|---|---|---|---|
| Aggregate ratio differs from row-ratio average | clicks `2`, impressions `110` from rows `1/10` and `1/100` | report / `kpi-v1` | CTR available as `1.818181818181...`, unit `percent`, serialized with at least 12 significant digits |
| Valid zero numerator | clicks `0`, impressions `100` | report / `kpi-v1` | CTR available as exact `0`, unit `percent` |
| Missing impressions | clicks `10`, spend `25`; impressions absent | report and currency:USD / `kpi-v1` | CTR and CPM unavailable with `missing_input`; each omits value and identifies `impressions` |
| Missing clicks | impressions `1000`, spend `25`; clicks absent | report and currency:USD / `kpi-v1` | CTR and CPC unavailable with `missing_input`; each omits value and identifies `clicks` |
| Missing spend | impressions `1000`, clicks `10`, leads `2`; spend absent | currency:USD / `kpi-v1` | CPC, CPM, and CPL unavailable with `missing_input`; each omits value and identifies `spend` |
| Missing leads | spend `25`; leads absent | currency:USD / `kpi-v1` | CPL unavailable with `missing_input`; value omitted and `leads` identified |
| Zero impressions denominator | impressions `0`, clicks `0`, spend `25` | report and currency:USD / `kpi-v1` | CTR and CPM unavailable with `zero_denominator`; zero total retained, values omitted |
| Zero clicks denominator | clicks `0`, impressions `100`, spend `25` | currency:USD / `kpi-v1` | CPC unavailable with `zero_denominator`; zero total retained and value omitted; CTR remains available as `0 percent` |
| Zero leads denominator | leads `0`, spend `25` | currency:USD / `kpi-v1` | CPL unavailable with `zero_denominator`; zero total retained and value omitted |
| Exact decimal spend | spend `0.10 + 0.20 = 0.30`, clicks `3` | currency:USD / `kpi-v1` | CPC available as exact `0.10`, unit `USD/click`; no binary-float artifact |
| Non-terminating quotient | spend `1`, impressions `3` | currency:USD / `kpi-v1` | CPM available as `333.333333333...`, unit `USD/1000_impressions`, at least 12 significant digits |
| Deterministic rerun | Same canonical identity and the totals from the exact-decimal case | currency:USD / `kpi-v1` | Repeated runs have identical availability, totals, unit, scope, currency, and serialized `0.10` value |
| Per-currency spend | USD: spend `30`, clicks `3`; EUR: spend `20`, clicks `4` | currency:USD and currency:EUR / `kpi-v1` | CPC results are `10 USD/click` and `5 EUR/click`, each using only its partition |
| Cross-currency spend request | USD spend `30` plus EUR spend `20`; clicks `7` | report / `kpi-v1` | Report-wide CPC unavailable with `incompatible_currency`; no combined spend total or numeric value |
| Compatible periods | Period A: clicks `10`, impressions `100`, CTR `10 percent`; period B: clicks `20`, impressions `100`, CTR `20 percent`; both 7 days with matching boundary policy and contracts | comparison:report / `kpi-v1` | Comparison available from the stored `10` and `20` values with unit `percent`, retaining both result identities and periods |
| Incompatible periods or contracts | The same `10 percent` and `20 percent` CTR inputs over 7 and 8 days, or with any differing definition, version, mapping/policy, scope, or currency | comparison:report / `kpi-v1` | Comparison unavailable with `incomparable_period`; value omitted and incompatible attributes identified |

The future Stage 3 data-import/calculation change must create the named suites and make both exact commands pass before handoff:

```sh
cd backend && python -m pytest tests/unit/processing/test_csv_import.py tests/unit/processing/test_normalization.py tests/unit/processing/test_kpi_calculation.py
cd backend && python -m pytest tests/integration/processing/test_confirmed_import.py
```

## Environment Configuration

Expected configuration groups include:

- Application: environment, public origins, API base URL, signing or authentication settings.
- PostgreSQL: application and migration database URLs.
- Redis/Celery: broker and worker settings.
- Object storage: endpoint, region, bucket, access credentials, path-style option, and signed-URL lifetime.
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`, request timeout, and prompt version.
- PDF: renderer timeout, template version, and browser executable settings where needed.

Secrets belong in local untracked environment files or a deployment secret manager. A committed example file may contain names and safe defaults but never credentials.

## Highest-priority Verification

1. KPI correctness across aggregate ratios, zero denominators, missing values, and currencies.
2. Database-enforced immutable versions and ownership isolation.
3. Idempotent version creation, job delivery, repeated clicks, and retries.
4. PDF generation from the exact version snapshot.
5. The main browser journey from report creation through history and download.
