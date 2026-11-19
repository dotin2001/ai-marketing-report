## Purpose

Enable report owners to attach and review bounded CSV files or pasted tabular text while preserving original input and provenance before any mapping, confirmation, or calculation.

## ADDED Requirements

### Requirement: Owner-authorized source intake
The API SHALL accept one CSV file at `POST /api/v1/reports/{report_id}/sources/csv` and unchanged Unicode content at `POST /api/v1/reports/{report_id}/sources/text`. Each accepted request MUST create an immutable, owner-scoped source intake record with source type, byte size, SHA-256 checksum, creation time, and original-input reference. The API SHALL return `201` with a `SourceDetail` in the standard single-resource envelope. It MUST authorize the report owner before attachment and return indistinguishable `404 resource_not_found` responses for absent and foreign reports.

#### Scenario: Owner attaches a CSV
- **WHEN** an authenticated owner uploads one valid CSV to an existing report
- **THEN** the API creates one immutable CSV source and returns its safe metadata with HTTP `201`
- **AND** the report's current source becomes that source in `source_review`.

#### Scenario: Owner pastes a table
- **WHEN** an authenticated owner submits non-empty Unicode tabular content to an existing report
- **THEN** the API preserves the content unchanged as a text source with its checksum and returns HTTP `201`
- **AND** the content remains untrusted, unvalidated source material rather than canonical metric input.

#### Scenario: Missing or foreign report
- **WHEN** a principal submits a source to a nonexistent or another owner's report
- **THEN** the API returns the same `404 resource_not_found` shape in both cases
- **AND** it creates no source or stored object.

### Requirement: Bounded CSV and text input validation
The CSV intake SHALL enforce a configured maximum byte size and maximum data-record count before accepting the source. It SHALL require exactly one non-empty multipart file, a declared CSV media type consistent with detected comma-delimited CSV content, UTF-8 decoding with an optional BOM, and a parseable header record. It SHALL retain duplicate header names as distinct ordinal columns. A header-only CSV SHALL remain reviewable and receive a blocking `empty_dataset` issue at later import validation. Pasted text SHALL enforce a configured UTF-8 byte limit and reject empty content. Intake MUST reject malformed CSV syntax, unsupported type or encoding, and limit breaches without creating a current or partial source; JSON errors SHALL use the existing safe error envelope and `payload_too_large`, `unsupported_media_type`, `unsupported_encoding`, or `validation_failed` as applicable.

#### Scenario: Upload crosses byte or record limit
- **WHEN** an upload exceeds the configured byte or data-record limit
- **THEN** intake rejects it with a safe limit error and no source becomes current
- **AND** no confirmed import, canonical dataset, job, or public object reference is created.

#### Scenario: Unsupported or malformed input
- **WHEN** the file is empty, has a conflicting declared or detected type, cannot be decoded as supported UTF-8, or contains malformed CSV syntax
- **THEN** intake rejects it with the applicable stable error code and safe details
- **AND** rejected source bytes and cell values are not echoed in the error.

#### Scenario: Header-only or repeated headers
- **WHEN** a valid CSV has a header but no data record, or repeated header names
- **THEN** intake preserves the original and exposes every header by ordinal for review
- **AND** the header-only source cannot be confirmed as a dataset under the existing `empty_dataset` rule.

### Requirement: Exact preservation and safe provenance
The system SHALL preserve accepted CSV bytes unchanged in private object storage and pasted Unicode content unchanged in the source record. It SHALL bind a CSV source to an owner/report-scoped object reference and persist the byte count, checksum, encoding, media type, untrusted original filename, and normalized display filename. General API responses SHALL label any exposed original filename as untrusted and provide a normalized display filename; internal object keys and credentials MUST NOT appear. A failure between storage and database acceptance MUST leave no current partial source and MUST compensate any object created solely for the failed request when safe to do so.

#### Scenario: Original input is retained
- **WHEN** an accepted source is retrieved through its owner-authorized record
- **THEN** its preserved original has the recorded byte count and checksum
- **AND** a preview never changes or replaces that original.

#### Scenario: Unsafe filename is supplied
- **WHEN** a CSV filename contains path segments or other unsafe display characters
- **THEN** its original value is retained and labeled as untrusted metadata and the API presents a normalized display filename
- **AND** the filename never determines an object-storage key or filesystem path.

#### Scenario: Persistence fails after upload
- **WHEN** storage succeeds but the source transaction fails
- **THEN** the report keeps its previous current source and no partial source is visible
- **AND** an object created solely by that request is removed through the storage abstraction when safe.

### Requirement: Authorized bounded source detail and preview
The API SHALL provide `GET /api/v1/reports/{report_id}/sources/{source_id}` and `GET /api/v1/reports/{report_id}/sources/{source_id}/preview` for the owning principal. Source detail SHALL expose only safe metadata. A CSV preview SHALL return a bounded set of columns and rows with original headers, zero-based source-column ordinals, one-based data-record indexes, truncation status, and an unconfirmed mapping suggestion where available. A text preview SHALL return a bounded excerpt labeled unvalidated; pasted claims MUST remain distinguishable from computed metrics. Preview content SHALL be treated as inert data, with no formula execution, and MUST NOT include unrestricted source content or internal object keys. Missing, foreign, or mismatched report/source pairs SHALL return the same `404 resource_not_found` shape.

#### Scenario: CSV preview preserves identities
- **WHEN** the owner previews a CSV with duplicate headers and more records than the preview bound
- **THEN** each column retains its ordinal and original header, each returned row has its one-based record index, and `truncated` is true
- **AND** the preview does not imply mapping confirmation.

#### Scenario: Text preview is bounded
- **WHEN** the owner previews pasted tabular text longer than the excerpt bound
- **THEN** the API returns only the bounded excerpt and `truncated: true`
- **AND** any figures or formula-like content remain labeled unvalidated source data.

#### Scenario: Foreign source cannot be previewed
- **WHEN** a principal requests another owner's source or pairs a source with the wrong report
- **THEN** the API returns `404 resource_not_found` without revealing source metadata or bytes.

### Requirement: Idempotent attachment and lifecycle safety
Both source-attachment routes SHALL require an `Idempotency-Key` scoped to the owner, operation, and report and bound to the semantic request fingerprint. An equivalent replay MUST return the original source with `Idempotency-Replayed: true`; reuse for different input MUST return `409 idempotency_conflict`. Concurrent submissions with one key MUST create at most one logical source and one current-source transition. A newly accepted source SHALL invalidate current confirmation, dataset, metric, and analysis eligibility while preserving historical immutable resources. Attachment MUST NOT confirm a mapping, create canonical rows or metrics, or start analysis.

#### Scenario: Equivalent upload is retried
- **WHEN** the owner repeats the same attachment with the same key and equivalent content
- **THEN** the API returns the original source and replay header
- **AND** no duplicate source, asset, or current-state transition is created.

#### Scenario: Key is reused with different content
- **WHEN** the same scoped key is submitted with different source content or semantic metadata
- **THEN** the API returns `409 idempotency_conflict`
- **AND** neither source nor current report state changes.

#### Scenario: New source supersedes prior current input
- **WHEN** an owner attaches a new accepted source to a report with a previously confirmed source
- **THEN** the report returns to `source_review` and current dataset, metric, and analysis eligibility are cleared
- **AND** the earlier source, confirmed data, and immutable versions remain available under their authorized historical identities.
