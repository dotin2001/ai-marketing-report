## 1. Prepared Input

- [x] 1.1 Add strict AI-layer input models for period, ordered objectives, metric availability/provenance, exact decimal strings, and semantic identities; verify unit tests reject malformed and non-finite values.
- [x] 1.2 Implement owner-scoped loading of the job-captured report, confirmed dataset, metric set/results, represented currencies, and exact input totals; verify PostgreSQL tests prove foreign rows and mismatched identities cannot enter the context.
- [x] 1.3 Check current draft/objectives revisions, period, dataset/metric attachment, and semantic identity before preparation; verify stale and changed-input cases fail without a result.
- [x] 1.4 Apply deterministic ordering and the documented objective, metric, and byte budgets; verify exact boundary, overflow, mixed-currency, unavailable-metric, and repeated-build fixtures.

## 2. Structured Result and Grounding

- [x] 2.1 Define the strict five-section Pydantic response model with bounded items, stable ordinal rules, classification, required summary, and trusted provenance envelope; verify valid empty optional sections and invalid/missing/extra fields in unit tests.
- [x] 2.2 Validate all item metric references and structured numeric assertions against the prepared metric set, including value, unit, scope, period, currency, and unavailable reasons; verify invented, cross-owner, altered, and free-text numeric assertions fail before persistence.
- [x] 2.3 Convert validated sections to the existing result/item shape and persist metric-reference links atomically with the result; verify PostgreSQL tests cover link ownership, exact identities, and transaction rollback on invalid output.

## 3. Worker Boundary and Verification

- [x] 3.1 Pass prepared context through the analysis runner boundary while leaving the production executor unavailable until provider integration; verify a deterministic fake produces a validated result and duplicate delivery produces only one result.
- [x] 3.2 Map stale, budget, and invalid-output outcomes to existing sanitized job failure codes and retryability rules; verify worker and API contract tests expose no source text, raw response, prompt, or internal details.
- [x] 3.3 Document analysis context limits and the provider-independent result contract in backend documentation; verify documented bounds and field names match the implementation.
- [x] 3.4 Run focused AI unit, worker, PostgreSQL integration, and analysis-job contract tests, then `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and `cd backend && python -m pytest tests`; record any gate not run and its reason.
