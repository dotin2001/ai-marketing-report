## Purpose

Make an explicitly confirmed CSV dataset usable for reproducible marketing KPI analysis while exposing safe, owner-authorized row accounting and calculation provenance.

## ADDED Requirements

### Requirement: Row accounting preserves the all-or-nothing confirmation gate
The system SHALL expose total, accepted, and rejected source-record counts with safe explanations. A validation with blocking errors MUST report zero accepted and all source records rejected for confirmation, clearly identifying this as rejection of the whole revision; it MUST NOT yield a current dataset or metric result. The owner MUST resolve errors and confirm a new error-free review. A successful confirmation SHALL accept every source data record, including warned duplicates, and report zero rejected records. Counts MUST refer to distinct source records, not issue count.

#### Scenario: Error-free reviewed CSV is confirmed
- **WHEN** the owner confirms an error-free current validation with its exact warnings acknowledged
- **THEN** the confirmation and dataset expose accepted count equal to total data records and rejected count zero
- **AND** every canonical row retains its one-based source-record index.

#### Scenario: Rejected validation is explained
- **WHEN** a reviewed CSV contains one or more blocking mapping or row errors
- **THEN** validation reports zero accepted and all source records rejected for confirmation, identifies the error codes and safe locations, and creates no current dataset or metric result
- **AND** it does not describe valid-looking rows as partially confirmed.

### Requirement: Confirmed data yields deterministic scoped aggregates
The system SHALL calculate CTR, CPC, CPM, and CPL only from canonical rows of a current confirmed dataset. It SHALL support a whole-report-period scope and individual campaign scopes over that same inclusive period. It SHALL sum each required input within the selected scope before one division and MUST NOT average row ratios or use pasted claims, filenames, comments, or unmapped values. CTR MAY span represented currencies; monetary KPIs MUST use one currency partition, and a requested cross-currency monetary result SHALL be unavailable with `incompatible_currency`.

#### Scenario: Aggregate CTR differs from row average
- **WHEN** two confirmed rows have clicks/impressions of `1/10` and `1/100`
- **THEN** report-period CTR uses totals `2/110` and is approximately `1.818181818181` percent, with at least 12 significant decimal digits
- **AND** it does not use the average of the two row CTR values.

#### Scenario: Campaign and currency partitions are distinct
- **WHEN** canonical rows include multiple campaign names and USD and EUR spend
- **THEN** each requested campaign result uses only rows with that exact canonical campaign name
- **AND** CPC, CPM, and CPL results identify their single currency and never combine USD and EUR spend.

### Requirement: KPI availability and provenance are explicit
Every requested supported KPI SHALL return an available or unavailable result with canonical-data identity, calculation version, calculation time, inclusive period, aggregation scope, represented currencies, and exact aggregate input totals as decimal strings where present. Available results SHALL include a numeric value and unit and omit an unavailable reason. Unavailable results SHALL omit numeric value and unit and include exactly one reason from `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, or `incomparable_period`, with safe supporting details. The calculation context MUST provide at least 28 significant decimal digits and serialize non-terminating available quotients with at least 12 significant digits.

#### Scenario: Missing or zero denominator
- **WHEN** an input column is unmapped or a required denominator totals zero
- **THEN** the relevant result is unavailable with `missing_input` or `zero_denominator` respectively, without zero, infinity, `NaN`, or an invented value.

#### Scenario: True zero and exact decimal spend
- **WHEN** clicks are zero and impressions are positive, or spend values `0.10` and `0.20` sum with three clicks
- **THEN** CTR is available as zero in the first case and CPC is exactly `0.10` in the second case
- **AND** no binary-float artifact enters the serialized result.

#### Scenario: Period comparison compatibility
- **WHEN** two stored KPI results are compared
- **THEN** a comparison is available only for equivalent duration and boundaries, metric definition and version, mapping and normalization policy, scope, and currency
- **AND** an incompatible comparison is unavailable with `incomparable_period` and identifies the mismatched attributes without a numeric value.

### Requirement: Metric attachment and reads are current, repeatable, and owner safe
The system SHALL attach one logical result set to the current confirmed dataset identity and calculation version. Equivalent reruns SHALL return the same logical result without duplicate current results. Source, mapping, normalization policy, or report-period changes SHALL invalidate current metric attachment but preserve historical datasets and results. Dataset detail, canonical row, and metric reads SHALL authorize the report owner and return the same safe `404 resource_not_found` for absent and foreign resources. Row pagination SHALL be deterministic and expose only canonical fields and permitted provenance.

#### Scenario: Same input is calculated again
- **WHEN** the same confirmed dataset and calculation version are processed repeatedly
- **THEN** one current result set is returned with identical values, totals, availability, units, and scopes.

#### Scenario: Confirmed input changes
- **WHEN** the current source, mapping, policy, or period changes after metrics exist
- **THEN** the old result is no longer current, a new explicit confirmation is required, and the old result remains historical.

#### Scenario: Another owner's dataset is requested
- **WHEN** a principal requests a foreign dataset's detail, rows, or metrics
- **THEN** the response is indistinguishable from an absent resource and discloses no foreign rows, totals, or metadata.
