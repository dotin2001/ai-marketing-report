## Why

Report drafts already store revisioned objectives and have database structures for narrative, claims, limitations, and charts, but the owner cannot save those report sections or chart configuration through the public API. This change completes the editable draft boundary before version creation and PDF export consume saved draft content.

## What Changes

- Let the report owner read and save ordered narrative sections, limitations, labeled pasted claims, and chart configuration on the active draft.
- Extend the draft update contract with strict field validation, safe metric and source references, and an expected revision that detects conflicting updates across all draft edits.
- Preserve validated metrics, original sources, AI provenance, and existing versions when draft presentation content changes; a draft save never creates a version or PDF.
- Verify owner isolation, stale revision rejection, atomic saves, chart reference rules, and the resulting draft projection with API and PostgreSQL tests.

## Capabilities

### New Capabilities

- `editable-report-drafts`: Owner-scoped editing, retrieval, validation, and revision conflict behavior for report content and charts.

### Modified Capabilities

None. The existing report-management and versioning requirements are active change deltas; this change fills the permitted draft-field scope they leave for a later stage.

## Impact

The existing `PATCH /api/v1/reports/{report_id}/draft` and report detail response gain editable fields and chart configuration. The implementation will use the existing draft tables and chart snapshot contract in `backend/app/db/`, with domain rules in `backend/app/domain/`, Pydantic contracts and routes in `backend/app/api/`, and corresponding contract and PostgreSQL tests. A migration is needed only if the existing schema cannot enforce a required invariant. Version creation, version history, and PDF export are separate changes. The issue acceptance intent is preserved: save editable report sections and chart configuration, and detect conflicting updates using draft revisions.

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLp0xo","issueId":"I_kwDOVnzly88AAAABiSfwpA","branch":"feature/backend","baseCommit":"5560bde4a1f02aef99b139d163f7bbe867b8aba7","changeId":"gh-17-implement-editable-report-drafts","projectNumber":2,"issueNumber":17} -->
