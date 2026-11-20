## Purpose

Complete CSV mapping review by making only an explicitly confirmed, fully normalized, provenance-bound dataset available for later deterministic analysis.

## ADDED Requirements

### Requirement: Confirm only the exact reviewed mapping and normalization result
The system SHALL accept confirmation only from the report owner for the current CSV source and an error-free validation of its exact mapping revision, normalization-policy version, source checksum, and inclusive report period. The owner MUST explicitly acknowledge the complete set of warnings from that validation. A suggestion, preview, or validation alone MUST NOT create a current canonical dataset.

#### Scenario: Current error-free revision is confirmed
- **WHEN** the owner confirms the current validation and acknowledges exactly its warning set
- **THEN** the system records the confirming principal, validation and configuration identities and revision, source checksum, policy version, period, warning acknowledgement, row count, and canonical-data identity
- **AND** a canonical dataset for that exact input becomes current.

#### Scenario: Ambiguous date requires explicit resolution
- **WHEN** a mapped date is ambiguous without a selected supported format
- **THEN** validation reports a located blocking `ambiguous_date` error and confirmation creates no current dataset
- **AND** the owner must select an explicit format in a new configuration revision and validate that revision before confirmation.

#### Scenario: Errors or unacknowledged warnings block confirmation
- **WHEN** the validation has a blocking error or the acknowledgement omits, duplicates, or adds a warning identifier
- **THEN** confirmation fails with a stable safe error and makes no confirmation or dataset current.

#### Scenario: Reviewed input changes before confirmation
- **WHEN** the current source, mapping revision, normalization policy, or report period differs from the validated input
- **THEN** confirmation fails as stale and the changed input requires fresh validation and explicit confirmation
- **AND** any earlier confirmed dataset remains historical.

### Requirement: Canonical data preserves normalization and source provenance
The confirmed dataset SHALL contain every valid source record exactly once, including exact duplicate canonical rows, and SHALL contain only mapped canonical fields. `date` MUST be an ISO calendar date inside the inclusive period; `campaign_name` MUST be non-empty after surrounding whitespace removal; `currency` MUST be an uppercase supported ISO 4217 code; mapped counts MUST be non-negative whole integers; and mapped spend MUST be a non-negative finite exact base-10 decimal in that row's currency. Missing mapped values, ambiguous or invalid dates, unsupported currencies, invalid measures, and out-of-period dates MUST NOT be guessed, imputed, silently dropped, or converted to zero. The dataset and rows SHALL retain source-record identity and a link to the confirmed source-column mapping and policy.

#### Scenario: All seven mapped fields normalize without loss
- **WHEN** the owner confirms a valid row using all supported fields
- **THEN** its canonical row contains an ISO date, trimmed campaign label, uppercase supported currency, whole counts, and exact-decimal spend
- **AND** the row's one-based source-record index and confirmed mapping identify the origin of each value.

#### Scenario: Duplicate and unmapped source values are handled explicitly
- **WHEN** validation contains a duplicate-row warning and an unmapped-column warning that the owner acknowledges
- **THEN** both duplicate records appear in canonical data with their distinct record indexes
- **AND** unmapped values remain in the immutable original but do not appear in canonical fields.

#### Scenario: Mixed currencies remain separate
- **WHEN** valid source rows use more than one supported currency and the owner acknowledges the warning
- **THEN** canonical rows retain their individual currency codes and the dataset lists every represented currency
- **AND** confirmation does not convert or combine monetary values.

### Requirement: Confirmation is atomic, idempotent, and owner safe
The confirmation API SHALL require an idempotency key and SHALL create or return one logical confirmation and canonical dataset for an equivalent owner-scoped request. A reused key with different semantic input MUST fail with `idempotency_conflict`. Confirmation and dataset commitment MUST be atomic: any validation, freshness, persistence, or source-integrity failure leaves no partial current confirmation or dataset. Missing and foreign report or source identities MUST yield indistinguishable `404 resource_not_found` responses. Responses and errors MUST NOT reveal source cell values, unrestricted original content, internal object keys, or credentials.

#### Scenario: Equivalent confirmation is retried
- **WHEN** the owner repeats an equivalent request with the same idempotency key, including after a delivery retry
- **THEN** the API returns the original confirmation and canonical dataset identities with replay indicated
- **AND** it creates no duplicate confirmation, dataset, or canonical rows.

#### Scenario: Idempotency key is reused for another input
- **WHEN** the owner reuses a confirmation key with a different validation, revision, or acknowledgement set
- **THEN** the API returns `409 idempotency_conflict` and preserves the original result.

#### Scenario: Foreign report is requested
- **WHEN** a principal attempts confirmation for another owner's report or source
- **THEN** the API returns the same safe `404 resource_not_found` response as for an absent resource
- **AND** no confirmation, dataset, source metadata, or validation issue is disclosed.
