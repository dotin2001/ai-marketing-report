## 1. Metric storage and grouping

- [x] 1.1 Add an Alembic migration and model fields for non-null metric group identity, campaign label, and safe uniqueness across result set, metric, group, and currency scope; verify upgrade/backfill, PostgreSQL constraints, and lossless downgrade where applicable in `backend/tests/integration/db/test_migrations.py` and `test_datasets_and_metrics.py`.
- [x] 1.2 Define `kpi-v1` result ordering and semantic result-set identity from confirmed canonical identity, calculation version, and group contract; verify repeated input yields the same identity and distinct groups/versions differ in processing unit tests.

## 2. Deterministic calculation

- [x] 2.1 Implement whole-report-period and exact campaign grouping over confirmed canonical rows in `backend/app/processing/`; verify aggregate CTR `2/110`, duplicate-row inclusion, represented currencies, and no unmapped/source-claim inputs in `backend/tests/unit/processing/test_kpi_calculation.py`.
- [x] 2.2 Implement CPC, CPM, and CPL per currency with exact `Decimal` totals, at least 28-digit context, and at least 12 significant digits for non-terminating quotients; verify exact `0.10` CPC, `333.333333333...` CPM, and USD/EUR partition golden cases in `test_kpi_calculation.py`.
- [x] 2.3 Implement available/unavailable result variants for missing inputs, zero denominators, true zero numerator, invalid canonical input, and cross-currency spend requests; verify every golden case omits forbidden value/unit or reason fields as appropriate in `test_kpi_calculation.py`.
- [x] 2.4 Add compatible-period comparison over stored result provenance and return `incomparable_period` with safe mismatch details for differing duration, boundary policy, definition/version, mapping/policy, scope, or currency; verify both compatible and incompatible golden cases in `test_kpi_calculation.py`.

## 3. Confirmation and persisted results

- [x] 3.1 Extend validation and confirmation schemas/services with total, accepted, and rejected record counts and whole-revision rejection explanation; verify blocked reviews report `0/total` accepted/rejected, successful confirmation reports `total/0`, and duplicate rows count once per source record in import review and confirmation contract tests.
- [x] 3.2 Persist metric sets, results, exact inputs, and represented currencies through an owner-scoped domain service and attach them in the confirmation transaction only for the current dataset; verify calculation failure rolls back confirmation and no partial current metrics remain in `backend/tests/integration/processing/test_confirmed_import.py`.
- [x] 3.3 Handle equivalent reruns, confirmation replay, concurrent attempts, and input invalidation with database uniqueness and transactional current-reference checks; verify one logical result set, historical preservation, and stale-result rejection in PostgreSQL integration tests.

## 4. Dataset and metric API

- [x] 4.1 Implement `/api/v1` current/detail dataset and paginated canonical-row reads with strict Pydantic schemas and owner-scoped repositories; verify stable row order, canonical-only fields, count/provenance fields, and identical absent/foreign `404` responses in `backend/tests/contract/api/test_datasets_and_metrics.py`.
- [x] 4.2 Implement dataset metric reads with report-period/campaign and currency filters, deterministic ordering, exact decimal strings, and available/unavailable discriminated responses; verify runtime/OpenAPI contract, mixed-currency unavailability, safe errors, and no foreign totals or internal keys in `test_datasets_and_metrics.py`.

## 5. Stage verification and handoff

- [x] 5.1 Run `cd backend && .venv/bin/python -m pytest tests/unit/processing/test_csv_import.py tests/unit/processing/test_normalization.py tests/unit/processing/test_kpi_calculation.py tests/contract/api/test_import_review_routes.py tests/contract/api/test_import_confirmation_routes.py tests/contract/api/test_datasets_and_metrics.py -q`; record exact result and resolve failures.
- [x] 5.2 Against an isolated PostgreSQL test database, run `cd backend && .venv/bin/python -m pytest tests/integration/processing/test_confirmed_import.py tests/integration/db/test_datasets_and_metrics.py tests/integration/db/test_migrations.py -q`; verify migration upgrade, owner isolation, atomicity, and retries, and record any unavailable gate.
- [x] 5.3 Run `backend/.venv/bin/ruff check backend`, `backend/.venv/bin/ruff format --check backend/app backend/tests backend/alembic`, `backend/.venv/bin/mypy backend/app`, the full PostgreSQL-backed backend test suite, and `openspec validate gh-12-implement-dataset-confirmation-and-kpi-aggregati --strict --json`; record exact outcomes, including anything not run, before handoff.

## Verification record

- Focused unit and API contract command (5.1): 39 passed.
- Focused isolated PostgreSQL command (5.2): 19 passed; migration upgrade, populated backfill, lossless downgrade/upgrade, owner isolation, atomic rollback, and concurrency assertions passed.
- Full isolated PostgreSQL-backed backend suite: 326 passed, 2 live storage tests deselected with `-m 'not storage_live'`. Live object-storage tests were not run.
- `ruff check backend`: passed. `ruff format --check backend/app backend/tests backend/alembic`: 113 files already formatted. `mypy backend/app`: 54 source files, no issues.
- `openspec validate gh-12-implement-dataset-confirmation-and-kpi-aggregati --strict --json`: valid, zero issues. `git diff --check`: passed.
