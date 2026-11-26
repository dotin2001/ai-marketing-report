## Purpose

Let a report owner attach CSV or pasted source content through the frontend while seeing accurate progress, intake limits, safe errors, and a clearly unvalidated preview.

## ADDED Requirements

### Requirement: Owner can reach the import interface for a report
The frontend SHALL provide an import route for an existing report and a way to reach it from the report listing. It MUST load the owner-authorized report before showing protected source information and MUST distinguish loading, authentication failure, missing or foreign report, and recoverable service failure. If the report has a current source, the interface SHALL show that source's safe detail and bounded preview when available.

#### Scenario: Open a report with no source
- **WHEN** an authenticated owner opens the import page for a report whose `current_source_id` is null
- **THEN** the page identifies the report and presents CSV and pasted-content attachment controls without claiming any source is confirmed.

#### Scenario: Open an existing source
- **WHEN** an authenticated owner opens the import page for a report with a current source
- **THEN** the page loads that owner-authorized source and its bounded preview and labels the content unvalidated and unconfirmed.

#### Scenario: Report is unavailable to the caller
- **WHEN** the report is absent, belongs to another owner, or authentication is missing
- **THEN** the page displays the appropriate safe unavailable or authentication state and reveals no source metadata or preview content.

### Requirement: CSV attachment shows limits and measurable progress
The frontend SHALL offer a labeled single-file CSV input and show the configured CSV byte limit and accepted CSV type before selection. It SHALL reject an empty file, a file larger than its displayed limit, or a selection whose declared type is unsupported before submission, while treating the backend as authoritative for actual content, encoding, record count, and policy. During upload it SHALL show measurable bytes or percentage when the browser reports them, distinguish transfer completion from server acceptance, and never present a completed source until the API accepts it.

#### Scenario: Valid CSV is uploaded
- **WHEN** the owner selects one CSV file within the displayed size limit and submits it
- **THEN** the frontend sends one multipart `file` to the report's CSV source endpoint with an idempotency key, shows upload and server-processing states, and shows accepted source detail only after a successful response.

#### Scenario: Browser does not report upload progress
- **WHEN** the upload transport provides no computable total or progress events
- **THEN** the page shows an indeterminate uploading status rather than an invented percentage.

#### Scenario: File fails a local bound
- **WHEN** the selected file is empty, exceeds the displayed byte limit, or declares a clearly unsupported media type
- **THEN** the page explains the selection error and does not submit it, while allowing the owner to choose another file.

### Requirement: Pasted source attachment preserves exact submitted content
The frontend SHALL offer a labeled multiline pasted-content input and show its configured UTF-8 byte limit. It SHALL reject empty content and known oversize content before submission, submit the exact entered Unicode content as JSON with an idempotency key, and retain the entered text after an intake failure. It MUST NOT parse pasted claims into metrics or suggest that attachment validates a table.

#### Scenario: Owner pastes a table
- **WHEN** the owner enters non-empty content within the displayed UTF-8 byte limit and submits it
- **THEN** the frontend sends the unchanged content to the text source endpoint and shows a submission state followed by the accepted source only after the server responds successfully.

#### Scenario: Pasted content exceeds the limit
- **WHEN** the UTF-8 encoding of entered content exceeds the displayed limit
- **THEN** the page shows the limit and current byte count, does not submit, and preserves the text for editing.

### Requirement: Intake failures are safe and retryable without duplication
The frontend SHALL normalize the API's safe error envelope and show actionable messages for `payload_too_large`, `unsupported_media_type`, `unsupported_encoding`, `validation_failed`, `idempotency_conflict`, `resource_not_found`, authentication failure, and recoverable network or service errors. It SHALL preserve the file or text on failure, prevent simultaneous repeated submits, reuse the same idempotency key for an unchanged command after an uncertain or retryable outcome, and use a new key when the semantic input changes. It MUST NOT display rejected source bytes, raw provider errors, internal object keys, or credentials in an error message.

#### Scenario: Response is lost after acceptance
- **WHEN** the upload request ends in an uncertain network failure and the owner retries without changing the file or its semantic metadata
- **THEN** the frontend reuses the original idempotency key and accepts the server's original source replay as success without creating a second source.

#### Scenario: Owner changes input after failure
- **WHEN** the owner changes the selected file or pasted content after an unsuccessful attempt
- **THEN** the next submission uses a new command identity and the prior failure does not clear the new input.

#### Scenario: Backend rejects ingestion
- **WHEN** the backend returns a supported intake error or a safe field detail
- **THEN** the page shows the safe reason and a suitable correction or retry action while retaining the entered input.

### Requirement: Accepted source preview remains bounded and untrusted
After acceptance, the frontend SHALL load and render only the owner-authorized safe source detail and bounded preview returned by the source API. It SHALL identify CSV columns by zero-based ordinal and original header, rows by one-based record index, and the preview's truncation state. It SHALL render source strings as inert text, distinguish pasted excerpts and claims from computed metrics, and display preview-loading or preview-failure states without treating the accepted attachment as failed. The interface MUST NOT imply mapping confirmation, canonical data, KPI calculation, or analysis has occurred.

#### Scenario: Duplicate CSV headers and truncated sample
- **WHEN** an accepted CSV preview contains repeated header labels and `truncated: true`
- **THEN** the page shows each header with its distinct ordinal, the returned row indexes, and a notice that only a bounded sample is displayed.

#### Scenario: Pasted content contains markup or formula-like text
- **WHEN** a pasted preview contains HTML-looking or formula-like content
- **THEN** it is displayed as inert, unvalidated source text without executing markup or formulas or presenting the claims as verified metrics.

#### Scenario: Preview fails after attachment
- **WHEN** source attachment succeeds but preview retrieval fails temporarily
- **THEN** the accepted source remains shown and the owner can retry preview loading without attaching the source again.

### Requirement: Import controls and status are accessible
The import interface SHALL provide explicit labels and descriptions for file and text inputs, keyboard-operable mode selection and retry controls, status announcements for upload and submission changes, visible focus, and responsive layout. Determinate progress MUST have an accessible value; indeterminate progress MUST have an accessible status. Reduced-motion preferences SHALL be respected.

#### Scenario: Keyboard and assistive-technology journey
- **WHEN** a keyboard or screen-reader user selects an import path, submits it, receives an error, and retries
- **THEN** focus and status messages identify the active control, failure, and recovery path without requiring pointer use or animation.
