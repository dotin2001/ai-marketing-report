## 1. Version and chart persistence

- [x] 1.1 Add an Alembic migration and SQLAlchemy fields for owner/report-consistent dataset, metric-result-set, and analysis-result bindings on report versions; verify upgrade, model parity, foreign-key rejection, retained immutability triggers, and repeat upgrade against PostgreSQL.
- [x] 1.2 Add revisioned, ordered draft chart configuration storage and compare-and-set updates with bounded types and metric references; verify valid edits advance the draft revision and stale or invalid edits leave it unchanged.
- [x] 1.3 Add schema 2 snapshot models for explicit dataset/result identities and safe chart declarations while preserving schema 1 validation for existing rows; verify unit tests reject forbidden keys, numeric overrides, missing metric references, and invalid structured/text-only combinations.

## 2. Immutable dataset commitment

- [x] 2.1 Implement an owner-scoped domain transaction that commits a dataset and canonical rows only for the current error-free confirmed CSV input; verify tests cover exact source/configuration/policy/period identity, row provenance, currencies, and atomic rejection.
- [x] 2.2 Make same-identity commitment idempotent after full provenance and row comparison, and retain old datasets when a new confirmation becomes current; verify PostgreSQL tests for replay, changed inputs, direct update/delete rejection, and historical reads.

## 3. Coherent report versions

- [x] 3.1 Implement a domain save service that locks the report, checks the expected active draft revision and owner, reads current source/dataset/metric/analysis records and ordered draft content/charts, and builds the schema 2 snapshot; verify mismatched, stale, or foreign references fail without a version insert.
- [x] 3.2 Bind the validated snapshot and relational IDs in one idempotent version transaction with sequential numbering; verify PostgreSQL tests for same-key replay, different-command key conflict, concurrent saves, no number gaps, and database update/delete rejection.
- [x] 3.3 Extend owner-scoped history and restoration to read both snapshot schemas, require expected current draft revision and scoped idempotency, and copy only editable content/charts to a new active draft; verify prior versions, datasets, and PDFs remain unchanged and foreign IDs disclose nothing.
- [x] 3.4 Verify PDF export identity derives solely from the selected saved version and template, including after draft edits, dataset replacement, restoration, and export retry; use a focused PostgreSQL integration test without implementing PDF rendering.

## 4. Stage verification and documentation

- [x] 4.1 Document the schema 2 snapshot, new migration and any required command or environment changes in project documentation; verify examples and historical schema 1 compatibility against tests.
- [x] 4.2 Run focused unit and PostgreSQL integration suites, then the backend stage formatting, lint, type-check, migration, and database suites; record exact commands, outcomes, and any unavailable gate before handoff.
