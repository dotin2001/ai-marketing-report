## Why

The repository describes the intended marketing-report journey, but it does not yet have a normative OpenSpec contract for report fields, lifecycle gates, editing boundaries, job states, or acceptance criteria across all seven MVP workflow steps. Defining that contract now gives each later delivery-stage change a stable behavioral baseline and prevents database, backend, processing, AI, PDF, and frontend work from making incompatible lifecycle assumptions.

## What Changes

- Define the owned report aggregate and the minimum fields and provenance records needed to move from creation through source import, confirmed normalization, analysis, draft editing, immutable versioning, PDF export, and history.
- Define lifecycle gates and editing rules, including confirmation before analysis, optimistic draft updates, immutable saved versions, and cloning an older version into a new draft instead of mutating history.
- Define persisted analysis-job and PDF-job states, legal retry behavior, idempotency expectations, and protection against stale results, duplicate versions, or conflicting exports.
- Define acceptance criteria for every step of the seven-step MVP journey, including validation and failure behavior, ownership authorization, currency and period compatibility, metric availability, AI provenance, and exact-version PDF rendering.
- Define the verification evidence that later implementation changes must provide while preserving the repository's staged delivery order; this change does not implement application code or combine the later delivery stages.

## Capabilities

### New Capabilities

- `report-lifecycle`: Normative report fields, source/configuration provenance, lifecycle gates, editing and immutability rules, analysis/PDF job states and retries, the seven-step MVP journey, and required verification.

### Modified Capabilities

None.

## Impact

- Establishes the behavioral contract that later database, backend, data-processing, job/AI, version/PDF, frontend, and integrated-verification changes must implement in dependency order.
- Affects future report, source, import configuration, draft, metric, analysis, job, version, PDF export, ownership, API, storage, and UI contracts without selecting a concrete authentication provider.
- Introduces no application code, schema migration, API, dependency, branch, or external-system mutation in this planning change.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa2aw","issueId":"I_kwDOVnzly88AAAABd52rsg","branch":"feature/set_up","baseCommit":"37734ce517c9114723bed7fd36f53763c3dab670","changeId":"gh-1-define-the-report-lifecycle-and-mvp-requirements","projectNumber":2,"issueNumber":1} -->
