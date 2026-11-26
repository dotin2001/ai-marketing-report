## 1. Version Contracts and Read Path

- [x] 1.1 Add strict Pydantic create, restore, version summary, version detail, and page envelopes with safe checksum and UTC serialization; verify schema tests reject unknown mutation fields and nested private references.
- [x] 1.2 Add an owner/report-scoped bounded keyset history query and a schema-aware detail projection for schema 1 and 2 snapshots; verify PostgreSQL tests cover descending pages, a concurrent new version between pages, and no inferred legacy bindings.
- [x] 1.3 Add a version domain service using the existing transaction functions, signed owner/report-bound cursors, and explicit not-found/conflict outcomes; verify service tests cover foreign access, invalid cursors, and no raw object keys or source content in responses.

## 2. Version Mutations and HTTP Routes

- [x] 2.1 Wire the version service through dependencies and app lifespan, then add the four `/api/v1/reports/{report_id}/versions` routes with existing envelopes and stable error codes; verify OpenAPI and API contract tests for `201` create, `200` list/detail/restore, `400` cursor errors, `404` foreign resources, `409` conflicts, and `422` validation.
- [x] 2.2 Connect create to `save_current_report_version` using the exact active draft revision, scoped idempotency, and the server template version; verify PostgreSQL tests for structured and text-only snapshots, stale or mismatched bindings, replay, duplicate snapshot handling, and no version from a draft save.
- [x] 2.3 Connect restore to `restore_saved_version` with expected active draft identity and revision, returning the new draft projection; align persisted replay success status with public `200` and verify tests for saved editable content, idempotent replay, stale revision, and unchanged versions, datasets, and exports.

## 3. Invariants and Stage Verification

- [x] 3.1 Extend PostgreSQL concurrency and authorization tests to verify contiguous report-local version numbers, no partial version on rollback, immutable snapshots, owner isolation, and safe historical reads after current inputs change; run the focused version database suite.
- [x] 3.2 Run focused version schema and API contract tests, then `npm run backend:check` and the relevant PostgreSQL stage suite using isolated `APP_ENV=test`, `DATABASE_URL`, `TEST_DATABASE_URL`, and `MIGRATION_DATABASE_URL`; record any environment-limited checks and verify `openspec validate gh-18-implement-report-version-creation-and-history --strict --json` reports no issues.

Verification: focused version PostgreSQL tests passed (16); backend non-PostgreSQL tests passed (291); PostgreSQL integration stage passed (67); backend format, lint, and import passed; strict OpenSpec validation reported no issues. `npm run backend:check` stopped at repository-wide mypy errors in unrelated existing tests (69 after the one new-test error was fixed). Targeted mypy for the new version sources and tests passed. No schema migration was added.
