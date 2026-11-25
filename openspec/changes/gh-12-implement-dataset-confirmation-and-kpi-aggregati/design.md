## Context

See `proposal.md` for motivation and `specs/confirmed-dataset-kpi-aggregation/spec.md` for behavior. Issue #11 already provides exact-revision CSV confirmation and atomic canonical dataset commitment in `backend/app/domain/import_confirmation.py` and `backend/app/domain/datasets.py`. Validation stores `total_records` and located issues; confirmation exposes `row_count`. `backend/app/db/models.py` already has metric result-set, result, input-total, and represented-currency tables, but no calculation service or dataset/metric routes. A metric result's current `scope` and nullable currency uniqueness do not uniquely identify arbitrary campaign groups.

## Goals / Non-Goals

**Goals:**

- Bind calculations to one confirmed dataset and `kpi-v1`, persist one result set for a semantic input, and attach it only while that dataset is current.
- Make whole-report-period and canonical campaign groups explicit and safely queryable, with currency partitions for spend results.
- Add row accounting without weakening the existing confirmation gate.

**Non-Goals:**

- Arbitrary date buckets or custom comparison policy, partial-row acceptance, AI interpretation, frontend charts, and recalculating old versions in place.

## Decisions

1. **Treat “by period” as the confirmed report's inclusive reporting period; expose campaign groups within that period.** The dataset is already constrained to this period. Introduce a stable non-null group identity and campaign label on metric results, with a database uniqueness constraint covering result set, metric, group, and currency scope. A migration is required because the existing nullable-currency uniqueness permits duplicates and `scope` alone cannot distinguish campaigns. A later change can add finer date buckets with a separate contract. Alternative: encode campaign names in `scope`; rejected because its 64-character limit and collation/escaping would make identity unsafe.
2. **Calculate in a pure processing function and persist through a domain service.** The function accepts canonical rows, computes integer and `Decimal` totals, partitions by canonical campaign and currency, and emits ordered available/unavailable results. `kpi-v1` is an explicit calculation version. The domain service checks owner and current confirmation, writes the set and inputs in one transaction, and compare-and-sets the current metric reference under a report lock. Database uniqueness and a semantic identity derived from canonical-data identity, version, and scope contract resolve concurrent reruns. Alternative: calculate during GET; rejected because results need stable identities and immutable provenance for analysis and versions.
3. **Keep confirmation atomic with the metric transition.** Extend the confirmation service to calculate and persist metrics from the same canonical rows before committing the current dataset and metric references. If calculation or persistence fails, the transaction rolls back. Existing idempotent confirmation replay returns the original confirmation and metric identity; no second set is created. The metric read path can repair a historical confirmed dataset's missing result set only through the same idempotent service, without attaching it as current unless freshness still holds. Alternative: asynchronous KPI job; rejected because deterministic calculation is required before `analysis_ready` and has no external dependency.
4. **Expose counts as accounting, not partial success.** Validation derives its blocking state from stored issues and reports `total_records` with safe record-level error locations. A blocked validation reports zero accepted and all source records rejected for confirmation, explicitly labeling this as whole-revision rejection. Confirmation and dataset responses add `accepted_row_count = row_count`, `rejected_row_count = 0`, and a concise all-records-accepted explanation. Alternative: count individually valid rows as accepted in a failed revision; rejected because it implies partial confirmation.
5. **Centralize owner-scoped reads and response schemas.** Add dataset detail/current, canonical row pagination, and metric reads under the existing `/api/v1/reports/{report_id}/datasets/...` paths. Authorize owner and parent before query/filter validation that could reveal metadata. Serialize exact decimals as strings, enforce available/unavailable Pydantic variants, and order rows by source-record index with stable tie-breakers. `MetricQuery` selects report-period or campaign scope and optional currency; a report-wide mixed-currency spend request returns `incompatible_currency`. Alternatives: direct ORM serialization or a new endpoint family; both would conflict with current API conventions.
6. **Keep period comparison as a deterministic contract utility.** Compare stored result identities only after matching inclusive duration, boundary policy, metric definition, calculation version, mapping/policy, scope, and currency. Return `incomparable_period` with safe mismatched attributes otherwise. No new comparison route is introduced in this stage; the utility and golden tests support later analysis without inventing a public API.

## Risks / Trade-offs

- [Large campaign cardinality expands result rows] → Bound work by the existing CSV record limit, use one pass for grouping, and test the maximum supported group shape without unbounded response payloads.
- [Concurrent confirmation or recalculation duplicates results] → Use report row locking, semantic identity uniqueness, and transactional attachment; verify repeated and concurrent calls against PostgreSQL.
- [Historical metric schema changes affect existing rows] → Migrate with a stable default group key for existing report-period results, then add non-null identity and uniqueness after checking duplicate historical rows. Preserve immutable historical identities and use a safe rollback only if lossless.
- [Decimal persistence loses precision] → Specify database numeric scale/precision based on `kpi-v1` output bounds, round only at the storage boundary if required by the versioned calculation contract, and assert exact totals and at least 12 significant quotient digits through API tests.

## Migration Plan

1. Add the Alembic migration for explicit group identity and campaign scope, with deterministic backfill and upgraded uniqueness/constraints; verify upgrade on an isolated PostgreSQL database and downgrade only where lossless.
2. Deploy processing and service changes with the route/schema additions. Existing confirmed datasets remain readable; calculate missing results idempotently while preserving source and confirmation history.
3. Roll back application code only after confirming compatibility with the migrated schema; avoid deleting historical metric results or datasets.
