## Purpose

Let a report owner freeze an exact saved draft, inspect its ordered history, and continue editing from an older snapshot without changing historical records.

## ADDED Requirements

### Requirement: Create an immutable numbered version from the current draft
The system SHALL accept `POST /api/v1/reports/{report_id}/versions` only for the authenticated report owner, with an expected active draft revision and an idempotency key. A successful request SHALL return `201` with one positive, report-local sequential version number and an immutable snapshot of the exact saved revision. The snapshot SHALL preserve report metadata, period, source identity and checksum, confirmed input and canonical-data identity where applicable, deterministic metrics and availability reasons, validated analysis and its model/prompt/request provenance, edited objectives and narrative, labeled claims, limitations, chart declarations, template version, and creation time. A confirmed text-only source SHALL explicitly carry no fabricated dataset or metrics. A draft save alone SHALL NOT create a version.

#### Scenario: Current structured draft is versioned
- **WHEN** the owner versions the current revision with compatible confirmed source, dataset, metrics, analysis, and chart references
- **THEN** the API returns `201` with the next report-local version and a snapshot bound to those exact inputs
- **AND** later draft or input changes leave the saved snapshot unchanged

#### Scenario: Confirmed text draft is versioned
- **WHEN** the owner versions a current draft backed by an explicitly confirmed text source
- **THEN** the snapshot preserves its source checksum and labeled content, with dataset and metric bindings explicitly absent

#### Scenario: Stale or incompatible draft is rejected
- **WHEN** the expected active revision is stale or a source, confirmation, metric, analysis, or chart binding is incompatible with the current report
- **THEN** the API returns a safe `409` conflict and commits no partial version or sequence number

### Requirement: Version creation and restoration are retry safe
The system SHALL bind each creation or restoration idempotency key to the owner, report, operation, and command fingerprint. Repeating the same key and command SHALL return the original result; using the key for another command SHALL return an idempotency conflict. Concurrent version requests SHALL NOT create duplicate numbers, conflicting snapshots, or gaps from rolled-back transactions. Neither version creation nor restoration SHALL mutate a committed version, its snapshot, or a prior PDF export.

#### Scenario: Creation request is replayed
- **WHEN** the owner repeats the same version command with the same idempotency key
- **THEN** the API returns the original version without creating another number

#### Scenario: Idempotency key is reused for a different command
- **WHEN** the owner sends a different version or restore command with a previously bound key in the same scope
- **THEN** the API returns `409` with a stable `idempotency_conflict` code and changes no draft or version

#### Scenario: Concurrent creation requests race
- **WHEN** two valid requests try to version one report concurrently
- **THEN** committed versions have distinct contiguous report-local numbers and coherent immutable snapshots

### Requirement: Owners can list and retrieve safe version history
The system SHALL provide owner-scoped `GET /api/v1/reports/{report_id}/versions` with deterministic descending version-number order and stable cursor pagination, and `GET /api/v1/reports/{report_id}/versions/{version_id}` for detail. A summary SHALL expose the version identity and number, source draft identity and revision, template version, creation time, provenance summary, and PDF export summary. Detail SHALL expose the immutable report snapshot needed for reproduction, while withholding internal object keys, credentials, signed URLs, and unrestricted original source content. Historical schema 1 snapshots SHALL remain readable without invented schema 2 bindings.

#### Scenario: Owner browses history after editing
- **WHEN** the owner lists and opens an earlier version after later draft or source changes
- **THEN** the API returns the original ordered version and its unchanged snapshot

#### Scenario: Foreign or unknown version is requested
- **WHEN** a principal lists another owner's report or retrieves a version outside the owned report
- **THEN** the API returns `404` without revealing ownership or resource details

### Requirement: Restore history into a new active draft
The system SHALL accept `POST /api/v1/reports/{report_id}/versions/{version_id}/restore` only for the owner with an idempotency key and the expected current active draft identity and revision. A successful restore SHALL return `200` with a new mutable active draft identity and revision, copying saved editable objectives, narrative, limitations, labeled claims, and compatible chart declarations from the selected snapshot. It SHALL leave the selected and all other versions, datasets, and exports unchanged. Later edits to the new draft SHALL use the ordinary draft concurrency rules.

#### Scenario: Older version is restored
- **WHEN** the owner restores an older version using the current active draft identity and revision
- **THEN** a new active draft contains the saved editable content and existing history remains unchanged

#### Scenario: Restore revision is stale
- **WHEN** another edit or restore has replaced or advanced the expected active draft
- **THEN** the API returns `409` with `revision_conflict` and does not replace the current draft or change history

#### Scenario: Restore request is replayed
- **WHEN** the owner repeats the same restore command with the same idempotency key
- **THEN** the API returns the original restored draft rather than creating another draft
