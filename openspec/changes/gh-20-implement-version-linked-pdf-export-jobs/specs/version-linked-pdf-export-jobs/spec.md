## Purpose

Owners can request, monitor, retry, and download PDF generation for an exact saved report version while preserving its immutable content and a durable record of every attempt.

## ADDED Requirements

### Requirement: Export requests bind to an authorized immutable version
The system SHALL accept PDF export creation only for a saved version owned by the caller. It SHALL bind the logical export to that version's snapshot identity and supported template version, persist it before background execution, and return the established `202` export representation. Repeated equivalent requests SHALL resolve to the same logical export; a conflicting idempotency-key reuse SHALL fail without side effects. Export creation SHALL NOT create or modify a report version or mutable draft.

#### Scenario: Owner queues a saved version
- **WHEN** an owner requests an export using the saved version's template and a valid idempotency key
- **THEN** one `queued` export and its first attempt are persisted for that version and snapshot identity
- **AND** the response identifies that same version and immutable input

#### Scenario: A request is repeated
- **WHEN** the owner repeats an equivalent request or two equivalent requests race
- **THEN** both resolve to one logical export and no additional attempt or report version is created

#### Scenario: Version is unavailable to the caller
- **WHEN** a caller targets a missing or another owner's report or version
- **THEN** the operation returns an owner-safe `404 resource_not_found` and creates no export or background work

### Requirement: Execution uses only saved version content
Every export attempt SHALL render the exact saved version and its bound template, validate the PDF, upload it through private object storage, and mark success only after a matching generated asset is durably linked to the same version and export. Later draft, source, metric, or analysis changes SHALL NOT change the output input. Broker redelivery and concurrent execution SHALL NOT produce conflicting successful assets or state transitions.

#### Scenario: Saved version is exported after later edits
- **WHEN** an export runs after the active draft or current report inputs change
- **THEN** the PDF content comes solely from the selected immutable version snapshot and template
- **AND** the completed export links one verified PDF asset to that version

#### Scenario: Worker delivery repeats
- **WHEN** the same queued or completed attempt is delivered more than once
- **THEN** at most one worker claims the attempt and at most one matching asset becomes the completed export

### Requirement: Failure preserves the version and supports safe retry
The system SHALL persist rendering, invalid-snapshot, artifact-validation, storage, and timeout failures as safe `failed` export outcomes with attempt timestamps and approved failure codes. A failed export SHALL leave its report version unchanged and contain no downloadable asset. A retryable failed export SHALL be requeued only for the same version, snapshot identity, and template, with a new persisted attempt and an idempotent retry command; a stale ordinal, mismatched input, or nonretryable state SHALL fail safely.

#### Scenario: Rendering or upload fails
- **WHEN** rendering, validation, or storage fails after an attempt is accepted
- **THEN** the export and attempt reach `failed` with a sanitized reason and no downloadable PDF
- **AND** the saved report version remains available and unchanged

#### Scenario: Owner retries a failed export
- **WHEN** the owner retries a retryable failed export with its current attempt ordinal and immutable input identity
- **THEN** the same export gains exactly one queued attempt and can complete against the same saved version
- **AND** no additional report version or logical export is created

#### Scenario: Retry command is replayed or races
- **WHEN** an equivalent retry command is delivered again or concurrently
- **THEN** it resolves to the same intended attempt without incrementing the attempt count again

### Requirement: Status and download stay owner scoped
The system SHALL provide version-scoped export list and detail responses with persisted state, attempts, safe file metadata on success, and sanitized failure on failure. Lists SHALL use owner-bound opaque keyset pagination. A download SHALL reauthorize the report, version, and export and provide the completed PDF through the established private delivery path; pending or failed exports SHALL return `409 export_not_ready`. JSON SHALL NOT expose internal object keys, signed URLs, credentials, raw source content, or provider details.

#### Scenario: Owner checks export progress
- **WHEN** the owner lists exports or retrieves one export detail
- **THEN** the response reflects durable `queued`, `running`, `succeeded`, or `failed` state and safe attempt information

#### Scenario: Owner downloads completed output
- **WHEN** the owner requests download of a succeeded export bound to the requested version
- **THEN** the authorized PDF bytes are returned with safe file metadata

#### Scenario: Export is unavailable for download
- **WHEN** download is requested for a queued, running, or failed export
- **THEN** the API returns `409 export_not_ready` with its persisted state and no PDF bytes
