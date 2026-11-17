## Context

See `proposal.md` for motivation and `specs/immutable-report-versions-and-dataset-revisions/spec.md` for behavior. Stage 2 already supplies `CanonicalDataset`, `CanonicalRow`, `ReportVersion`, owner-scoped repositories, a JSONB snapshot validator, idempotency records, and PostgreSQL triggers that reject changes to immutable tables. The version repository currently accepts a caller-built snapshot and checks its hash, report metadata, and draft revision, but does not construct it from locked current records or verify dataset, metric, analysis, and chart coherence. `ReportVersionSnapshot` schema 1 has a canonical identity but no dataset ID or chart configuration. The repository contains no general report API implementation yet.

## Goals / Non-Goals

**Goals:**

- Make the domain service, rather than a caller-provided snapshot, authoritative for selecting and validating saved inputs.
- Keep source, dataset, result, draft, and version references consistent under concurrent edits and retries.
- Make chart configuration reproducible without storing raw source content or derived arithmetic in the chart declaration.

**Non-Goals:**

- Parsing CSV, calculating KPIs, generating AI content, rendering PDFs, or adding HTTP routes in this change.
- Rewriting historical schema 1 snapshots or allowing mutation of committed source, dataset, result, or version records.

## Decisions

### 1. Commit datasets through an owner-scoped transaction

Introduce a domain service for dataset commitment that reads the current confirmation and its exact validation/configuration/source under a report-level lock, checks error-free status and row provenance, and inserts the canonical dataset, currencies, and rows atomically. Replays for the same canonical identity resolve to the existing dataset only after comparing full provenance and row identity; a conflict fails closed. A changed current input must use a new confirmation and canonical identity. This reuses the existing append-only tables and triggers. A mutable dataset table or in-place row replacement would break version history.

### 2. Assemble the version snapshot inside a locked domain transaction

The save service first resolves the idempotency record using owner, operation, report, key, and command fingerprint. It locks the report, checks the expected active draft revision, then reads its ordered content and current source/confirmation/dataset/result references. It verifies owner/report alignment, confirmation currency and period, canonical identity, metric calculation provenance, and analysis semantic identity before creating a typed snapshot. It rejects stale or incomplete references. The repository's current `create_report_version` becomes a narrow persistence primitive called only with the validated snapshot. The report lock serializes version numbering, while unique constraints and the idempotency record defend against duplicate requests. The command fingerprint includes the expected revision and selected input identities, so key reuse with a different command conflicts.

### 3. Use a new snapshot schema for explicit bindings and charts

Define snapshot schema 2 with `dataset_id` and explicit metric-result-set and analysis-result identities where applicable, plus ordered chart declarations. A chart declaration uses a bounded chart type, title/labels, scope, and metric IDs that exist in the snapshot; it contains no numeric override or arbitrary configuration blob. The version snapshot still embeds the safe metric values and edited content needed for deterministic PDF rendering, while relational IDs and immutable source/confirmed-data records retain deeper provenance. Validate stored schema 1 snapshots through their existing validator and schema 2 through the new validator; new saves use schema 2. The public-safe forbidden-key check remains recursive. An unversioned optional field on schema 1 would blur compatibility and make old snapshots appear to have charts that were never saved.

### 4. Add narrow relational binding only where it closes a gap

Add nullable owner/report-consistent `dataset_id`, `metric_result_set_id`, and `analysis_result_id` references on `report_versions` through Alembic. Nulls represent text-only or absent analysis; schema 2 structured versions require a dataset binding in the typed snapshot and domain service. The service still checks semantic compatibility, since foreign keys cannot prove calculation or analysis freshness. Keep preexisting rows nullable and schema 1 readable; do not backfill guessed IDs from JSON. The migration retains update/delete rejection for committed rows and verifies the new constraints on PostgreSQL. A pure JSONB-only binding would make cross-aggregate references depend entirely on application code.

### 5. Restore and export from saved state

Keep history reads owner-scoped and ordered by version number and ID. Extend restoration to require the expected current draft revision and idempotency key at the domain boundary, copy only editable content and valid presentation configuration into a new active draft, and leave deterministic metrics and version-bound data immutable. Existing PDF export creation continues to derive its input identity from the selected version snapshot and template; it never reads the active draft or chooses a new dataset.

## Risks / Trade-offs

- [Schema 1 versions lack explicit chart and dataset IDs] → Preserve schema 1 as historical records and expose only its actually stored content; require schema 2 for all new versions.
- [A confirmation can become stale between lookup and insert] → Lock the report, recheck current identities in the transaction, and use unique constraints for races.
- [A snapshot can be internally well-formed but cite the wrong immutable result] → Build it from owner-scoped database records and assert source, confirmation, dataset, metric, and analysis relationships before insert.
- [Chart declarations could become a second arithmetic source] → Reference included metric IDs only and prohibit numeric overrides.

## Migration Plan

Add an Alembic revision for any new version bindings and draft chart storage, with safe nullable columns for existing versions. Verify upgrade from the current head, metadata parity, immutability triggers, and a repeat upgrade. Downgrade only where it is lossless; if schema 2 data uses new columns, document the destructive rollback limit and rely on forward repair. Release the service after the migration so new writes always include the new snapshot schema.
