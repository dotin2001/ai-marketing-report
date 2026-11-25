## Purpose

Provide durable, owner-authorized analysis-job submission and observation so asynchronous work remains traceable and safe across repeated requests, worker delivery, and dependency failures.

## ADDED Requirements

### Requirement: Analysis jobs are accepted with persistent identity
The system SHALL accept analysis-job creation only for an owner-authorized report with current confirmed data, current deterministic metrics, a matching expected draft revision, and a complete semantic input identity. It SHALL return HTTP `202` with the persistent logical job UUID and `queued` state. Equivalent idempotency-key replay SHALL return that same logical job without another attempt; conflicting key reuse SHALL return `409 idempotency_conflict`.

#### Scenario: Current input is queued
- **WHEN** the owner submits valid current analysis inputs and an unused idempotency key
- **THEN** the API returns a persistent job ID in `queued` state with one queued attempt and its queue timestamp

#### Scenario: Repeated submission
- **WHEN** the owner repeats the equivalent command with the same scoped key
- **THEN** the API returns the same logical job with replay indication and creates no additional attempt

#### Scenario: Input is stale
- **WHEN** the submitted draft revision, dataset, metric set, or objectives identity is no longer current
- **THEN** the API rejects creation with a safe conflict and creates no job

### Requirement: Job status is persisted and owner scoped
The system SHALL expose analysis-job list and detail reads from PostgreSQL with exactly `queued`, `running`, `succeeded`, and `failed` states, ordered attempt history, queue/start/finish timestamps, and only the fields appropriate to each state. Lists SHALL use the established owner-scoped keyset pagination contract. Missing and foreign jobs SHALL have indistinguishable `404 resource_not_found` responses.

#### Scenario: Owner polls a running job
- **WHEN** the report owner requests a claimed analysis job
- **THEN** the response reports `running`, its persistent ID, attempt ordinal, queue and start timestamps, and no invented result

#### Scenario: Owner polls a failed job
- **WHEN** the report owner requests a failed analysis job
- **THEN** the response includes finish time and a stable sanitized failure code, safe message, and retryability without internal error details

#### Scenario: Another owner requests the job
- **WHEN** an authenticated principal requests a job under a report they do not own
- **THEN** the response matches the missing-resource `404` without disclosing job metadata

### Requirement: Worker delivery produces durable legal transitions
The system SHALL claim a queued attempt transactionally before execution and SHALL persist a terminal `succeeded` or `failed` outcome with a finish timestamp. A success SHALL require a validated result with matching job and numeric provenance. A failure SHALL carry only approved sanitized details. Repeated or concurrent delivery SHALL not produce another claim, result, attempt, or conflicting terminal outcome. A late result from changed semantic inputs SHALL not become the report's current analysis or overwrite newer draft content.

#### Scenario: Validated work completes
- **WHEN** a worker claims a queued attempt and receives a validated result matching its captured input
- **THEN** that attempt and logical job become `succeeded` once, and the result becomes current only if the report input is still current

#### Scenario: Processing fails
- **WHEN** a claimed attempt encounters a processing error or has no available analysis executor
- **THEN** that attempt and logical job become `failed` with a finish timestamp and an approved safe failure code, without a fabricated analysis result

#### Scenario: Delivery is repeated
- **WHEN** the same queued job message is delivered to concurrent workers or redelivered after completion
- **THEN** at most one worker executes the claimed attempt and its persisted terminal outcome remains unchanged

#### Scenario: Result is stale at completion
- **WHEN** the report input changes before a claimed attempt completes
- **THEN** the attempt outcome remains recorded but no stale result is attached to the report or active draft

### Requirement: Retry and queue recovery are idempotent
The system SHALL retry only a failed, retryable logical job whose captured semantic input is still current and whose observed attempt ordinal matches. A successful retry command SHALL create exactly one new queued attempt on the same job and return HTTP `202`; equivalent replay SHALL create none. Queued work SHALL remain discoverable after publish failure and SHALL be redeliverable without using broker state as the status authority.

#### Scenario: Failed job is retried
- **WHEN** the owner retries an eligible failed job with a new idempotency key and matching observed attempt ordinal
- **THEN** the same logical job becomes `queued` with exactly one next-ordinal attempt and a new queue timestamp

#### Scenario: Retry is no longer eligible
- **WHEN** the job is not failed, is not retryable, its input is stale, or its observed ordinal is outdated
- **THEN** the API returns a safe conflict and creates no attempt

#### Scenario: Delivery publish fails after acceptance
- **WHEN** broker delivery fails after the queued job is committed
- **THEN** the job remains visible as `queued` in PostgreSQL and a recovery process can redeliver it without adding an attempt

### Requirement: Job execution keeps private data out of public and operational surfaces
The system SHALL expose only safe status and failure fields through the API and SHALL avoid logging credentials, source content, prompts, provider payloads, stack traces, internal object keys, or signed URLs. Worker messages SHALL contain only opaque identifiers needed to resolve the persisted job.

#### Scenario: Dependency error is observed
- **WHEN** a worker or broker encounters a dependency failure
- **THEN** API and ordinary logs contain only approved identifiers and sanitized status or error fields
