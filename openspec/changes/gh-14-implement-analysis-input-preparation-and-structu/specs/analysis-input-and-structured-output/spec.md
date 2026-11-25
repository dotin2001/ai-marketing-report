## Purpose

Provide a trustworthy, reproducible context for narrative analysis and a validated five-section result that cannot turn unverified claims into computed facts.

## ADDED Requirements

### Requirement: Analysis input is bound to confirmed numeric provenance
The system SHALL prepare analysis input only from the owner-scoped report, current confirmed dataset, job-captured metric result set, inclusive reporting period, and objectives at the job's captured draft and objectives revisions. It SHALL preserve each selected metric's exact serialized value or unavailable reason, unit, scope, currency, calculation version, metric identity, and represented currencies. It MUST NOT recalculate KPIs, combine currencies, use unconfirmed source rows as figures, or substitute a missing or unavailable value.

#### Scenario: Current confirmed analysis input is prepared
- **WHEN** an analysis job refers to a current confirmed dataset, its matching metric result set, and the matching active draft and objectives revisions
- **THEN** prepared input contains the inclusive period, ordered objectives, and deterministic metric records with exact values or explicit unavailability and provenance.

#### Scenario: A metric is unavailable or currencies differ
- **WHEN** a selected KPI has a missing input, zero denominator, or incompatible currency, or monetary results exist in multiple currency groups
- **THEN** the input carries the recorded reason and separate currency scopes without a numeric substitute or combined monetary total.

#### Scenario: Captured inputs are stale or foreign
- **WHEN** the report owner, confirmed dataset, metric identity, period, draft revision, or objectives revision does not match the job's captured semantic input
- **THEN** preparation fails safely and no successful analysis result is attached.

### Requirement: Bounded context treats source text as untrusted
The system SHALL bound the number and size of objectives and metric records included in one request and SHALL use deterministic ordering. Any permitted source excerpt or user claim MUST be labeled as unvalidated data and delimited from instructions; it MUST NOT be represented as a computed KPI. The prepared context and customer-bearing prompt content MUST NOT be logged or returned in job status or errors.

#### Scenario: Input exceeds the analysis budget
- **WHEN** current objectives or metric records exceed the configured analysis context budget
- **THEN** preparation reports a safe explicit failure or deterministic omission that identifies the limitation without silently omitting a required KPI, inventing a value, or exposing the omitted content.

#### Scenario: Pasted claim contains an instruction
- **WHEN** an optional pasted claim or source excerpt contains text that asks the analysis system to change its behavior
- **THEN** the text remains delimited, labeled unvalidated data and cannot override the analysis rules or become a validated metric.

### Requirement: Narrative output has five validated sections
The system SHALL accept only a schema-valid result with `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps` sections. Each item SHALL have nonblank bounded content, stable order, and an `observation` or `hypothesis` classification; a user claim, when supported by the existing result contract, SHALL remain explicitly labeled `user_claim`. The result SHALL retain model identifier, prompt version, request provenance, semantic input identity, and numeric-source identity. Unknown fields, invalid classifications, malformed sections, and missing required provenance MUST fail validation before persistence or display.

#### Scenario: Complete five-section result is accepted
- **WHEN** a result contains a valid summary and all five sections, including empty anomaly or gap lists where appropriate, with valid labels and provenance
- **THEN** it is available for persistence in the existing analysis-result structure and public five-section representation.

#### Scenario: Malformed structured output is rejected
- **WHEN** a result omits a required section, adds unknown fields, uses an invalid label, or has blank or oversized item content
- **THEN** it is rejected as `invalid_structured_output`, no result is attached, and the job exposes only a sanitized failure.

### Requirement: Numeric assertions are grounded in prepared metrics
Every numeric KPI assertion in an analysis item SHALL reference a prepared available metric identity and use that metric's recorded value, unit, scope, period, and currency. A data limitation SHALL be able to reference a prepared unavailable metric and its reason without asserting a numeric value. The system MUST reject references outside the captured metric set, cross-owner references, mismatched values or units, and unsupported numeric figures before success.

#### Scenario: Finding cites an available KPI
- **WHEN** a finding cites a prepared available metric with matching value, unit, scope, period, and currency
- **THEN** the validated item retains that metric reference and can be persisted with the result.

#### Scenario: Unavailable KPI is described as a limitation
- **WHEN** a data-gap item cites a prepared unavailable metric and its recorded reason
- **THEN** the result may explain the limitation without supplying a numeric value.

#### Scenario: Figure is invented or reference is foreign
- **WHEN** an item asserts a numeric KPI without a matching prepared metric reference, changes a metric value or currency, or cites a metric outside the captured owner-scoped set
- **THEN** validation rejects the output and no successful result is persisted or displayed.
