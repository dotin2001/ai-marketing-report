## Why

Report owners can create reports but cannot attach the source material needed for analysis from the frontend. Issue #22 asks for a data import interface that accepts CSV files and pasted tables and makes upload progress, limits, and ingestion errors clear.

## What Changes

- Add an owner-facing import page for an existing report with mutually clear CSV and pasted-content entry paths.
- Show the configured CSV and pasted-text size limits before submission, reject known oversize or empty inputs locally, and present server intake errors without losing the selected file or pasted content.
- Show determinate upload progress where the browser can measure bytes, an explicit indeterminate state when it cannot, and safe retry behavior for an uncertain result using the same idempotency key.
- After attachment, display safe source metadata and the bounded, explicitly unvalidated preview returned by the API. Provide a path toward later mapping and confirmation without implying that attachment completed analysis.
- Link report cards to their import page and centralize typed source API calls, error handling, and frontend configuration.

## Capabilities

### New Capabilities

- `data-import-interface`: Frontend source attachment, progress, limit and error feedback, retry, and unvalidated preview for an owner-scoped report.

### Modified Capabilities

None. This change consumes the active source-ingestion, import-preview, report-management, and API contracts without changing their requirements. There are no archived main specs in `openspec/specs/` to modify.

## Impact

- Affects `frontend/app/reports/`, report-list navigation, `frontend/lib/` API and configuration modules, frontend tests, and setup documentation.
- Consumes `GET /api/v1/reports/{report_id}`, `POST /api/v1/reports/{report_id}/sources/csv`, `POST /api/v1/reports/{report_id}/sources/text`, and owner-authorized source detail and preview endpoints. No backend route, schema, normalization, KPI, AI, versioning, or PDF behavior is introduced.
- Keeps authentication and report ownership at the existing backend boundary. Source content remains untrusted and previews are not confirmed data.

## Acceptance Criteria

- From a report listing, an owner can reach that report's import page and attach either one CSV file or non-empty pasted content. The interface shows the supported CSV type and current configured size limits before submission.
- The CSV path shows progress while bytes are sent, distinguishes uploading from processing and preview loading, and gives accessible success, failure, and retry states. The pasted path gives equivalent submission feedback without suggesting byte progress that cannot be measured.
- Empty input, known oversize input, unsupported file selection, and safe API ingestion errors are explained clearly. A recoverable failure preserves the selected file or pasted text and can be retried without a duplicate source; editing the input creates a new command identity.
- On success, the page shows the accepted source's safe metadata and bounded CSV rows or pasted excerpt as unvalidated, unconfirmed source data. Duplicate CSV headers stay distinguishable by ordinal; row indexes and truncation are visible. No preview content is executed as HTML or formulas.
- Authentication and missing or foreign report/source responses expose no protected data. Source attachment does not claim to confirm a mapping, calculate metrics, or begin analysis.
- Controls and status messages work with keyboard navigation, labeled inputs, focus management, small screens, and reduced motion.

## Verification

- Test source API request shape and envelope parsing for multipart CSV, JSON pasted text, idempotency, safe errors, and preview metadata with deterministic fakes.
- Test frontend selection and limit checks, accessible progress and status states, retained input after failure, repeated-click and uncertain retry behavior, successful source/preview rendering, authentication and 404 handling, duplicate-header ordinals, and inert source content.
- Run frontend lint, typecheck, tests, and production build. Run a browser journey against an authenticated test backend for both import paths, an ingestion failure/retry, upload progress, and bounded preview; record any unavailable gate.
- Run `openspec validate gh-22-build-the-data-import-interface --strict --json` and require a valid zero-issue result. Verify exactly one versioned traceability marker in this proposal.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhMEJ40","issueId":"I_kwDOVnzly88AAAABitfSfA","branch":"feature/frontend","baseCommit":"afb69c37e6e41f0d87df3b991629738fd2fda83d","changeId":"gh-22-build-the-data-import-interface","projectNumber":2,"issueNumber":22} -->
