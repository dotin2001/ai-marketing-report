## 1. Shared normalized processing result

- [x] 1.1 Refactor `backend/app/processing/csv_import.py` to return ordered validation issues and canonical row candidates from one full-file pass while keeping `validate_csv` callers compatible; verify `backend/tests/unit/processing/test_csv_import.py` passes for repeated headers, exact duplicate rows, unmapped fields, and source-record indexes.
- [x] 1.2 Extend normalization tests for explicit date format resolution, ISO dates, trimmed campaign labels, uppercase supported currencies, whole counts, exact decimal spend, blank mapped cells, invalid values, and inclusive period bounds; verify `backend/tests/unit/processing/test_normalization.py` and `test_csv_import.py` pass without float coercion, guessing, imputation, or row loss.
- [x] 1.3 Add deterministic canonical identity encoding for source checksum, mapping and policy revision, period, and ordered canonical rows; verify same-input reruns produce the same identity and changed semantic inputs produce a different identity in processing unit tests.

## 2. Atomic import confirmation

- [x] 2.1 Add an owner-scoped domain operation that reads the exact validation and verified CSV, reproduces its issues and rows, checks warning IDs and current-source/period/revision freshness, and commits confirmation plus canonical dataset in one transaction; verify error, warning, stale, and rollback cases in `backend/tests/integration/processing/test_confirmed_import.py`.
- [x] 2.2 Use the existing idempotency record and database uniqueness constraints for equivalent replay and key conflicts; align report/configuration lock order in touched helpers and verify concurrent/repeated confirmation creates one confirmation, one dataset, and no partial current state in the PostgreSQL integration suite.
- [x] 2.3 Verify canonical rows keep distinct one-based record indexes for duplicate rows, exclude unmapped values, retain exact decimal spend, and expose all represented currencies through the confirmed mapping and dataset provenance in PostgreSQL integration tests.

## 3. API contract and authorization

- [x] 3.1 Add strict confirmation request and response schemas and `POST .../confirm` under `/api/v1/reports/{report_id}/sources/{source_id}` with required `Idempotency-Key`, safe stable errors, and replay header; verify success, blocked validation, exact warning acknowledgement, stale revision, and conflicting key in `backend/tests/contract/api/test_import_confirmation_routes.py`.
- [x] 3.2 Verify missing and foreign report/source pairs yield the same safe `404`, confirmation and error bodies exclude sensitive source and storage data, and generated OpenAPI matches runtime request, response, and error behavior in API contract tests.
- [x] 3.3 Check the active `/validate` contract against the existing `/import-configuration/validate` route; add a compatible alias if needed for declared contract coverage and verify both paths produce the same review result without changing existing clients.

## 4. Stage verification and handoff

- [x] 4.1 Run `backend/.venv/bin/python -m pytest backend/tests/unit/processing/test_normalization.py backend/tests/unit/processing/test_csv_import.py backend/tests/contract/api/test_import_review_routes.py backend/tests/contract/api/test_import_confirmation_routes.py -q` and resolve failures; record the command and result in the implementation handoff.
- [x] 4.2 Against an isolated PostgreSQL test database, run `cd backend && .venv/bin/python -m pytest tests/integration/processing/test_confirmed_import.py tests/integration/db/test_dataset_commitment.py tests/integration/db/test_import_review_service.py -q`; if a schema change was required, also run Alembic upgrade and `tests/integration/db/test_migrations.py`; record results and any unavailable gate.
- [x] 4.3 Run `backend/.venv/bin/ruff check backend`, `backend/.venv/bin/ruff format --check backend/app backend/tests backend/alembic`, `backend/.venv/bin/mypy backend/app`, the full PostgreSQL-backed backend test suite, and `openspec validate gh-11-implement-column-mapping-and-data-normalization --strict --json`; require zero strict OpenSpec issues and record exact outcomes at handoff.
