## 1. API Boundary

- [x] 1.1 Add the same-origin `/api/v1` backend rewrite using the existing validated API base URL, and verify browser requests reach the backend without exposing secrets or bypassing `401` responses.
- [x] 1.2 Add typed report list/detail/create requests and safe error normalization in `frontend/lib/`, covering envelopes, cursor metadata, `422` detail paths, and idempotency headers; verify with deterministic API tests.

## 2. Report Listing

- [x] 2.1 Replace the foundation home page with the report listing shell and owner-scoped summary cards showing name, inclusive dates, and server stage; verify populated and empty rendering tests.
- [x] 2.2 Add initial loading, unauthenticated, first-page error, retry, load-more, later-page error, and invalid-cursor restart states while preserving cards and deduplicating IDs; verify interaction tests for each state and cursor handling.
- [x] 2.3 After creation, reauthorize the `created` report ID through the detail endpoint, show the returned report while refreshing the list, and reconcile by ID; verify authorized, missing/foreign, and older-replay cases.

## 3. Report Creation

- [x] 3.1 Build `/reports/new` with labeled name/date/objective controls and add/remove objective actions; verify keyboard interaction, bounds, and small-screen rendering.
- [x] 3.2 Validate trimmed name and objectives, strict inclusive dates, objective count, and server field-detail paths without clearing user entries; verify boundary and error-mapping tests.
- [x] 3.3 Submit one in-flight command with a stable per-command idempotency key, reuse it for uncertain retries, rotate it after semantic edits, and route successful creation/replay to the listing; verify repeated-click, retry, conflict, failure, and success tests.

## 4. Documentation and Verification

- [x] 4.1 Update frontend setup documentation for the same-origin API path and authenticated backend prerequisite, and verify the documented environment and commands match the code.
- [x] 4.2 Run `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck`, `npm --prefix frontend test`, and `npm --prefix frontend run build`; verify all pass or record each unavailable gate.
- [x] 4.3 Run a browser journey with an authenticated test backend for list loading, creation, and seeing the created report; check keyboard focus, narrow viewport, reduced motion, and distinct `401` behavior, then record results or the specific authentication blocker.
- [x] 4.4 Run `openspec validate gh-21-build-report-listing-and-report-creation-pages --strict --json`, verify a valid zero-issue result and exactly one versioned traceability marker in `proposal.md`, and review the change diff for scope and whitespace.
