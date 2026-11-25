## Why

CSV confirmation now produces a canonical dataset, but the backend does not calculate or expose deterministic KPI results from it. Issue #12 requires the confirmed data to become explainable aggregates while making accepted and rejected record counts clear to the owner.

## What Changes

- Calculate and persist versioned CTR, CPC, CPM, and CPL results from the exact current confirmed dataset, with report-wide and currency-specific scopes as defined by the product contract.
- Expose owner-authorized dataset and metric reads with canonical provenance, exact decimal totals, unavailable reasons, and deterministic ordering.
- Report accepted and rejected record counts with safe explanations during validation and confirmation. Blocking row errors reject the entire revision: a successful confirmation accepts every source record and has zero rejected records.
- Keep repeated calculation and reads idempotent, and invalidate the current metric reference when the confirmed input changes while retaining historical results.

## Capabilities

### New Capabilities

- `confirmed-dataset-kpi-aggregation`: Deterministic aggregation, persisted metric results, authorized reads, and explicit row-count accounting for confirmed CSV data.

### Modified Capabilities

None. Existing active import, API, lifecycle, and database contracts already define the core behavior; no archived main specification exists under `openspec/specs/` to modify.

## Impact

- Affects backend processing, dataset/metric domain services, repositories, `/api/v1` dataset routes and Pydantic schemas, and focused unit, contract, and PostgreSQL integration tests. Existing confirmed-import and metric tables are reused where sufficient; any proven schema gap requires an Alembic migration.
- No frontend, AI analysis, PDF rendering, currency conversion, partial-row acceptance, or new source format is included.

## Acceptance Criteria

- The owner can confirm a current, error-free mapping and obtain a dataset revision with accepted and rejected row counts and safe explanations. Validation reports the total and located errors; any blocking error prevents confirmation and metric attachment. Valid duplicates remain included.
- CTR uses aggregate clicks and impressions across the confirmed report period. CPC, CPM, and CPL use aggregate inputs within one currency; mixed currencies are never combined for spend metrics. Period and campaign grouping uses only supported canonical dimensions and retains each group's scope and provenance.
- Missing inputs, zero denominators, incompatible currency requests, and incompatible period comparisons are explicit unavailable results without a numeric value. Genuine zero numerators remain available zero. Every result retains exact input totals, dataset identity, calculation version, period, scope, currency, and calculation time.
- Equivalent reruns produce the same logical result without duplicate current result sets. Source, mapping, policy, or period changes remove stale current metric references while preserving historical results. Missing and foreign resources have the same owner-safe response.

## Verification

- Implement the Stage 3 golden cases in `backend/tests/unit/processing/test_kpi_calculation.py`, including aggregate-ratio divergence, exact decimal spend, non-terminating precision, missing and zero inputs, currency partitions, reproducibility, and period comparability.
- Extend `backend/tests/integration/processing/test_confirmed_import.py` for row counts, atomic metric attachment, invalidation, historical preservation, idempotency, and ownership; add runtime contract tests for dataset and metric routes, schema exclusivity, pagination, and safe errors.
- At implementation handoff run the focused unit, contract, and isolated PostgreSQL integration suites, then backend lint, type checks, and the stage-level backend suite. Report unavailable gates. Planning requires `openspec validate gh-12-implement-dataset-confirmation-and-kpi-aggregati --strict --json` with zero issues.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhJbT3c","issueId":"I_kwDOVnzly88AAAABf-SeDA","branch":"feature/backend","baseCommit":"f70bcc5b4a2e54c31c7e700d8771a1e9b4c149e5","changeId":"gh-12-implement-dataset-confirmation-and-kpi-aggregati","projectNumber":2,"issueNumber":12} -->
