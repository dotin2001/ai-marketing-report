## Context

See `proposal.md` and `specs/import-preview-and-validation-feedback/spec.md`. Source intake already provides `/api/v1/reports/{report_id}/sources/{source_id}/preview` and stores exact CSV bytes privately. Its CSV envelope exposes ordinal headers, indexed rows, and total records, but no mapping or semantic validation exists. The database already has import configuration, revision, mapping, validation, and validation-issue tables and a repository helper for compare-and-set revision updates. The active API and import specs define the route family and issue taxonomy. Backend processing currently has only source-envelope parsing; pandas normalization is still to be added.

## Goals / Non-Goals

**Goals:**

- Use one source identity and revision-bound validation result across preview, mapping, and feedback.
- Make the complete-data validation outcome deterministic and safe to display without exposing cell values.
- Reuse existing owner-scoped persistence and storage boundaries, adding a migration only if the existing schema cannot support the contract.

**Non-Goals:**

- Confirmation endpoint, canonical dataset commit, metric calculation, or analysis execution.
- Frontend implementation or changing pasted text into structured data.

## Decisions

### 1. Keep source preview separate from validation

The existing GET preview remains a bounded projection of immutable source bytes. It keeps `total_records`, column ordinals, and indexed samples while clearly signaling `validation_status: unvalidated`. Validation reads the entire verified CSV through the storage abstraction and returns a separate result for the exact configuration revision. The alternative of validating only previewed rows would miss later errors and make the confirmation gate unsound.

### 2. Establish a configuration on first PUT and append revisions thereafter

The owner-scoped import service checks that the report's current source is the requested CSV and creates one configuration with revision 1 for the first valid structural request. Later PUT requests use `expected_revision` and append a revision transactionally. Store the explicit normalization policy version and optional date format on each revision. Continue to use zero-based source ordinals as mapping keys, including repeated headers. Reject unknown fields, out-of-range ordinals, duplicate source ordinals or canonical fields, and unsupported date-format settings with the standard `422 validation_failed` issue details; database uniqueness remains a backstop. Permit an incomplete but structurally valid mapping revision so validation can return `missing_required_mapping` and `missing_measure_mapping` feedback. The current `append_import_revision` helper prechecks required fields and has no date-format argument, so it must be adjusted in this stage. A route-level-only mapping object would lose revision identity and stale-write protection.

### 3. Validate in a pure processing step, then persist one snapshot

Use the existing CSV parser to retain original ordinals and record indexes; normalize mapped fields with an explicit versioned policy in `backend/app/processing/`. Use pandas only inside that layer and exact decimal parsing for spend, not binary floats. Walk every source record, keeping original values only in the local parse context. Apply the project's full issue taxonomy and deterministic ordering: structural/mapping issues first, then row issues by record index and column ordinal, then dataset warnings. Detect duplicate rows from valid canonical values and report both record indexes. Count errors and warnings from the produced issues and derive `confirmation_blocked` from `error_count > 0`.

Persist an `ImportValidation` and ordered `ImportValidationIssue` rows transactionally for the captured source checksum, current configuration revision, policy version, and report period revision. Add `source_checksum`, `period_start`, `period_end`, `period_revision`, and `total_records` to the validation table through Alembic because the current table does not retain these inputs or the complete record count. Existing validation rows, if any, need a safe migration strategy: derive source checksum and period from their linked configuration/report only where sound; otherwise mark them historical and ineligible for confirmation. A repeated identical validate request can return the persisted result when its semantic inputs match. The API should return the same representation from persisted rows. No canonical dataset or metric is written. An alternative streaming result without persistence would not support the later exact-revision confirmation gate.

### 4. Recheck freshness at the transaction boundary

The service authenticates owner/report/source before storage access and captures source checksum, report period and revision, and configuration revision. It validates outside a long database transaction, then locks the report/configuration and rechecks these inputs before inserting the result. A mismatch returns `409 revision_conflict` or `stale_input` without making the result current. New source attachment or report-period update already invalidates current confirmation references; validation must not restore them. Ownership checks return the same `404 resource_not_found` for absent and foreign resources.

### 5. Bound feedback without suppressing errors

The API must communicate every blocking issue or provide a deterministic paginated issue collection tied to the immutable validation ID; truncating an issue list while reporting `confirmation_blocked: false` would be misleading. The baseline API contract asks for all stable issues in validation responses, so this stage will return all issues under the configured CSV record cap and enforce a safe response-size policy that fails explicitly if the complete list cannot fit. Persisted issue rows remain available for a later paginated read extension if limits prove insufficient. Messages use stable templates and locations, never original cell values, filenames, object keys, or provider details. Logs include only identifiers and counts.

## Risks / Trade-offs

- **[Large files create many issues and a large response]** → Respect existing source byte and record caps, fail explicitly on response limit instead of hiding issues, and keep deterministic ordering; later pagination requires a contract change.
- **[Validation races with a new source or revision]** → Capture and recheck semantic inputs under row locks before persisting; stale results cannot authorize confirmation.
- **[Existing repository helper assumes complete mappings]** → Move completeness into validation while retaining structural checks and database uniqueness; test incomplete and duplicate mappings separately.
- **[Parser and pandas may differ on types or blank cells]** → Use original CSV strings and explicit conversion rules; test representative edge cases against the existing import-spec matrix.

## Migration Plan

1. Migrate validation rows to retain source checksum, period snapshot and revision, and total records; verify upgrade and safe treatment of any preexisting rows. Add processing, service, schemas, and routes; update repository helpers for incomplete mappings and date format.
2. Keep source intake and existing preview response compatible. Existing CSV sources can be reviewed without backfill; their first configuration begins at revision 1.
3. Rollback removes new review routes and service wiring. Historical validation rows can remain without affecting immutable sources or reports.
