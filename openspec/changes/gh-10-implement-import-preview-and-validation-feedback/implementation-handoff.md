## Implementation handoff

All 11 tasks are complete. The change adds revision-bound CSV import configuration,
full-record validation, persisted safe issues, and the owner-scoped review API.
Historical validation rows without source and period identity remain in the database
but cannot authorize confirmation.

## Verification

Commands were run from the repository root unless marked `cd backend`.

| Command | Result |
|---|---|
| `backend/.venv/bin/python -m pytest backend/tests/unit/processing/test_normalization.py backend/tests/unit/processing/test_csv_import.py backend/tests/unit/processing/test_source_envelope.py backend/tests/contract/api/test_import_review_routes.py backend/tests/contract/api/test_source_routes.py -q` | 34 passed |
| `backend/.venv/bin/ruff check backend` | Passed |
| `backend/.venv/bin/mypy backend/app` | Passed; 48 source files |
| `backend/.venv/bin/ruff format --check backend/app backend/tests backend/alembic` | Passed; 101 files formatted |
| `openspec validate gh-10-implement-import-preview-and-validation-feedback --strict --json` | Passed; zero issues |
| `git diff --check` | Passed |

The isolated PostgreSQL cluster was created under `/tmp/mkt-gh10-pg` on local port
`55439`, upgraded to head, and stopped after testing. Its database was named
`mkt_gh10_test`; `mkt_app` served only as the distinct production URL for the
fail-closed test database guard. The exact database commands below ran from
`backend/`:

```sh
env APP_ENV=test TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test .venv/bin/alembic upgrade head
env APP_ENV=test DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_app TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test .venv/bin/python -m pytest tests/integration/db/test_migrations.py -q
env APP_ENV=test DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_app TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55439/mkt_gh10_test .venv/bin/python -m pytest tests -q
```

The migration suite passed 4 tests. The final stage suite passed 300 tests and
skipped 2 opt-in live storage tests because `RUN_STORAGE_LIVE` was not set.
