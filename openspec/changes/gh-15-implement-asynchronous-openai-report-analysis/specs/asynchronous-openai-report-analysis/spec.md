## Purpose

Turn a persisted, owner-authorized analysis job into a validated OpenAI narrative while preserving input provenance, safe retries, and explicit failure outcomes.

## ADDED Requirements

### Requirement: Analysis executes against a confirmed captured input
The system SHALL execute an accepted analysis job asynchronously using its captured, owner-scoped, confirmed dataset and deterministic metric result set. The provider request SHALL contain the bounded prepared context, inclusive period, explicit metric limitations, and captured objectives; it MUST NOT treat pasted claims or objectives as system instructions, recalculate metrics, combine currencies, or send unrestricted source content.

#### Scenario: Current analysis is submitted to the provider
- **WHEN** a worker claims a queued attempt whose confirmed source, dataset, metric result set, draft, objectives revision, and semantic input identity are current
- **THEN** it submits only the bounded prepared context to the configured model and keeps the persisted job in `running` until a validated terminal outcome is recorded.

#### Scenario: Captured input is stale before provider submission
- **WHEN** any captured dataset, metric, objective, draft, or period identity is no longer current before the request
- **THEN** no provider request is made, the attempt fails as `stale_result`, and no result is attached to the current draft.

#### Scenario: Untrusted objective contains instructions
- **WHEN** an objective or permitted source excerpt contains text requesting a change to model behavior
- **THEN** it is sent only as bounded, delimited data, cannot override the trusted analysis rules, and cannot become a computed metric.

### Requirement: Only validated structured analysis can succeed
The system SHALL accept a provider outcome only when it is a complete, schema-valid five-section analysis whose numeric references match the captured prepared metrics. It SHALL distinguish observations from hypotheses, preserve data gaps and unavailable reasons, and MUST NOT persist or display invented figures or unsupported period comparisons as a successful result.

#### Scenario: Complete grounded response succeeds
- **WHEN** the provider returns a complete structured response with valid `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`, and every numeric assertion matches a prepared metric
- **THEN** exactly one validated result and its metric links are persisted for the logical job, the job becomes `succeeded`, and the result is attached only if the captured input remains current.

#### Scenario: Output is malformed or ungrounded
- **WHEN** a response is missing a required section, violates the schema, cites a foreign metric, changes a metric value or unit, or asserts an invented figure
- **THEN** the attempt fails as `invalid_structured_output`, no analysis result is persisted, and the job never reports success for that attempt.

#### Scenario: Input changes during a provider call
- **WHEN** source, confirmation, metrics, period, objectives, or relevant draft revision changes after the provider request starts
- **THEN** the late response cannot overwrite newer content or become the current analysis; the attempt has a safe stale outcome.

### Requirement: Analysis results retain trusted provenance
For every successful analysis, the system SHALL retain the actual provider model identifier, trusted prompt version, safe request provenance, logical job and attempt association, captured semantic input identity, and numeric-source identity linked to the confirmed dataset revision. Provider-authored content MUST NOT supply or override trusted provenance.

#### Scenario: Successful analysis is inspected
- **WHEN** the owner reads a succeeded analysis job
- **THEN** the result exposes the validated five sections and safe model, prompt, request, and numeric-source provenance associated with that job's captured dataset and metric revision.

#### Scenario: Provider metadata is absent or invalid
- **WHEN** the provider outcome lacks a usable model identifier or the trusted adapter cannot establish required request provenance
- **THEN** the attempt cannot succeed and no result with fabricated provenance is persisted.

### Requirement: Provider failures are durable, safe, and retryable by policy
The system SHALL persist timeouts, refusals, incomplete responses, invalid structured output, and provider availability failures as terminal `failed` attempts using the established safe analysis failure codes and retryability policy. It SHALL keep status in PostgreSQL, preserve existing valid results, and permit unchanged-input retries without duplicate logical results or attempts. Clients and ordinary logs MUST NOT expose credentials, raw prompts, source content, provider payloads, stack traces, or internal object keys.

#### Scenario: Provider times out or is unavailable
- **WHEN** the provider call times out or a transient provider error occurs
- **THEN** the attempt becomes `failed` with `provider_timeout` or `provider_unavailable`, a sanitized message and retryable state, while the same-input logical job remains eligible for the existing retry command.

#### Scenario: Provider refuses or response is incomplete
- **WHEN** the provider refuses the request or returns no complete parsed analysis
- **THEN** the attempt becomes `failed` with `provider_refusal` or `incomplete_response`, exposes only sanitized details, and cannot attach a result.

#### Scenario: Delivery is repeated
- **WHEN** Celery redelivers an attempt or an owner repeats an equivalent idempotent command
- **THEN** the persisted claim and completion rules prevent an additional provider execution for a claimed attempt, duplicate result, or conflicting attempt.

#### Scenario: Foreign owner requests analysis status
- **WHEN** a principal reads or retries another owner's report or job
- **THEN** the existing owner-safe resource-not-found response applies without exposing job, result, or provider details.
