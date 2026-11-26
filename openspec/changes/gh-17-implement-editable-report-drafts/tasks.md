## 1. Draft API contract

- [x] 1.1 Extend the strict draft patch request with optional objectives, narrative, limitations, claims, and charts; validate supported sections, labels, nonblank bounded text, chart presentation fields, and protected-field rejection. Verify with focused Pydantic and API validation tests, including omitted versus empty collections.
- [x] 1.2 Add ordered chart declarations and metric references to `DraftDetail` and the owner-scoped report detail projection. Verify a save followed by report retrieval returns the same ordered content and safe empty collections in API contract tests.

## 2. Atomic domain save

- [x] 2.1 Implement one owner-authorized, revision-checked draft save transaction in the report domain service, replacing only supplied collections and advancing the revision once. Verify PostgreSQL integration tests cover a multi-collection save, objective-only compatibility, clearing one collection, and rollback of a failed combined save.
- [x] 2.2 Validate claim source ownership and current chart metric membership, scope, type, count, and absence of numeric overrides before mutation. Verify PostgreSQL and API tests reject foreign, historical, stale, duplicate, and missing references without changing the revision or other draft content.
- [x] 2.3 Wire `PATCH /api/v1/reports/{report_id}/draft` to the domain command and safe error mapping. Verify API tests distinguish successful `200`, stale `409 revision_conflict`, malformed `422 validation_failed`, and owner-safe `404`, including generated OpenAPI request and response shapes.

## 3. Concurrency and state protection

- [x] 3.1 Add PostgreSQL tests for simultaneous saves with the same expected revision and for a stale save after another edit; verify exactly one succeeds and the rejected request does not overwrite newer content or create a version.
- [x] 3.2 Verify a draft edit during an in-flight analysis cannot attach the older result or overwrite saved content, and that presentation edits leave source, metric, analysis provenance, and historical version rows unchanged. Use the relevant worker and PostgreSQL integration tests.

## 4. Stage verification

- [x] 4.1 Run focused draft schema, API, and PostgreSQL tests, then the backend stage suite with `cd backend && uv run pytest tests/unit/api tests/contract/api/test_reports_and_drafts.py tests/integration/db/test_reports_and_drafts.py tests/integration/db/test_draft_charts.py tests/integration/db/test_report_management_service.py tests/integration/db/test_saved_version_service.py tests/integration/db/test_analysis_job_service.py`; verify all pass or record environment limits and failures.
- [x] 4.2 Run `cd backend && uv run ruff check app tests` and `cd backend && uv run mypy app`, and verify `openspec validate gh-17-implement-editable-report-drafts --strict` passes. Document any new command or environment setting in project documentation or an example environment file if introduced.
