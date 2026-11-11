## Context

See `proposal.md` for motivation and `specs/report-lifecycle/spec.md` for the normative behavior. The repository has project guidance, local OpenSpec/GitHub workflow tooling, and one unrelated active tooling change, but no application implementation or main product capability specs. `project.md` already describes the intended journey and invariants at a high level; it does not yet make report stages, field groups, transition gates, editing invalidation, or per-step acceptance evidence precise enough for the later delivery stages to implement independently.

The lifecycle crosses PostgreSQL state, object storage, pandas processing, Celery delivery, OpenAI output, immutable version snapshots, Playwright rendering, and Next.js interaction. The requirements foundation therefore needs stable identities and state boundaries without prematurely combining those implementation stages or choosing the still-undecided authentication provider.

## Goals / Non-Goals

**Goals:**

- Establish one canonical lifecycle vocabulary that database, backend, processing, AI/job, PDF, and frontend changes can share.
- Separate report workflow stage, analysis-job state, PDF-job state, draft revision, and immutable version identity so one concern cannot overwrite another.
- Make invalidation, retry, stale-result protection, and idempotency implementable with database-backed identities and transitions.
- Keep the main product overview aligned with the normative OpenSpec capability and define the evidence later stage changes must provide.

**Non-Goals:**

- Implement application code, migrations, infrastructure, APIs, workers, UI, model calls, storage operations, or PDF rendering in this change.
- Select a concrete authentication provider; all later contracts use an authenticated-principal boundary and mandatory owner checks.
- Design additional input formats, advertising-platform integrations, OCR, currency conversion, custom formulas, collaboration, scheduled distribution, or additional PDF templates.
- Replace focused downstream OpenSpec changes with an umbrella implementation change.

## Decisions

### 1. Make `report-lifecycle` the normative capability and keep `project.md` as the product map

The delta spec contains testable SHALL/MUST behavior and scenarios. Applying this foundation change will update `project.md` only where needed to expose the same field groups, stage names, transition gates, editing rules, and seven-step acceptance matrix. After review and archive, the main `openspec/specs/report-lifecycle/spec.md` becomes the behavioral source of truth for later changes.

Maintaining only prose in `project.md` was rejected because later changes need scenario-level contracts and strict validation. Duplicating the full spec into another design document was rejected because two normative copies would drift.

### 2. Derive one report workflow stage from orthogonal persisted facts

The report exposes a small user-facing workflow stage while job attempts and export state remain separate. The stage is derived transactionally from persisted current source/configuration identity, metrics, current analysis job/result, active draft revision, and latest versioned draft revision:

| Current stage | Event and gate | Resulting stage |
|---|---|---|
| `created` | An immutable source is attached | `source_review` |
| `source_review` | Current source/configuration is confirmed and deterministic metrics finish | `analysis_ready` |
| `analysis_ready` | One current analysis logical job is accepted | `analysis_pending` |
| `analysis_pending` | A validated result for the still-current input is attached | `reviewing` |
| `analysis_pending` | Current analysis fails | `analysis_ready` with failed job retained |
| `reviewing` | Current draft revision is atomically versioned | `versioned` |
| `versioned` | Narrative-only draft edit or clone from history | `reviewing` |
| `reviewing` or `versioned` | Source, mapping, normalization, reporting period, or objectives change in a way that invalidates analysis | `source_review` or `analysis_ready`, according to whether confirmation remains valid |

PDF queueing, running, failure, success, and retry do not change the report workflow stage because exports belong to immutable versions. A new source does not remove previous versions or their exports.

A single large enum containing report, analysis, and PDF combinations was rejected because it creates an unbounded product state matrix. Leaving the report with no exposed stage was rejected because clients would otherwise reconstruct domain status inconsistently.

### 3. Use revisioned input identities to guard every asynchronous result

Each confirmed analysis input is identified by the report, source checksum/identity, import-configuration revision, canonical-data identity, metric calculation version/result identity, objectives revision, and relevant draft revision. Analysis jobs capture that identity at enqueue time and attach results only if it is still current. Draft saves use compare-and-set revision checks. Version creation captures one exact draft revision and an idempotency key.

This lets workers remain safe under delay and redelivery and prevents a late AI response from overwriting a newer source or edit. Timestamp-only freshness was rejected because equal or reordered timestamps cannot prove semantic input equality. Process-local locks were rejected because they do not coordinate API and worker processes.

### 4. Model analysis and PDF work as logical operations with attempts

Both job types use the persisted states `queued`, `running`, `succeeded`, and `failed`. A logical operation owns the idempotency key, input identity, current state, and result association; attempts record retry-specific timestamps and sanitized failures. Database uniqueness and transactional compare-and-set transitions enforce idempotency. Celery/Redis delivers work but never becomes the status source of truth.

Analysis retry may reuse the logical job or add an attempt only when the analysis input identity is unchanged. PDF retry always keeps the same version and template identity. A changed analysis input creates a new logical analysis operation; a PDF retry never creates a version.

Treating every delivery as a new independent job was rejected because repeated clicks and broker redelivery could create competing current results. Reusing one mutable attempt record was rejected because it erases the retry trail needed for diagnosis.

### 5. Preserve provenance in normalized operational state and immutable version snapshots

Mutable report, source metadata, import configuration, draft, jobs, and export operations remain normalized operational records. Original source bytes/text are immutable. Version creation produces a denormalized immutable snapshot containing all identifiers, values, unavailable reasons, provenance, narrative, and template version required to reproduce the report and its PDF.

PDF rendering receives only the snapshot-backed version view model, never the live draft. Creating a new draft from history copies snapshot content into a new mutable revision and leaves history untouched.

Reconstructing old reports by joining current mutable tables was rejected because mappings, objectives, narratives, prompts, and templates can change. Storing only rendered HTML or PDF was rejected because it would not preserve structured audit and reproduction inputs.

### 6. Keep arithmetic deterministic and AI interpretation bounded

Pandas/Python owns normalization, aggregate totals, KPI formulas, comparability, and unavailable reasons. AI receives bounded computed results, explicit limitations, objectives, and delimited untrusted source excerpts or labeled pasted claims. Structured output is validated before attachment and retains model and prompt provenance. Charts read computed data rather than AI prose.

Allowing AI to calculate or repair missing metrics was rejected because arithmetic would become non-reproducible and could blur claims with validated facts. Averaging row-level ratios and implicit currency conversion were rejected because both violate the product invariants.

### 7. Allocate verification evidence to the delivery stage that owns the behavior

This foundation change defines the full acceptance matrix, while later focused changes implement and verify their slice in dependency order:

| Delivery stage | Required evidence before handoff |
|---|---|
| Database/local infrastructure | PostgreSQL integration tests for UUID/FK/check constraints, ownership filters, revisions, legal job transitions, unique idempotency, immutable snapshots, and migration upgrade verification |
| Backend foundation | API contract tests for field validation, stable error codes, owner authorization on every resource, optimistic draft conflicts, persisted state serialization, and repeated-click idempotency |
| Data import/calculation | Unit and integration tests for original preservation, upload limits/type/encoding, previews, mappings, confirmation gate, invalid rows, ISO currency normalization, aggregate formulas, zero denominators, missing inputs, mixed currencies, and period comparability |
| Background jobs/AI | Deterministic fake-provider and worker tests for queue/run/succeed/fail transitions, redelivery, retries, stale input, bounded untrusted context, structured result validation, refusals/timeouts, and AI provenance |
| Versioning/PDF | Integration and fixed-snapshot rendering tests for atomic version numbers, complete immutable snapshots, repeated version clicks, exact-version PDF content, export failure/retry, authorized download, and draft cloning |
| Frontend | Component/browser tests for all explicit loading/empty/validation/job/failure/conflict states, keyboard/focus behavior, unsaved-edit preservation, and the seven-step journey |
| Integrated verification | PostgreSQL-backed and browser evidence for the entire create/import/confirm/analyze/edit/version/export/history path plus ownership isolation and safe retries |

Every downstream proposal and task list must name the applicable scenarios and exact commands. Live OpenAI and object-storage tests remain opt-in; deterministic adapter fakes and fixed snapshots are required in the default suite.

## Risks / Trade-offs

- **[Risk] A high-level workflow stage could drift from underlying records** → Derive it through one domain service from transactionally persisted facts and test every transition and recovery path.
- **[Risk] A broad lifecycle capability could encourage one umbrella implementation change** → Keep the delivery sequence explicit and require focused downstream OpenSpec changes to implement only their dependency-appropriate slice.
- **[Risk] Updating `project.md` and the capability spec can create duplicate wording** → Keep `project.md` concise and architectural; keep normative edge cases and scenarios only in the capability spec.
- **[Risk] Source or objective edits can make an in-flight analysis stale** → Capture semantic input identities and require an equality check before result attachment.
- **[Risk] Retries can create duplicate versions or mismatched exports** → Use database uniqueness, idempotency keys, transactional transitions, and immutable version binding rather than process-local coordination.
- **[Trade-off] The MVP accepts multiple valid ISO 4217 currencies but performs no conversion** → Preserve currency grouping and report cross-currency metrics or comparisons as unavailable.

## Migration Plan

1. Apply only the documentation alignment tasks in this foundation change; do not scaffold application code or infrastructure.
2. Run the artifact consistency checks and strict OpenSpec validation defined in `tasks.md`.
3. After human approval and completion, archive the change so `report-lifecycle` becomes a main capability spec.
4. Create and approve the focused delivery-stage changes in the order defined by `project.md`, with each change referencing and testing its applicable lifecycle scenarios.

There is no production data or deployed application to migrate. Before archive, rollback is removal or revision of this unimplemented planning change; after archive but before application implementation, rollback is a reviewed OpenSpec change that explicitly modifies the affected requirements rather than silently editing history.

## Open Questions

- The concrete authentication provider remains intentionally deferred to the backend-foundation change; the authenticated-principal interface and owner-authorization behavior are fixed by this change.
- Exact upload-size, preview-row, signed-URL lifetime, and provider-timeout values remain configuration decisions for their owning stage; changing those values within safe bounded behavior does not change this lifecycle contract.
