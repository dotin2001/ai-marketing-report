## Purpose

Define the canonical structured marketing import and deterministic KPI contract so every later component validates, calculates, stores, and explains the same data consistently.

## ADDED Requirements

### Requirement: Supported CSV envelope and canonical field set
The system SHALL accept the MVP structured dataset as a comma-delimited CSV with one header record and one or more data records, decoded as UTF-8 with an optional byte-order mark. Source columns SHALL be identified by ordinal and original header so mapping remains deterministic even when headers repeat. The only canonical fields SHALL be the required dimensions `date`, `campaign_name`, and `currency` plus the optional measures `impressions`, `clicks`, `spend`, and `leads`. All required dimensions and at least one supported measure MUST be mapped before confirmation. Unmapped source columns SHALL be retained in the immutable original but excluded from the canonical dataset and calculations.

#### Scenario: Supported CSV is available for mapping
- **WHEN** a UTF-8 CSV has a header record and at least one source column
- **THEN** the system exposes each source column by ordinal and original header for preview and mapping
- **AND** it does not infer unsupported columns as canonical fields

#### Scenario: Required field is not mapped
- **WHEN** `date`, `campaign_name`, or `currency` has no source-column mapping
- **THEN** validation reports a blocking missing-mapping issue for each absent required field
- **AND** the import cannot be confirmed

#### Scenario: No supported measure is mapped
- **WHEN** none of `impressions`, `clicks`, `spend`, or `leads` is mapped
- **THEN** validation reports a blocking missing-measure issue
- **AND** the import cannot be confirmed

#### Scenario: Header-only dataset is rejected
- **WHEN** a parsed CSV contains a header record but no data record
- **THEN** validation reports a blocking empty-dataset issue
- **AND** the import cannot be confirmed or calculated

#### Scenario: Unmapped source columns remain explicit
- **WHEN** one or more source columns are not mapped to canonical fields
- **THEN** validation reports each unmapped column as a non-blocking warning using its source ordinal and header
- **AND** confirmation excludes those columns from canonical data without altering the immutable original

### Requirement: One-to-one user-confirmed mapping
The system SHALL require an explicit mapping configuration in which each source-column ordinal maps to at most one canonical field and each canonical field receives at most one source column. Suggested mappings MUST remain editable and MUST NOT count as confirmed mappings until the owner explicitly confirms the current mapping, normalization result, and validation summary. A mapping or source revision change MUST invalidate the previous confirmation and derived metrics.

#### Scenario: Suggested mapping is corrected before confirmation
- **WHEN** the system suggests an incorrect canonical field for a source column and the owner changes it
- **THEN** validation and preview use the corrected mapping revision
- **AND** no earlier suggestion is treated as confirmed input

#### Scenario: Duplicate mapping is rejected
- **WHEN** two source columns target the same canonical field or one source-column ordinal targets multiple canonical fields
- **THEN** validation reports a blocking duplicate-mapping issue identifying all involved columns and fields
- **AND** the import cannot be confirmed

#### Scenario: Confirmed mapping changes
- **WHEN** the source, mapping, or normalization configuration changes after confirmation
- **THEN** the prior canonical-data identity and metric results cease to be current
- **AND** the changed revision requires validation and explicit confirmation before recalculation

### Requirement: Canonical types, units, and normalization
The canonical dataset SHALL normalize `date` to a calendar date serialized as `YYYY-MM-DD`; `campaign_name` to a non-empty Unicode string with surrounding whitespace removed; and `currency` to an uppercase ISO 4217 alphabetic code. `impressions`, `clicks`, and `leads` SHALL be non-negative base-10 whole counts. `spend` SHALL be a non-negative finite base-10 decimal amount expressed in the major unit of the row's currency, without binary floating-point coercion or implicit scaling. Normalization MUST reject booleans, percentages, currency symbols, `NaN`, infinities, and values requiring locale-dependent interpretation. It MUST preserve the immutable original value and record the normalization-policy version.

#### Scenario: Valid row is normalized canonically
- **WHEN** a row contains an unambiguous date, a non-blank campaign name, a supported currency code with any letter case, valid whole counts, and a valid decimal spend value
- **THEN** the canonical row contains an ISO date, trimmed campaign name, uppercase currency code, integer counts, and an exact decimal spend amount in major currency units
- **AND** provenance links every canonical value to its source record and source-column ordinal

#### Scenario: Ambiguous date is blocked
- **WHEN** a date value can represent more than one calendar date under the allowed parsing configuration or does not represent a valid date
- **THEN** validation reports a blocking ambiguous-date or invalid-date issue for that source record
- **AND** the system does not guess a date from locale or runtime defaults

#### Scenario: Invalid measure is blocked
- **WHEN** a mapped count is fractional, any mapped measure is negative, non-finite, contains a unit or currency symbol, or otherwise cannot be parsed under the confirmed normalization policy
- **THEN** validation reports a blocking invalid-measure issue for that source record and canonical field
- **AND** the system does not coerce the value to zero or silently discard the record

#### Scenario: Unsupported currency is blocked
- **WHEN** a currency value is not an active supported ISO 4217 alphabetic code in the versioned validation list
- **THEN** validation reports a blocking unsupported-currency issue for that source record
- **AND** no spend-based result is calculated from that row

### Requirement: Missing values are never imputed
A blank or missing value in any required dimension or in any measure column that is present and mapped SHALL be a blocking row issue. The system MUST NOT impute, forward-fill, interpolate, or convert such a value to zero. A measure column that is not mapped SHALL be treated as an absent metric input rather than a row error, provided at least one other supported measure is mapped.

#### Scenario: Mapped measure cell is missing
- **WHEN** a row has a blank or missing value for a mapped measure
- **THEN** validation reports a blocking missing-value issue for that source record and field
- **AND** the row is not silently included with a zero or imputed value

#### Scenario: Optional measure column is absent
- **WHEN** a confirmed dataset omits one supported measure column but maps at least one other measure
- **THEN** the dataset can be confirmed if all present fields are valid
- **AND** every KPI requiring the absent measure is unavailable with reason `missing_input`

### Requirement: Validation issues and confirmation gate
Every validation issue SHALL have a stable machine-readable code, severity of `error` or `warning`, a safe human-readable message, and applicable canonical field, source-column ordinal, and one-based source-record index. Errors SHALL block confirmation; warnings SHALL require display before confirmation but SHALL NOT block it. Validation SHALL cover missing and duplicate mappings, missing values, invalid rows, ambiguous dates, unsupported currencies, unmapped columns, duplicate source records detected by exact canonical row equality, dates outside the report's inclusive reporting period, and mixed-currency aggregation risk. Confirmation SHALL persist the source identity and checksum, mapping and normalization-policy revisions, validation summary, canonical-data identity, row count, reporting period, currencies present, confirmation time, and owner/report association.

#### Scenario: Blocking errors prevent confirmation
- **WHEN** validation returns one or more issues with severity `error`
- **THEN** the confirmation request fails with the current validation summary and field or row details
- **AND** no confirmed configuration, canonical dataset, or metric result becomes current

#### Scenario: Warnings are acknowledged
- **WHEN** validation returns warnings but no errors and the owner explicitly confirms the current revision
- **THEN** the confirmation records the warnings and their acknowledgement with the canonical-data identity
- **AND** deterministic calculation may proceed under the warning-specific rules

#### Scenario: Exact duplicate canonical row is detected
- **WHEN** two source records normalize to exactly the same values across every mapped canonical field
- **THEN** validation reports a non-blocking duplicate-row warning identifying both source-record indexes
- **AND** both rows remain included unless the user changes the source because the system does not silently deduplicate

#### Scenario: Date falls outside the reporting period
- **WHEN** a normalized row date precedes the report start date or follows the report end date
- **THEN** validation reports a blocking out-of-period issue for that source record
- **AND** the current import cannot be confirmed for that report period

### Requirement: Deterministic aggregate KPI formulas
For each requested aggregation scope, the system SHALL sum canonical inputs before division and SHALL calculate only these KPI definitions: `CTR = aggregate clicks / aggregate impressions * 100`, `CPC = aggregate spend / aggregate clicks`, `CPM = aggregate spend / aggregate impressions * 1000`, and `CPL = aggregate spend / aggregate leads`. It MUST NOT average row-level ratios, use AI-generated arithmetic, infer unsupported inputs, or apply intermediate display rounding. `CTR` SHALL have unit `percent`; `CPC` SHALL have unit `<currency>/click`; `CPM` SHALL have unit `<currency>/1000_impressions`; and `CPL` SHALL have unit `<currency>/lead`. A serialized available value SHALL retain at least 12 significant decimal digits when the exact quotient is non-terminating, while presentation rounding MUST remain separate from the stored result.

#### Scenario: Aggregate ratio differs from average row ratio
- **WHEN** valid rows have different denominators such that the aggregate ratio differs from the arithmetic mean of row ratios
- **THEN** the system calculates the KPI from the summed numerator and summed denominator
- **AND** the recorded input totals reproduce the returned result under the calculation version

#### Scenario: Valid zero numerator produces zero
- **WHEN** a KPI numerator totals zero and its required denominator is present and greater than zero
- **THEN** the system records an available metric value of zero with the defined unit
- **AND** it distinguishes that valid value from an unavailable metric

#### Scenario: Calculation is reproducible
- **WHEN** the same confirmed canonical data, aggregation scope, and calculation version are evaluated more than once
- **THEN** the system returns identical metric availability, input totals, units, currency scope, and serialized values
- **AND** display formatting does not alter the stored calculation result

### Requirement: Explicit metric availability and provenance
The system SHALL produce a result record for each supported KPI requested for the confirmed dataset, whether available or unavailable. An available result SHALL include metric name, decimal value, unit, exact aggregate input totals, aggregation scope, reporting period, currency when applicable, canonical-data identity, calculation version, and calculation time. An unavailable result SHALL omit the value and SHALL include exactly one primary reason from `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, or `incomparable_period`, plus supporting field or scope details. An unavailable result MUST NOT expose zero, infinity, `NaN`, or an invented substitute as its value.

#### Scenario: Required input is absent
- **WHEN** a supported KPI requires a measure column that was not mapped
- **THEN** the KPI result is unavailable with reason `missing_input` and identifies the absent canonical field
- **AND** it has no numeric value

#### Scenario: Aggregate denominator is zero
- **WHEN** all required inputs are present and valid but the KPI's aggregate denominator is zero
- **THEN** the KPI result is unavailable with reason `zero_denominator` and records the zero input total
- **AND** it has no numeric value, infinity, or `NaN`

#### Scenario: Invalid unconfirmed data cannot produce current metrics
- **WHEN** the current source or mapping revision has blocking validation errors or has not been confirmed
- **THEN** no metric result from that revision can become current
- **AND** any calculation request reports the input as invalid rather than partially calculating from selected rows

### Requirement: Currency-isolated spend metrics
The system SHALL calculate `CPC`, `CPM`, and `CPL` only inside aggregation scopes containing exactly one currency. When a confirmed dataset contains multiple currencies, the system SHALL produce separate spend-based results for each currency group that has the required inputs and SHALL mark any requested cross-currency spend result unavailable with reason `incompatible_currency`. It MUST NOT add spend across currencies, choose a preferred currency, or perform implicit conversion. `CTR` MAY aggregate across currency groups because neither input is monetary, while its result provenance SHALL list the currencies represented in the scope.

#### Scenario: Single-currency spend KPI is calculated
- **WHEN** the requested scope contains one currency and valid spend and denominator inputs
- **THEN** the system returns the spend-based KPI with that ISO 4217 code in its unit and currency field
- **AND** its aggregate spend total contains only rows in that currency

#### Scenario: Mixed-currency dataset produces per-currency results
- **WHEN** a confirmed dataset contains two or more supported currencies
- **THEN** the system calculates spend-based KPI results independently for each currency group with sufficient inputs
- **AND** a report-wide spend-based result is unavailable with reason `incompatible_currency`

#### Scenario: CTR spans currencies without combining money
- **WHEN** a mixed-currency confirmed dataset has valid clicks and impressions
- **THEN** the system may calculate report-wide CTR from all clicks and impressions
- **AND** the result records the multi-currency scope but no currency-denominated unit

### Requirement: Comparable periods and calculation versions
A KPI comparison SHALL be available only when both results use the same metric definition and calculation version, compatible mappings and normalization policies, compatible aggregation scopes and currency rules, and reporting periods with equivalent boundaries and duration under an explicitly selected comparison policy. Otherwise, the comparison SHALL be unavailable with reason `incomparable_period` and details identifying the incompatible attributes. The system MUST NOT derive a comparative conclusion from an unavailable comparison.

#### Scenario: Compatible periods can be compared
- **WHEN** two confirmed result sets have equal-duration periods, compatible boundaries, the same metric and calculation version, compatible mappings, and the same applicable currency scope
- **THEN** the system may calculate a deterministic comparison from the stored metric values
- **AND** the comparison retains both source result identities and periods

#### Scenario: Incompatible periods are not compared
- **WHEN** periods differ incompatibly in duration or boundaries or their metric definition, mapping, calculation version, aggregation scope, or currency scope differs
- **THEN** the comparison is unavailable with reason `incomparable_period` and identifies the incompatibility
- **AND** no deterministic output or downstream AI context states a comparative conclusion

### Requirement: Structured data and unvalidated claims remain separate
Only a confirmed canonical dataset SHALL be eligible for deterministic KPI calculation. Values or claims found in pasted text, unmapped columns, filenames, comments, or other untrusted metadata MUST NOT populate canonical fields or metric inputs unless the user supplies them through a supported mapped CSV and confirms the resulting canonical data. Original source material SHALL remain preserved and distinguishable from normalized values and calculated results.

#### Scenario: Pasted figure is not used as a metric input
- **WHEN** pasted text claims a click count, spend value, or KPI result
- **THEN** the system retains it as an unvalidated user-provided claim
- **AND** deterministic calculation does not use it as a canonical input

#### Scenario: Unmapped numeric column is excluded
- **WHEN** an unmapped source column contains numeric values resembling a supported measure
- **THEN** the system excludes those values from aggregate totals and KPI calculations
- **AND** the preview identifies the column as unmapped before confirmation
