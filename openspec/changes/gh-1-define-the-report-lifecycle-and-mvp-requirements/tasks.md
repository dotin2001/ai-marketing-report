## 1. Align the Product Requirements Foundation

- [x] 1.1 Update `project.md` to enumerate the report, immutable source, confirmed import configuration, revisioned draft, metric result, analysis result, logical job/attempt, immutable version, and version-bound PDF export field groups from `specs/report-lifecycle/spec.md`; verify every group retains owner/provenance, identity, revision or immutability, timestamps, and safe error/reference fields applicable to it.
- [x] 1.2 Add the canonical report workflow stages `created`, `source_review`, `analysis_ready`, `analysis_pending`, `reviewing`, and `versioned` plus their transition gates to `project.md`; verify the documented transitions cover confirmation, analysis success/failure/staleness, narrative edits, version creation, new inputs, and restoration from history without mixing PDF status into report stage.
- [x] 1.3 Document editing and invalidation rules in `project.md`, including optimistic draft saves, non-editable deterministic metrics and original sources, no implicit version on draft save, semantic analysis-input identities, stale-result rejection, and immutable historical versions; verify each rule agrees with the lifecycle spec and the design transition table.
- [x] 1.4 Align the analysis and PDF logical-job sections in `project.md` with the shared `queued`, `running`, `succeeded`, and `failed` states, persisted attempts, idempotency, sanitized failures, and retry binding; verify analysis retry cannot overwrite newer work and PDF retry cannot create or switch report versions.

## 2. Document All Seven MVP Acceptance Steps

- [x] 2.1 Add concise acceptance criteria for MVP steps 1–3 to `project.md`: validated report creation, immutable pasted/CSV source preservation, safe upload rejection, CSV/text preview, user-correctable mapping and normalization, ISO 4217 currency handling, explicit warnings/errors, and confirmation before analysis; verify the criteria cover both happy paths and blocking validation.
- [x] 2.2 Add concise acceptance criteria for MVP step 4 to `project.md`: aggregate CTR/CPC/CPM/CPL calculations, unavailable reasons, mixed-currency and period-comparability rules, persisted idempotent analysis jobs, bounded untrusted AI context, validated structured output, provenance, explicit failure, retry, and stale-result behavior; verify no criterion permits AI arithmetic or invented figures.
- [x] 2.3 Add concise acceptance criteria for MVP steps 5–7 to `project.md`: review and narrative editing, conflict-safe saves, atomic immutable versions, exact-version PDF generation, ordered history, authorized download, same-version export retry, and cloning an old version into a new draft; verify draft changes cannot alter a saved version or completed PDF.
- [x] 2.4 Add the downstream verification matrix from `design.md` to the delivery guidance in `project.md`, assigning database, API, processing, worker/AI, version/PDF, frontend, and integrated evidence to their owning focused stages; verify the document still requires sequential stage-specific OpenSpec changes and does not authorize an umbrella implementation.

## 3. Verify Requirement Consistency and Traceability

- [x] 3.1 Review `project.md`, `proposal.md`, `design.md`, and `specs/report-lifecycle/spec.md` for terminology and scope consistency; verify report stages, job states, seven workflow steps, supported KPIs, source types, currency policy, immutability, authorization, and non-goals have no conflicting definitions.
- [x] 3.2 Verify each MVP step is represented by at least one explicit scenario by running `for step in 1 2 3 4 5 6 7; do rg -q "MVP step $step" openspec/changes/gh-1-define-the-report-lifecycle-and-mvp-requirements/specs/report-lifecycle/spec.md || exit 1; done` and record any manual acceptance review needed for multi-scenario steps.
- [x] 3.3 Verify `proposal.md` contains exactly one `ai-local-trace:v1` marker whose repository, Project, item, issue, branch, base commit, and change identities match the selected issue context; do not copy the marker into any other artifact.

## 4. Final Planning-Foundation Validation

- [x] 4.1 Run `openspec validate gh-1-define-the-report-lifecycle-and-mvp-requirements --strict --json` and verify it reports the change valid with no missing capability delta, malformed requirement, or scenario error.
- [x] 4.2 Perform a final human-readable checklist against GitHub issue #1 and verify the delivered requirements explicitly define report fields, processing flows, editing rules, report states, analysis-job states, PDF-job states, acceptance criteria for all seven workflow steps, and required downstream verification.
- [x] 4.3 Confirm the applied change modifies only requirements/documentation artifacts, leaves application code and infrastructure unimplemented, and does not apply another OpenSpec change, change Project status, close the issue, create or switch branches, commit, push, merge, or deploy.
