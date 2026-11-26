## Purpose

Keep analysis requests safe to repeat and bounded to a clear retry policy while preserving current draft content when workers finish late.

## ADDED Requirements

### Requirement: Analysis failure classification determines retry eligibility
The system SHALL persist each failed attempt with a safe failure code, message, and retryability. `provider_timeout` and transient `provider_unavailable` SHALL be retryable while the captured input is current and the attempt limit remains; `provider_refusal`, `invalid_structured_output`, and `stale_result` SHALL be non-retryable. `incomplete_response` SHALL be retryable only when the response ended without a complete parsed result. The logical job's public retryability SHALL be false once its attempt limit is reached, even if its last attempt failed for a transient reason. Raw provider details, prompts, source data, and credentials MUST NOT appear in public errors or ordinary logs.

#### Scenario: Provider timeout
- **WHEN** a claimed provider request times out
- **THEN** the attempt and logical job finish as `failed` with safe `provider_timeout` metadata and remain eligible for an explicit retry only if the captured input is current and attempts remain

#### Scenario: Refusal or malformed output
- **WHEN** the provider refuses or the completed output fails structured or grounding validation
- **THEN** the job finishes with `provider_refusal` or `invalid_structured_output`, exposes no result, and rejects retry

#### Scenario: Retry budget is exhausted
- **WHEN** the third total attempt fails for an otherwise transient reason
- **THEN** the job is `failed`, its public failure is non-retryable, and a retry request returns `409 job_not_retryable` without a fourth attempt

### Requirement: Owner retry is bounded and input bound
The system SHALL allow at most three total attempts for one logical analysis job, counting the initial attempt. A retry SHALL require the owner, a failed retryable job, the observed attempt ordinal, a new scoped idempotency key, and the exact current captured semantic input. A valid retry SHALL queue exactly one next-ordinal attempt on the same job and return HTTP `202`. An ineligible retry SHALL leave the job and attempts unchanged and return a safe conflict; missing and foreign jobs SHALL remain indistinguishable owner-safe `404` responses.

#### Scenario: Eligible retry
- **WHEN** the owner retries a transiently failed first attempt with the observed ordinal and unchanged input
- **THEN** the same job becomes `queued` with exactly one second attempt

#### Scenario: Stale or concurrent retry
- **WHEN** the captured input changed, the observed ordinal is outdated, or another request already queued a retry
- **THEN** the request returns a safe conflict and adds no attempt

#### Scenario: Foreign retry
- **WHEN** a caller retries another owner's job
- **THEN** the API returns the same `404 resource_not_found` shape as a missing job and reveals no job metadata

### Requirement: Repeated commands and deliveries converge on one operation
The system SHALL identify a logical analysis operation by owner, report, and captured semantic input, and SHALL use persisted idempotency and transactional uniqueness to make equivalent repeated create or retry requests converge. Equivalent scoped-key replay SHALL resolve to the original logical job without adding an attempt, even after its state changes; reuse of that key for a different semantic command SHALL return `409 idempotency_conflict`. A different creation key for the same current semantic input SHALL resolve to the existing logical job without a second attempt. Repeated or concurrent worker deliveries of an attempt SHALL not invoke the provider more than once for that attempt or produce conflicting results. Broker publish recovery SHALL redeliver the existing queued attempt without adding one.

#### Scenario: Repeated create click
- **WHEN** equivalent create requests arrive concurrently with the same key or separate keys for the same current semantic input
- **THEN** both resolve to one logical job with one initial attempt and no duplicate provider execution

#### Scenario: Replayed retry
- **WHEN** an equivalent retry command is replayed with its original scoped key after the job has advanced
- **THEN** it resolves to the same logical job and creates no additional attempt

#### Scenario: Key conflict
- **WHEN** a scoped key is reused for different command input
- **THEN** the API returns `409 idempotency_conflict` and changes neither result

#### Scenario: Broker redelivery
- **WHEN** a queued attempt is delivered twice or republished after an initial publish failure
- **THEN** one claim executes and no new attempt or conflicting terminal result is created

### Requirement: Timeout recovery and late completion preserve current work
The system SHALL persist a safe `provider_timeout` failure for a running attempt whose execution exceeds the configured recovery threshold. Recovery and worker completion SHALL use the attempt ordinal and legal persisted state transition so only one terminal outcome wins. A result whose captured semantic input is no longer current SHALL never become the report's current analysis or overwrite a changed draft, and a stale attempt SHALL have a safe terminal outcome. Earlier valid results and unsaved or newer draft content SHALL remain intact.

#### Scenario: Worker stalls
- **WHEN** a running attempt passes the stale-running threshold without a terminal outcome
- **THEN** recovery marks that attempt failed as `provider_timeout` once, with no fabricated analysis result

#### Scenario: Late provider completion after draft edit
- **WHEN** an owner changes the relevant draft revision while a provider request is running
- **THEN** the late result is rejected as stale and cannot replace the current analysis or the newer draft content

#### Scenario: Recovery races completion
- **WHEN** timeout recovery and worker completion target the same running ordinal concurrently
- **THEN** one terminal transition wins and the other leaves the persisted job, attempt, and result unchanged
