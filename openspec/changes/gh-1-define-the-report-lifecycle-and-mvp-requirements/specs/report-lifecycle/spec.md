## Purpose

Define the authoritative lifecycle, field, editing, job, versioning, export, authorization, and acceptance contracts for the seven-step marketing-report MVP journey.

## ADDED Requirements

### Requirement: Owned report aggregate and workflow state
The system SHALL represent each report as an owner-scoped aggregate with a UUID, owner identity, name, inclusive reporting-period start and end dates, one or more analysis objectives, an active draft identity and revision, created and updated timestamps, and a workflow stage. The reporting-period end date MUST NOT precede its start date. The exposed workflow stage SHALL be derived from persisted report, source-confirmation, metric, job, draft, and version facts using the stages `created`, `source_review`, `analysis_ready`, `analysis_pending`, `reviewing`, and `versioned` so a single job status cannot erase the rest of the report state.

#### Scenario: MVP step 1 creates a report
- **WHEN** an authenticated user supplies a valid name, reporting period, and at least one analysis objective
- **THEN** the system creates an owned report and revisioned active draft in the `created` stage
- **AND** the system returns the stored fields without creating a version or background job

#### Scenario: Invalid reporting period is rejected
- **WHEN** a user supplies a reporting-period end date earlier than its start date
- **THEN** the system rejects creation with a stable validation error and field-level details
- **AND** the system creates no report or draft

#### Scenario: Report stage advances from persisted facts
- **WHEN** the current source is confirmed, analysis is requested, a current analysis succeeds, the draft is edited, or a version is created
- **THEN** the system exposes the corresponding `analysis_ready`, `analysis_pending`, `reviewing`, or `versioned` stage
- **AND** a failed analysis returns the current input to `analysis_ready` while retaining the failed job outcome

#### Scenario: A later draft change does not alter history
- **WHEN** a report in `versioned` receives a narrative edit or a new source or import configuration
- **THEN** the active draft moves to `reviewing` for a narrative-only edit or `source_review` for an input change
- **AND** every existing version and version-bound export remains unchanged

### Requirement: Original source preservation and provenance
The system SHALL accept pasted text and CSV uploads as immutable report sources. Each source SHALL retain its source type, report ownership, creation time, byte size, checksum, media type or encoding metadata, and either the original pasted content or an authorized object-storage reference; CSV sources SHALL also retain a safely normalized display filename while the original filename remains untrusted metadata. Uploaded and pasted content MUST be treated as data rather than instructions and MUST NOT be logged as unrestricted application or provider output.

#### Scenario: MVP step 2 preserves pasted text
- **WHEN** the owner pastes marketing report content into a report
- **THEN** the system stores the original text unchanged with source provenance and a checksum
- **AND** the report enters `source_review` without treating instructions inside the text as executable or authoritative

#### Scenario: MVP step 2 preserves a valid CSV upload
- **WHEN** the owner uploads a CSV within the configured size limit using a supported content type and encoding
- **THEN** the system stores the original object through the storage abstraction and persists its checksum and metadata
- **AND** the system exposes an authorized preview path without exposing internal object keys or public storage URLs

#### Scenario: Invalid upload is rejected safely
- **WHEN** an upload exceeds the size limit or fails CSV type or encoding validation
- **THEN** the system rejects it with a stable validation error
- **AND** the system does not create a confirmed import, background job, or public object reference

### Requirement: Preview, mapping, normalization, and confirmation gate
For a CSV source, the system SHALL provide a preview and user-correctable mapping to `date`, `campaign_name`, `currency`, `impressions`, `clicks`, `spend`, and `leads`. `date`, `campaign_name`, and `currency` MUST be mapped, at least one supported measure MUST be mapped, provided measures MUST normalize to non-negative numeric values, and currency values MUST normalize to valid uppercase ISO 4217 codes before confirmation. The system SHALL report missing or duplicate mappings, unmapped source columns, invalid rows, ambiguous or invalid dates, unsupported currencies, and mixed-currency aggregation risk, distinguishing blocking errors from non-blocking warnings. For pasted text, the system SHALL provide a source review that keeps pasted claims distinguishable from validated computed metrics. Analysis MUST NOT start until the current source review or CSV mapping and normalization configuration is explicitly confirmed.

#### Scenario: MVP step 3 confirms valid CSV data
- **WHEN** the owner maps all required dimensions, maps at least one supported measure, resolves blocking row and normalization errors, and explicitly confirms the preview
- **THEN** the system persists the mapping, normalization settings, validation summary, canonical-data identity, confirmation time, and input revision
- **AND** the report can advance to deterministic metric calculation and `analysis_ready`

#### Scenario: Blocking validation prevents confirmation
- **WHEN** required dimensions or every supported measure are missing, a provided measure is invalid or negative, a date is ambiguous or invalid, or a currency is unsupported
- **THEN** the system keeps the report in `source_review` and identifies each blocking issue by field or row where applicable
- **AND** analysis cannot be queued

#### Scenario: Extra columns and multiple currencies remain explicit
- **WHEN** a valid CSV contains unmapped extra columns or more than one supported currency
- **THEN** the system reports those conditions before confirmation
- **AND** it excludes unmapped columns from calculations and prevents cross-currency spend aggregation rather than silently combining currencies

#### Scenario: Pasted claims remain unvalidated claims
- **WHEN** a pasted-text source contains figures or causal statements that were not computed from a confirmed canonical dataset
- **THEN** the system labels them as user-provided claims in preview and downstream context
- **AND** it does not present them as validated metrics

### Requirement: Deterministic metrics and comparability
The system SHALL calculate metrics from confirmed canonical data using deterministic code. It SHALL calculate `CTR` as aggregate clicks divided by aggregate impressions times 100, `CPC` as aggregate spend divided by aggregate clicks, `CPM` as aggregate spend divided by aggregate impressions times 1000, and `CPL` as aggregate spend divided by aggregate leads. Ratios MUST use aggregate numerators and denominators rather than averaged row-level ratios. Every metric result SHALL retain its name, value and unit when available, input totals, aggregation scope, period, currency where applicable, calculation version, and an explicit unavailable reason when an input is missing, invalid, incompatible, or has a zero denominator. Spend-based metrics MUST be separated by currency, and period comparisons MUST be omitted unless periods and data definitions are compatible.

#### Scenario: MVP step 4 calculates aggregate ratios
- **WHEN** a confirmed dataset contains valid inputs for a supported metric
- **THEN** the system calculates the metric from aggregate numerator and denominator totals
- **AND** records the inputs, aggregation scope, unit, currency where applicable, and calculation version

#### Scenario: Missing input or zero denominator is unavailable
- **WHEN** a metric input is absent or its aggregate denominator is zero
- **THEN** the system records the metric as unavailable with a specific reason
- **AND** it never returns zero, infinity, `NaN`, or an invented substitute as the metric value

#### Scenario: Mixed currencies are not combined
- **WHEN** confirmed data contains spend in multiple currencies
- **THEN** the system calculates each spend-based metric only within a single currency group or marks a requested cross-currency result unavailable
- **AND** it performs no implicit conversion

#### Scenario: Incompatible periods are not compared
- **WHEN** requested comparison periods differ incompatibly in duration, boundaries, mapping, or metric definition
- **THEN** the system reports the comparison as unavailable with the incompatibility reason
- **AND** neither deterministic output nor AI narrative states a comparative conclusion

### Requirement: Persisted analysis job lifecycle and validated AI result
The system SHALL run AI analysis as an owner-authorized persisted logical job whose state is exactly `queued`, `running`, `succeeded`, or `failed`. An analysis job SHALL identify the report, confirmed input revision, metric-result identity, draft revision used for objectives and context, idempotency key, attempt information, timestamps, and either a validated result reference or a sanitized failure. The AI request SHALL include only computed metrics, explicit limitations, objectives, and bounded source excerpts or labeled claims; it MUST delimit source content as untrusted data. A successful result SHALL be schema-validated and contain `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`, plus model identifier, prompt version, request provenance, and distinctions between observations and hypotheses. The system MUST NOT attach a result to a newer incompatible input or draft revision.

#### Scenario: MVP step 4 queues one logical analysis
- **WHEN** the owner requests analysis for an `analysis_ready` report using an idempotency key
- **THEN** the system persists one logical job in `queued`, advances the report to `analysis_pending`, and schedules work using the confirmed input identity
- **AND** a repeated equivalent request resolves to the same logical operation rather than creating conflicting jobs

#### Scenario: Analysis succeeds for the current input
- **WHEN** a worker validates a complete structured response for the job's still-current input identity
- **THEN** the system transitions the job to `succeeded`, persists the validated result and AI provenance, attaches it to the active draft, and advances the report to `reviewing`
- **AND** every numeric observation remains traceable to a computed metric or explicitly labeled pasted claim

#### Scenario: Analysis fails explicitly
- **WHEN** the provider times out, refuses, returns an incomplete response, fails schema validation, or produces another provider error
- **THEN** the system transitions the job to `failed`, stores only a sanitized error, and exposes a retry action
- **AND** the report returns to `analysis_ready` without replacing a prior valid result or inventing narrative content

#### Scenario: Stale analysis result is not attached
- **WHEN** the source, confirmed mapping, objectives, or relevant draft revision changes after an analysis job was queued
- **THEN** the worker may record the attempt outcome but MUST NOT attach its result as current or overwrite newer draft content
- **AND** the report requires analysis for the new input identity before that result can be current

#### Scenario: Analysis retry preserves one logical operation
- **WHEN** the owner retries a failed analysis without changing its input identity
- **THEN** the system records a new attempt or safely requeues the failed logical job
- **AND** retry does not create duplicate current results or overwrite a newer draft result

### Requirement: Review and optimistic draft editing
The system SHALL present current deterministic metrics, metric availability reasons, charts derived from computed data, explicit limitations, AI narrative, AI provenance, and labeled pasted claims for review. Users SHALL be able to edit narrative content but MUST NOT directly edit deterministic metric values or immutable source records. Saving the mutable draft SHALL require the expected draft revision and increment the revision atomically; it MUST NOT create an immutable report version. Polling and recoverable failures MUST preserve unsaved local edits until the user saves or discards them.

#### Scenario: MVP step 5 reviews current results
- **WHEN** the owner opens a report with a current successful analysis
- **THEN** the system displays metrics and charts with units and availability, limitations and data gaps, editable narrative, and model and prompt provenance
- **AND** observations, hypotheses, pasted claims, and computed metrics remain distinguishable

#### Scenario: Narrative edit saves a new draft revision
- **WHEN** the owner submits narrative edits using the current expected revision
- **THEN** the system saves the edits and advances the draft revision atomically
- **AND** no immutable version is created

#### Scenario: Concurrent draft update is rejected
- **WHEN** a user attempts to save against a stale draft revision
- **THEN** the system rejects the update with a stable concurrency error and the current revision
- **AND** it does not silently overwrite either the stored draft or the user's submitted content

#### Scenario: Computed metrics cannot be manually overwritten
- **WHEN** a draft update attempts to replace deterministic metric values or mutate an original source
- **THEN** the system rejects or ignores the prohibited fields according to the API contract
- **AND** the persisted computed results and source provenance remain unchanged

### Requirement: Immutable report version creation
The system SHALL create a sequential immutable version from one exact active-draft revision in an atomic, owner-authorized operation. The version SHALL contain the report metadata and reporting period; source references and checksums; confirmed mapping, normalization, validation, and canonical-data identity; metric values, units, inputs, scopes, currencies, calculation version, and unavailable reasons; AI output and provenance; user-edited narrative; limitations and labeled claims; report-template version; version number; and creation time. Repeated equivalent version requests MUST be idempotent, and saving or editing a draft MUST NOT implicitly create a version.

#### Scenario: MVP step 6 saves an immutable version
- **WHEN** the owner requests a version from the current draft revision using an idempotency key
- **THEN** the system atomically creates one sequential version containing every required reproducibility field and advances the report to `versioned`
- **AND** later source, configuration, analysis, or draft changes cannot alter the version

#### Scenario: Repeated version request is idempotent
- **WHEN** the same version-creation request is delivered or clicked more than once
- **THEN** the system returns the same version identity or one equivalent successful result
- **AND** it does not create duplicate version numbers or conflicting snapshots

#### Scenario: Stale draft cannot be versioned as current
- **WHEN** version creation references a draft revision that is no longer current
- **THEN** the system rejects it with a stable concurrency error
- **AND** no partial or incorrectly numbered version is created

### Requirement: Version-bound PDF job lifecycle
The system SHALL render PDF output only from one immutable report-version snapshot. Each logical PDF export and its persisted job SHALL identify the owner, report version, template version, input identity, idempotency key, attempt information, timestamps, and exactly one state from `queued`, `running`, `succeeded`, or `failed`. A successful export SHALL retain authorized object metadata and checksum; a failure SHALL retain only a sanitized error. Retrying an export MUST continue to target the same immutable version and MUST NOT create a report version.

#### Scenario: MVP step 6 queues PDF generation for the saved version
- **WHEN** the owner requests PDF export for an immutable version
- **THEN** the system persists one version-bound logical export in `queued` and schedules rendering from that exact snapshot and template version
- **AND** draft changes made after the request cannot affect the rendered content

#### Scenario: PDF succeeds from the exact version
- **WHEN** rendering completes for the version snapshot
- **THEN** the system transitions the export job to `succeeded` and stores the PDF object reference, checksum, completion metadata, and version association
- **AND** the downloadable PDF corresponds to that version's content and provenance

#### Scenario: PDF failure preserves the version
- **WHEN** rendering or object storage fails
- **THEN** the system transitions the export job to `failed`, records a sanitized failure, and leaves the immutable version intact
- **AND** it exposes retry for the same version

#### Scenario: PDF retry does not duplicate a version
- **WHEN** the owner retries a failed export or repeats an equivalent export request
- **THEN** the system records a new attempt or safely requeues the same logical version-bound export
- **AND** it does not create a new report version or bind the result to a different version

### Requirement: Version history, download, and draft restoration
The system SHALL provide the owner with ordered immutable version history, each version's provenance summary, and its current PDF export status. A completed PDF SHALL be downloadable only through an authorized backend response or short-lived signed URL. The owner SHALL be able to create a new active draft from an older version; this operation MUST create a new mutable draft identity or revision and MUST NOT mutate, renumber, or replace any historical version.

#### Scenario: MVP step 7 reopens history
- **WHEN** the owner opens a report's version history
- **THEN** the system returns the ordered versions with creation metadata, provenance summary, and PDF status
- **AND** historical content is read from immutable snapshots rather than reconstructed from the current draft

#### Scenario: Owner downloads a completed PDF
- **WHEN** the owner requests a completed version's PDF
- **THEN** the system authorizes access against report ownership and returns an authorized stream or short-lived signed download
- **AND** it does not expose raw object-storage credentials or treat the object key as authorization

#### Scenario: Owner retries a failed historical export
- **WHEN** the owner retries a failed PDF shown in version history
- **THEN** the retry targets the same historical version and exposes persisted queued, running, succeeded, or failed status
- **AND** repeated polling or retry clicks do not create another report version

#### Scenario: Owner creates a draft from an older version
- **WHEN** the owner selects an older version as the basis for continued work
- **THEN** the system creates a new mutable active draft populated from that snapshot and protected by a new revision
- **AND** the selected version, later versions, and their PDFs remain immutable

### Requirement: Ownership authorization and explicit operational states
Every read, write, confirmation, calculation, job request, retry, draft save, version operation, export, history request, and download SHALL be authorized against the report owner. The persisted database state, not the message broker or browser, SHALL be authoritative for report stage, job state, attempts, and results. APIs and user interfaces SHALL expose loading, empty, validation, queued, running, succeeded, failed, conflict, unavailable, and retry states without leaking provider details, credentials, internal object keys, unrestricted source content, or another owner's resource existence.

#### Scenario: Cross-owner access is denied
- **WHEN** an authenticated user requests any report-linked resource owned by another user
- **THEN** the system denies the operation without returning the resource, signed URL, source contents, job details, version, or PDF
- **AND** no background work or state mutation occurs

#### Scenario: Persisted job state survives broker redelivery
- **WHEN** a worker receives the same job delivery more than once
- **THEN** transactional state and uniqueness constraints permit only legal idempotent transitions for the logical operation
- **AND** duplicate delivery cannot create conflicting results, versions, or exports

#### Scenario: Client observes explicit recoverable state
- **WHEN** a report, analysis, or PDF operation is empty, validating, queued, running, failed, unavailable, or in conflict
- **THEN** the API returns a stable machine-readable state or error code with safe human-readable context
- **AND** the client can render the corresponding state without manufacturing domain status locally
