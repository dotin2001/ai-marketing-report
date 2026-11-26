## Why

The frontend still shows a foundation placeholder, so owners cannot see their reports or start the first step of the MVP journey. Issue #21 calls for report listing and a creation form with validation and clear loading, empty, and error states, using the existing owner-scoped report API.

## What Changes

- Replace the placeholder home surface with an owner-scoped report list showing each report's name, inclusive period, and server-derived stage, plus navigation to create a report.
- Add a report creation page for name, inclusive start and end dates, and one or more objectives. Apply the backend's bounds before submission and display safe field errors returned by the API.
- Handle initial loading, empty lists, request failures, invalid cursors, and creation submission/retry states. Preserve entered values after validation or recoverable request failures and prevent duplicate creation from repeated submits.
- Centralize typed report API calls and safe error normalization for these pages, including cursor pagination and the required creation idempotency key. Document any new frontend configuration or commands.

## Capabilities

### New Capabilities

- `report-listing-and-creation-pages`: Owner-facing report listing and creation workflow, validation feedback, pagination, navigation, and explicit request states.

### Modified Capabilities

None. The main `openspec/specs/` directory has no archived capability to modify; this frontend capability consumes the active report-management and v1 API contracts without changing them.

## Impact

- Affects `frontend/app/`, a centralized `frontend/lib/` API boundary, reusable UI components if needed, frontend tests, and frontend setup documentation.
- Consumes existing `GET /api/v1/reports`, `GET /api/v1/reports/{report_id}`, and `POST /api/v1/reports` contracts. No backend route, database schema, source import, analysis, versioning, or PDF behavior is introduced.
- Authentication remains the backend's provider-neutral principal contract. The frontend must use the configured authenticated request path without exposing secrets or representing unauthenticated data as an empty report list.

## Acceptance Criteria

- An authenticated owner can see only their returned report summaries, including each name, inclusive period, and server-derived stage, and can begin creation.
- The list has distinct loading, empty, and recoverable error states; it can advance through opaque cursor pages without parsing cursors or duplicating report cards. Authentication failures are distinct from an empty list.
- A user can create a report with a trimmed 1–200 character name, valid `YYYY-MM-DD` inclusive period, and 1–20 trimmed objectives of 1–2,000 characters each. The form blocks known invalid inputs, shows field-level server validation, and preserves entered values on failure.
- A successful submit sends the required idempotency key, creates or replays one report despite repeated clicks or retry, and returns to the listing with the new report visible. No source, analysis, version, or export is implicitly created.
- Loading, submitting, success, error, and retry affordances remain keyboard accessible, labeled, focus-aware, and usable with reduced motion and small screens.

## Verification

- Test list rendering, stages, period formatting, empty/loading/error/authentication states, cursor progression, and duplicate prevention with deterministic API fakes.
- Test form boundary values, date ordering, objective editing, client and server field errors, retained input after failure, idempotency reuse on retry, and successful navigation.
- Run frontend lint, typecheck, tests, and production build; run a browser journey for listing and creation against an authenticated test backend. Report any unavailable gate.
- Run `openspec validate gh-21-build-report-listing-and-report-creation-pages --strict --json` and require a valid result with no issues. Verify this proposal contains exactly one versioned traceability marker.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhMEJls","issueId":"I_kwDOVnzly88AAAABitfAIg","branch":"feature/frontend","baseCommit":"1475f67562b1beca9f179cd5832c119567521ec2","changeId":"gh-21-build-report-listing-and-report-creation-pages","projectNumber":2,"issueNumber":21} -->
