## Why

Immutable report versions can be created and read, but `backend/app/pdf/` has no report template or renderer. The next versioning stage needs a reproducible PDF built from the saved snapshot, including readable Vietnamese text and predictable layout for long reports.

## What Changes

- Add one versioned HTML/CSS report template containing report metadata, objectives, deterministic KPIs, snapshot-declared charts, insights, recommendations, limitations, and labeled source claims where present.
- Add a backend view-model builder that validates schema 1 and 2 saved snapshots and renders only their frozen content. Unavailable metrics retain their reasons; text-only versions do not acquire invented metrics or charts.
- Render the template to PDF with Playwright and bundled Vietnamese-capable fonts, print styles, controlled page breaks, and bounded long-content behavior.
- Return validated PDF bytes and safe rendering failures to the later version-bound export orchestration, with fixed-snapshot and layout verification.

## Capabilities

### New Capabilities

- `versioned-report-pdf-rendering`: Deterministic, safe HTML report composition and Playwright PDF rendering from immutable report-version snapshots.

### Modified Capabilities

None. This stage implements the established saved-version and PDF invariants without changing version creation, API, or export lifecycle requirements.

## Impact

Affected areas are `backend/app/pdf/`, its unit and fixed-snapshot rendering tests, backend dependency and browser/font packaging, and documented renderer configuration. The renderer consumes `backend/app/db/snapshots.py` schemas and remains independent of mutable drafts, live source objects, and the public API. Existing version, export-state, storage, and authorized download code is reused by later orchestration; this change does not add export endpoints or wire a Celery PDF job.

Issue #19 acceptance intent is preserved: the template includes metadata, KPIs, charts, insights, and recommendations, and Playwright produces PDFs with correct Vietnamese fonts, page breaks, and long-content handling. Required verification includes fixed schema 1/schema 2 and text-only fixtures, Vietnamese glyph and multipage visual checks, malformed/untrusted content tests, the backend stage suite, and strict OpenSpec validation.

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLp1K0","issueId":"I_kwDOVnzly88AAAABiSgIrw","branch":"feature/backend","baseCommit":"15e4d118b5bc25aa6237fdd397fa20a07375226c","changeId":"gh-19-build-the-html-report-template-and-pdf-renderer","projectNumber":2,"issueNumber":19} -->
