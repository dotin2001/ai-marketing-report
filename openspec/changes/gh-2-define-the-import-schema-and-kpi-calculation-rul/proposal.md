## Why

The MVP names supported CSV fields and KPI formulas, but it does not yet provide a focused, implementation-ready contract for column types, units, mapping and normalization outcomes, metric result semantics, or the exact boundary between warnings and blocking errors. Defining that contract before the data-processing stage prevents database, backend, and frontend changes from making incompatible assumptions about confirmed imports or deterministic calculations.

## What Changes

- Define the canonical MVP marketing dataset: required dimensions (`date`, `campaign_name`, and `currency`), optional measures (`impressions`, `clicks`, `spend`, and `leads`) with at least one measure present, accepted data types and units, and the treatment of unmapped source columns.
- Define mapping, parsing, normalization, and validation behavior for dates, campaign names, ISO 4217 currency codes, non-negative counts, and non-negative monetary values, including row-level issue provenance and the explicit confirmation gate.
- Define deterministic aggregate CTR, CPC, CPM, and CPL formulas, result units and precision boundaries, required input totals, and stable unavailable reasons for absent, invalid, incompatible, or zero-denominator inputs.
- Define single-currency calculation scopes and mixed-currency behavior without implicit conversion, while keeping user-provided claims distinct from confirmed structured data and computed metrics.
- Define the unit, integration, fixture, and strict OpenSpec verification required before the later data-import and calculation implementation can be accepted.
- Keep this change planning-only: it does not add application code, migrations, APIs, workers, UI, dependencies, or infrastructure.

## Capabilities

### New Capabilities

- `marketing-data-import-and-kpi-calculation`: Canonical CSV schema, mapping and normalization rules, validation and confirmation behavior, deterministic aggregate KPI calculations, metric availability, currency isolation, provenance, and required verification.

### Modified Capabilities

None.

## Impact

- Establishes the behavioral contract for the future pandas processing layer and the confirmed-import and metric-result boundaries consumed by database, backend, AI, versioning/PDF, and frontend stages.
- Constrains future preview and confirmation APIs and UI states without selecting endpoint shapes or implementing them in this change.
- Requires future tests to cover valid and invalid imports, aggregate-ratio behavior, missing inputs, zero denominators, row-level provenance, ISO 4217 normalization, mixed currencies, and deterministic reproducibility.
- Adds no runtime dependency and makes no deployed-system or data migration change.

## Verification

- Run `npm test` for the repository planning, traceability, and untrusted-input regression suite.
- Run `openspec validate gh-2-define-the-import-schema-and-kpi-calculation-rul --strict` for the final artifact set.
- Run `git diff --check -- project.md openspec/changes/gh-2-define-the-import-schema-and-kpi-calculation-rul` and review the diff to confirm the eventual apply step remains documentation-only and in scope.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa2u4","issueId":"I_kwDOVnzly88AAAABd528WQ","branch":"feature/set_up","baseCommit":"3444a76c081ab6b6e64e4b399739cb40cca046e1","changeId":"gh-2-define-the-import-schema-and-kpi-calculation-rul","projectNumber":2,"issueNumber":2} -->
