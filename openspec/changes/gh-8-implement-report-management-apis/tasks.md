## 1. Report request and response contracts

- [x] 1.1 Add strict Pydantic request models for creation, metadata PATCH, objective PATCH, and pagination with trimming, bounds, complete period validation, and unknown-field rejection; verify focused model tests cover valid boundaries and safe invalid-field paths.
- [x] 1.2 Add distinct report summary, report detail, active-draft detail, page, and error response models with canonical UUID/date/UTC serialization and safe current references; verify serialization tests exclude ORM/private fields and match the v1 envelopes.
- [x] 1.3 Normalize FastAPI request-validation failures for these routes into `validation_failed` with deterministic safe `details` and documented status codes; verify HTTP tests contain no framework-default error body or rejected values.

## 2. Domain and persistence

- [x] 2.1 Add an owner-scoped report domain service and transaction/session wiring around the existing report, draft, and objective repository helpers; verify service tests cover creation of exactly one report and revision-1 draft with no other resources.
- [x] 2.2 Implement canonical request fingerprinting and transactional `create-report` idempotency using the existing database record, including key validation, owner scope, replay header result, conflict, and concurrent requests; verify isolated PostgreSQL tests find one report/draft and no partial records or duplicate side effects.
- [x] 2.3 Implement owner-authorized report detail and shallow list projections with derived stage and safe references; verify PostgreSQL tests cover created, source-review, analysis, and versioned facts as available, plus indistinguishable missing/foreign detail behavior.
- [x] 2.4 Implement revision-checked metadata updates against the active draft, with one revision increment for an effective edit and no increment for a current-revision no-op; verify concurrent/stale, malformed, and unknown-field tests leave persisted state unchanged on rejection.
- [x] 2.5 Implement period-change invalidation of current confirmation, dataset, metric, and analysis eligibility while retaining current source and immutable history; verify PostgreSQL tests prove required reconfirmation, preserved prior versions/datasets, and name-only validity preservation.
- [x] 2.6 Implement objective-only draft PATCH through the existing compare-and-set helper, preserving other draft content and invalidating stale objective-bound analysis; verify PostgreSQL tests cover bounds, stale and foreign access, exact revision increments, and no implicit version.

## 3. Pagination and HTTP routes

- [x] 3.1 Add owner-scoped `(created_at DESC, id DESC)` keyset report listing with `limit + 1`, signed expiring cursors bound to owner/route/order, and safe `invalid_cursor`; verify tests cover default/min/max, first/middle/final/empty pages, insert-before-boundary, replay, tamper, expiry, and cross-owner use.
- [x] 3.2 Wire `POST /api/v1/reports`, `GET /api/v1/reports`, `GET /api/v1/reports/{report_id}`, `PATCH /api/v1/reports/{report_id}`, and objective `PATCH /api/v1/reports/{report_id}/draft` through thin routes and the principal dependency; verify runtime contract tests cover statuses, envelopes, headers, ownership-before-conflict, and `401` with an unconfigured principal.
- [x] 3.3 Add cursor-signing configuration and example environment/project documentation without committing a real key; verify startup configuration tests reject a missing/invalid key and documentation identifies the required setting.

## 4. Contract and stage verification

- [x] 4.1 Create `backend/tests/contract/api/test_reports_and_drafts.py` with runtime request/response and generated OpenAPI assertions for valid/invalid creation, list/detail, metadata/objective updates, serialization, error allowlists, redaction, and no implicit resources; verify the focused pytest module passes.
- [x] 4.2 Add isolated PostgreSQL integration coverage for idempotency under repeated/concurrent creation, ownership, metadata/objective compare-and-set, period invalidation, and rollback; verify the focused database tests pass against the guarded test database.
- [x] 4.3 Run backend formatting/lint, strict type check, focused unit and contract tests, then the backend stage-level suite; if a migration was necessary, run upgrade verification and safe downgrade checks. Record exact commands and any unavailable gate in the implementation handoff.
- [x] 4.4 Run `openspec validate gh-8-implement-report-management-apis --strict --json` after implementation and verify it reports no issues before handoff.
