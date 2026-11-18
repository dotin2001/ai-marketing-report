## Purpose

Provide owner-authorized report management over the v1 API so clients can create and find reports, change their metadata and objectives safely, and page through report summaries.

## ADDED Requirements

### Requirement: Create a validated report
`POST /api/v1/reports` SHALL require an authenticated principal, an `Idempotency-Key` header, and a strict body containing `name`, `period.start_date`, `period.end_date`, and `objectives`. The server SHALL trim the name to 1–200 Unicode characters and each objective to 1–2,000 Unicode characters, require 1–20 objectives, require `YYYY-MM-DD` dates with an inclusive end on or after the start, and reject unknown fields. Success SHALL return `201` and `{ "data": ReportDetail }` with a new owner-scoped report in `created` stage and one active draft at revision `1`, without creating a source, job, version, or export. The key SHALL match `[A-Za-z0-9._:-]+` and contain 1–128 characters; its owner-and-operation scope SHALL bind a canonical semantic request fingerprint.

#### Scenario: Valid creation
- **WHEN** an authenticated principal submits a valid report and a new idempotency key
- **THEN** the API returns `201` with the normalized report, its objectives, and active draft revision `1`
- **AND** the report has no current source, dataset, analysis, version, or export

#### Scenario: Invalid creation fields
- **WHEN** the name or an objective is blank or over its bound, objectives are absent or exceed 20, a date is malformed, the end precedes the start, or an undeclared property is submitted
- **THEN** the API returns `422 validation_failed` with safe field paths and creates no report or draft

#### Scenario: Creation replay and conflict
- **WHEN** the same owner repeats a semantically equivalent valid creation with the same key
- **THEN** the API returns the original `201` result with `Idempotency-Replayed: true` and creates no duplicate
- **AND** reusing that key for a different canonical command returns `409 idempotency_conflict` without changing either result

### Requirement: List and retrieve owned reports
`GET /api/v1/reports` SHALL return only the authenticated owner's reports as `{ "data": [ReportSummary], "page": { "limit", "has_more", "next_cursor" } }`. The optional `limit` SHALL default to `25` and accept integers `1` through `100`; the optional opaque cursor SHALL page by `(created_at DESC, id DESC)` using an owner-, route-, filter-, and ordering-bound, integrity-protected boundary. `GET /api/v1/reports/{report_id}` SHALL return `{ "data": ReportDetail }` with current safe references, objectives, active draft, timestamps, and a stage derived from persisted state. Public IDs SHALL be lowercase UUIDs, dates `YYYY-MM-DD`, and instants UTC with `Z`. A cursor SHALL not grant authorization.

#### Scenario: Deterministic pages
- **WHEN** an owner pages through more reports than the requested limit
- **THEN** each page follows `(created_at DESC, id DESC)`, has the requested `page.limit`, and uses `has_more` and `next_cursor` consistently
- **AND** a report inserted before an existing page boundary does not duplicate an item on the next page

#### Scenario: Empty and final pages
- **WHEN** an owner has no matching reports or reaches the final page
- **THEN** the API returns an empty or remaining `data` array, `has_more: false`, and `next_cursor: null`

#### Scenario: Invalid pagination input
- **WHEN** `limit` is outside `1` through `100` or is not an integer
- **THEN** the API returns `422 validation_failed` without leaking report data
- **AND** a tampered, expired, wrong-owner, wrong-route, or wrong-order cursor returns `400 invalid_cursor` with no cursor internals

#### Scenario: Owner-safe detail
- **WHEN** a principal requests a missing report ID or a report owned by another principal
- **THEN** both requests return the same `404 resource_not_found` shape and no foreign metadata

### Requirement: Update report metadata with a revision gate
`PATCH /api/v1/reports/{report_id}` SHALL accept a strict body with `expected_revision >= 1` and at least one of `name` or a complete `period`. It SHALL use the same name and period validation as creation, authorize the report before returning its revision or lifecycle information, atomically compare the active draft revision and advance it once for an effective update, and return `200` with `{ "data": ReportDetail }`. It SHALL reject ownership, stage, source, metric, version, job, and other undeclared fields. An unchanged normalized value SHALL not invalidate analysis input. A changed name SHALL preserve current source confirmation, dataset, metrics, and analysis eligibility. A changed period SHALL make prior confirmation, dataset, metric, and analysis pointers non-current, require fresh review/confirmation before analysis, and retain all immutable history. A metadata update SHALL never create a version.

#### Scenario: Rename current report
- **WHEN** an owner supplies the current active draft revision and a valid different name
- **THEN** the API saves the trimmed name, advances the draft revision once, and leaves previously valid input references current

#### Scenario: Change reporting period
- **WHEN** an owner supplies the current active draft revision and a valid changed period
- **THEN** the API saves the inclusive period, advances the revision, and returns a stage that requires current source review and confirmation before new analysis
- **AND** historical datasets, analysis results, and versions remain unchanged and readable to the owner

#### Scenario: Reject stale or malformed metadata update
- **WHEN** the owner submits a stale revision, an empty update, an invalid name or period, or an undeclared field
- **THEN** stale revision returns `409 revision_conflict`; malformed content returns `422 validation_failed`
- **AND** neither response changes the report, active draft, or its current references

### Requirement: Update objectives through the active draft
`PATCH /api/v1/reports/{report_id}/draft` SHALL accept `expected_revision >= 1` and an `objectives` array under the same normalization and bounds as creation. It SHALL authorize the report first, atomically save objectives to the active draft, increment its revision once, and return `200` with `{ "data": DraftDetail }`. Objective changes SHALL invalidate any analysis result whose captured objectives revision is now stale; original sources, deterministic metric values, historical versions, and existing draft narrative SHALL remain intact. Saving objectives SHALL not create a version. Other permitted draft fields defined by the existing API contract remain outside this change's implementation scope.

#### Scenario: Save objective edit
- **WHEN** an owner submits non-blank objectives and the current active draft revision
- **THEN** the API returns the normalized objectives with the next revision and no new version

#### Scenario: Reject stale or foreign objective edit
- **WHEN** a stale revision is submitted for an owned report or any revision is submitted for a foreign report
- **THEN** the owned stale request returns `409 revision_conflict` without overwriting content, while the foreign request returns the same safe `404` as a missing report

### Requirement: Apply the shared v1 security and response contract
Every report management operation SHALL require an authenticated principal and SHALL use the approved v1 success and error envelopes, canonical scalar encodings, allowlisted error context, and safe validation detail paths. An unauthenticated request SHALL return `401 unauthenticated`. Invalid idempotency header syntax SHALL return `400 invalid_request`; missing required header SHALL return the documented safe validation error. Failed or replayed commands SHALL not create partial resources or side effects. JSON and generated OpenAPI SHALL describe the runtime request, response, status, header, pagination, and error shapes without exposing credentials, internal object keys, signed URLs, unrestricted source content, or provider details.

#### Scenario: Authentication and redaction
- **WHEN** an unauthenticated request or an invalid report mutation is sent
- **THEN** the API returns the stable safe error envelope with a request ID, retryability flag, details array, and allowlisted context
- **AND** it reveals no credentials, source values, internal keys, foreign report metadata, or raw provider errors

#### Scenario: Runtime and OpenAPI agree
- **WHEN** a valid or invalid report management request is exercised against the runtime and its generated OpenAPI contract
- **THEN** the documented schemas, statuses, headers, and field constraints match the observed response
