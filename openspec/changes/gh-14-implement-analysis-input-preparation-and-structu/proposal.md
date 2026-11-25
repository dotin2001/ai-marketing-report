## Why

The persisted analysis worker currently has no production input builder and its executor reports `provider_unavailable`. Issue #14 prepares a trustworthy, bounded analysis request from confirmed deterministic results and defines the structured narrative contract before provider integration.

## What Changes

- Build a revision-bound analysis input from the job's owner-scoped metric result set, inclusive reporting period, and captured draft objectives. Preserve metric value, unit, availability, reason, scope, currency, calculation version, and source identity without recalculating figures.
- Define a strict Pydantic structured-output schema for summary, findings, anomalies, recommendations, and data limitations (`data_gaps` in the existing API), with observation or hypothesis labels and valid metric references.
- Validate prepared input and parsed output before any result can be persisted or displayed; reject unsupported numeric claims, foreign references, malformed sections, and stale identities with a safe failed-job outcome.
- Add deterministic unit and PostgreSQL-backed verification for input selection, bounds, provenance, schema rejection, and worker integration.

## Capabilities

### New Capabilities

- `analysis-input-and-structured-output`: Revision-bound, bounded preparation of analysis context and validation of the five-section narrative result.

### Modified Capabilities

None. Existing lifecycle and job requirements already establish the API shape, failure codes, ownership, and persistence boundary.

## Impact

- Backend AI package, analysis worker integration, existing metric/draft/result persistence, and focused tests. Any necessary schema change must use Alembic.
- No public endpoint or request-envelope change is planned. Live OpenAI calls, prompt transport, PDF rendering, and frontend work remain separate stages.

## Acceptance Criteria

- Prepared input uses only the captured current confirmed metric set, its reporting period, and draft objectives; exact values and unavailable reasons remain distinguishable, currencies are never combined, and no pasted claim becomes a computed metric.
- The Pydantic result contract represents all five sections, labels observations and hypotheses, and validates every numeric reference against the prepared metric context before persistence or display.
- Changed inputs, malformed output, invented figures, or cross-owner references cannot produce an attached successful analysis result; failure is sanitized and existing job idempotency/retry behavior remains intact.

## Verification

- Unit tests cover deterministic input ordering and bounds, objective and period capture, metric availability/currency/provenance, untrusted-content handling, five-section parsing, extra-field rejection, and invented or mismatched metric references.
- PostgreSQL integration and worker tests cover owner isolation, revision staleness, validated result persistence, duplicate delivery, and sanitized invalid-output failure. At implementation handoff run focused suites, then `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and `cd backend && python -m pytest tests`; report unavailable gates.
- Planning gate: `openspec validate gh-14-implement-analysis-input-preparation-and-structu --strict --json` returns valid with no issues, and this proposal has exactly one versioned traceability marker.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLpzjA","issueId":"I_kwDOVnzly88AAAABiSeYcg","branch":"feature/backend","baseCommit":"a0bff2fd47362e28a058e2d168cf5706167a9d11","changeId":"gh-14-implement-analysis-input-preparation-and-structu","projectNumber":2,"issueNumber":14} -->
