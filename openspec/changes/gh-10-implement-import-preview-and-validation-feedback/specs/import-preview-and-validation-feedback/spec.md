## Purpose

Give report owners a bounded view of an imported CSV and complete, location-aware validation feedback for the exact mapping revision they must review before confirmation.

## ADDED Requirements

### Requirement: Preview identifies source shape and sample scope
The owner-authorized CSV preview SHALL expose every source column by zero-based ordinal and original header, a bounded sample of rows with one-based data-record indexes, the total data-record count, and whether any displayed content was truncated. A preview SHALL remain explicitly unvalidated and unconfirmed, and its sample MUST NOT be mistaken for the full validation result. Repeated header names MUST remain distinguishable by ordinal. Pasted-text preview SHALL remain bounded and labeled unvalidated.

#### Scenario: CSV exceeds the sample limit
- **WHEN** an owner previews a CSV with more records than the configured sample limit
- **THEN** the response contains the bounded indexed sample, all identifiable source columns, the full total record count, and `truncated: true`
- **AND** it does not claim that the sample has passed validation.

#### Scenario: Header-only CSV
- **WHEN** an owner previews a CSV containing a header and no data record
- **THEN** the response shows the columns and `total_records: 0`
- **AND** subsequent validation reports `empty_dataset` as a blocking issue.

### Requirement: Mapping revisions are explicit and current-source bound
The import-review API SHALL accept one-to-one source-column-ordinal mappings to the seven supported canonical fields, an expected configuration revision, an explicit date format when needed, and a versioned normalization policy. Suggested mappings SHALL remain editable and MUST NOT count as confirmation. A revision update SHALL use compare-and-set semantics; validation MUST be bound to the report's current CSV source, current report period, and exact configuration revision. Invalid or duplicate mappings SHALL be reported as blocking validation issues rather than silently repaired.

#### Scenario: Owner corrects a mapping
- **WHEN** an owner changes a suggested or prior mapping using the current expected revision
- **THEN** the new revision is available for validation and the previous validation is not eligible for current confirmation.

#### Scenario: Stale mapping update
- **WHEN** a mapping update uses an outdated expected revision
- **THEN** the API returns `409 revision_conflict` and does not replace the current revision.

### Requirement: Full dataset validation returns located feedback
Validation SHALL inspect every data record in the current CSV, not only previewed rows. It SHALL apply the current mapping, explicit normalization settings, and inclusive report period without imputing missing values, silently dropping records, or calculating from invalid rows. Each issue SHALL include a stable code, `error` or `warning` severity, safe message, and applicable canonical field, zero-based source-column ordinal, one-based source-record index, and related record index. The response SHALL include source and configuration revision identities, error and warning counts, total data-record count, preview identity when available, and an explicit confirmation-blocked indicator derived from the presence of errors. Issue ordering SHALL be deterministic.

#### Scenario: Invalid value beyond the preview sample
- **WHEN** a mapped measure contains an invalid value in a record outside the preview sample
- **THEN** validation returns a blocking issue with that record index, source-column ordinal, and canonical field
- **AND** the error count and confirmation-blocked indicator include it.

#### Scenario: Missing or duplicate mappings
- **WHEN** a required dimension or all measures are unmapped, or a mapping duplicates a source ordinal or canonical field
- **THEN** validation returns the applicable `missing_required_mapping`, `missing_measure_mapping`, or `duplicate_mapping` error with available column and field locations.

#### Scenario: Invalid normalized rows
- **WHEN** a mapped value is blank, an invalid or ambiguous date, an unsupported currency, an invalid count or spend, negative, or outside the report period
- **THEN** validation returns the applicable blocking code and row/column location without echoing the cell value.

### Requirement: Warnings remain visible and non-blocking
Validation SHALL report unmapped columns, exact duplicate canonical rows, and mixed currencies with the stable `unmapped_column`, `duplicate_row`, and `mixed_currency` warning codes. It SHALL identify both record indexes for a duplicate row and MUST NOT silently deduplicate. Warnings SHALL be visible in the summary and MUST require acknowledgement at a later confirmation step, but SHALL NOT by themselves set the confirmation-blocked indicator. Currency values MUST NOT be combined into a monetary result by this review flow.

#### Scenario: Warning-only import
- **WHEN** a valid mapped CSV has an unmapped extra column, duplicate canonical row, or multiple supported currencies but no errors
- **THEN** validation returns the corresponding located warnings, zero errors, and `confirmation_blocked: false`
- **AND** it makes no confirmed import or metric result.

### Requirement: Review results are safe, persisted, and freshness checked
The system SHALL persist the validation summary and ordered issues for the exact owner, report, source, configuration revision, normalization policy, and report period. A change to source, mapping, normalization configuration or policy, or report period MUST make earlier validation ineligible for current confirmation. Missing, foreign, or mismatched report/source pairs SHALL yield indistinguishable `404 resource_not_found` responses. Validation and preview responses MUST exclude internal object keys, credentials, unrestricted original content, and source cell values in issue messages. Review operations MUST NOT confirm an import, create canonical data or metrics, or start analysis.

#### Scenario: Source or period changes after validation
- **WHEN** the current source or inclusive report period changes after a validation succeeded
- **THEN** the prior result remains historical but cannot authorize confirmation of the changed input
- **AND** the changed input requires fresh validation and explicit confirmation.

#### Scenario: Another owner requests review
- **WHEN** a principal requests configuration or validation for a foreign report or source
- **THEN** the API returns the same safe `404 resource_not_found` shape as for an absent resource
- **AND** it reveals no source metadata or validation issues.
