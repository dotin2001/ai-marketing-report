# AI Marketing Report Assistant

## Project Status

The repository is in the requirements-foundation stage. No application code or stage-specific infrastructure has been implemented. Each implementation stage will receive its own focused OpenSpec change rather than one umbrella change for the whole application.

## Product Goal

Build a web application that turns pasted marketing report content or a CSV upload into a validated, explainable, editable, versioned report. Deterministic Python code calculates metrics; AI interprets those results; immutable versions preserve provenance; PDFs are rendered from the exact saved version.

## MVP User Journey

1. Create a report with a name, reporting period, and analysis objectives.
2. Paste source content or upload a CSV file while preserving the original input.
3. Preview the parsed data, map supported columns, normalize values, and resolve blocking validation errors.
4. Calculate available KPIs in Python and run AI analysis as a background job.
5. Review metrics, charts, limitations, and AI narrative; edit narrative content and save a mutable draft.
6. create an immutable version and request PDF generation for that exact version.
7. Review version history, download completed PDFs, retry failed exports, or create a new draft from an older version.

## MVP Scope

- Pasted text and CSV input.
- One documented marketing CSV schema with user-correctable mapping.
- Preview, normalization, and field-level validation.
- Deterministic CTR, CPC, CPM, and CPL calculations when their inputs are available.
- AI-generated summary, findings, anomalies, recommendations, and data gaps.
- Editable report drafts, basic charts, one report layout, and one PDF template.
- Immutable version history and authorized PDF downloads.
- Persistent background-job status and safe retries.

## Non-goals

- Advertising-platform integrations, OCR, or arbitrary document extraction.
- Currency conversion, user-defined formulas, or unsupported KPI inference.
- Custom template builders or multiple PDF themes.
- Collaboration, comments, scheduled reporting, or automatic distribution.
- AI-generated arithmetic or invented source figures.

## Technology Baseline

| Area | Technology |
|---|---|
| Frontend | Next.js App Router, TypeScript |
| UI | Tailwind CSS, shadcn/ui |
| API | FastAPI, Pydantic |
| Processing | Python, pandas |
| Database | PostgreSQL |
| ORM and migrations | SQLAlchemy, Alembic |
| AI | OpenAI Python SDK, Responses API, Structured Outputs |
| Background work | Celery, Redis |
| PDF | Versioned HTML/CSS rendered with Playwright |
| File storage | S3-compatible object storage |

The OpenAI model is selected through `OPENAI_MODEL`. Model-specific options must be supported by the configured model or omitted. The implementation should use the current Python SDK Structured Outputs helper for the Responses API and Pydantic validation; official documentation must be rechecked when the AI integration is implemented.

## System Architecture

```text
+--------------------+          +----------------------+
| Next.js frontend   |  HTTPS   | FastAPI application  |
| forms, preview,    | <------> | authz, domain rules, |
| editor, history    |          | API and persistence  |
+--------------------+          +----------+-----------+
                                           |
                      +--------------------+--------------------+
                      |                    |                    |
                      v                    v                    v
             +----------------+   +----------------+   +----------------+
             | PostgreSQL     |   | S3-compatible  |   | Redis          |
             | metadata,      |   | original files |   | Celery broker  |
             | state, versions|   | and PDFs       |   |                |
             +----------------+   +----------------+   +-------+--------+
                                                                  |
                                                                  v
                                                        +----------------+
                                                        | Celery workers |
                                                        | pandas, OpenAI,|
                                                        | Playwright PDF |
                                                        +----------------+
```

PostgreSQL is authoritative for state. Redis delivers work but is not the job-status source of truth. Object storage holds binary originals and PDFs; PostgreSQL holds their ownership-aware references and metadata.

## Component Responsibilities

### Frontend

- Guides the user through report creation, import, mapping, validation, analysis, editing, versioning, export, and history.
- Polls or subscribes to persisted job status and presents explicit retry actions.
- Keeps unsaved edits separate from background results and does not manufacture domain state locally.

### FastAPI application

- Authenticates the caller and enforces report ownership on every operation.
- Validates API contracts, coordinates transactions, and applies report lifecycle rules.
- Creates idempotent jobs and versions, exposes status, and authorizes object downloads.
- Keeps provider credentials and internal storage details private.

### Processing layer

- Parses and normalizes CSV data with pandas.
- Produces validation issues and a confirmed canonical dataset.
- Calculates KPIs from aggregate inputs and records unavailable reasons.

### Celery workers

- Claim persisted queued jobs through transactional state transitions.
- Run AI analysis or PDF rendering using immutable or revision-checked inputs.
- Persist success or sanitized failure details and tolerate redelivery.

### Storage

- PostgreSQL stores report metadata, mappings, normalization settings, draft content, metrics, jobs, version snapshots, and export state.
- S3-compatible storage stores original CSV objects and generated PDF objects.

## Core Domain Model

- **User identity**: authenticated principal used for ownership. The concrete authentication provider remains a design decision; ownership enforcement is not optional.
- **Report**: owner-scoped UUID, name, inclusive reporting-period dates, one or more objectives, active-draft identity and revision, derived workflow stage, and created/updated timestamps. The end date cannot precede the start date.
- **Source**: immutable UUID and report-owner association; pasted-text or CSV type; creation time, byte size, checksum, media type or encoding; and either unchanged pasted content or an authorized object reference. CSV metadata retains the untrusted original filename separately from a safely normalized display filename.
- **Confirmed import configuration**: report/source identity, configuration revision and input revision, user-confirmed column mapping and normalization settings, validation summary, canonical-data identity or snapshot, confirmation timestamp, and provenance sufficient to reproduce the confirmed input.
- **Draft**: mutable identity, report owner, revision, objectives and narrative content, current metric/analysis references, labeled claims and limitations, and created/updated timestamps. Its revision is the compare-and-set boundary for optimistic saves.
- **Metric result**: immutable identity linked to the confirmed input; deterministic metric name, value and unit when available, input totals, aggregation scope, period, currency where applicable, calculation version, unavailable reason, and calculation timestamp.
- **Analysis result**: immutable identity linked to its logical job and semantic input identity; schema-validated `summary`, `findings`, `anomalies`, `recommendations`, and `data_gaps`; observation-versus-hypothesis labels; model identifier, prompt version, request provenance, and creation timestamp.
- **Logical job and attempt**: owner/report association, job type, semantic input identity, idempotency key, persisted state, current result reference, and created/updated timestamps belong to the logical operation. Each attempt records its ordinal, queue/start/finish timestamps and sanitized failure details without exposing provider internals.
- **Report version**: owner-scoped immutable UUID and sequential version number created atomically from one exact draft revision. Its creation timestamp and snapshot preserve report metadata, source references and checksums, confirmed configuration and canonical-data identity, metric inputs/results, AI and request provenance, edited narrative, limitations, labeled claims, and template version.
- **Version-bound PDF export**: owner and immutable-version identity, template/input identity, idempotency key, logical state and persisted attempts, timestamps, and either sanitized failure details or an authorized generated-object reference, metadata, and checksum. Internal object keys are never public authorization tokens.

## Lifecycle and State Rules

The user-facing report stage is derived from persisted report, current-source confirmation, metric, job, draft, and version facts. It is separate from analysis-job and PDF-export states.

| Current stage | Event and gate | Resulting stage |
|---|---|---|
| `created` | Attach an immutable pasted or CSV source | `source_review` |
| `source_review` | Explicitly confirm the current source review or valid mapping/normalization configuration, then finish deterministic metrics | `analysis_ready` |
| `analysis_ready` | Accept one logical analysis job for the current semantic input | `analysis_pending` |
| `analysis_pending` | Attach a validated result only when its captured input identity is still current | `reviewing` |
| `analysis_pending` | Current analysis fails | `analysis_ready`, retaining the failed job and prior valid result |
| `analysis_pending` | Source, configuration, objectives, or relevant draft revision changes | Reject the late result as stale and return to `source_review` or `analysis_ready` according to whether confirmation remains valid |
| `reviewing` | Atomically version the current draft revision | `versioned` |
| `versioned` | Save a narrative-only edit or clone history into a new active draft | `reviewing` |
| `reviewing` or `versioned` | Change source, mapping, normalization, reporting period, or objectives in a way that invalidates analysis | `source_review` or `analysis_ready`, according to whether the current confirmation remains valid |

PDF queueing, running, success, failure, and retry never change the report stage because each export belongs to an immutable version. New inputs and drafts never remove or alter prior versions or their exports.

### Editing and invalidation

- Draft saves require the expected revision and atomically advance it. A stale revision produces a stable concurrency error and preserves both stored and submitted content; polling and recoverable failures must preserve unsaved local edits.
- Users may edit narrative content, objectives, and other permitted draft fields. Original sources and deterministic metric values are non-editable. Saving a draft never creates an immutable version.
- Analysis freshness uses a semantic identity containing the report, source checksum or identity, import-configuration revision, canonical-data identity, metric-result identity and calculation version, objectives revision, and relevant draft revision. A timestamp alone is insufficient.
- A worker may persist the outcome of a stale attempt, but it cannot attach that result as current or overwrite newer draft content. Changed semantic inputs require a new logical analysis operation.
- Versions and completed PDFs are immutable. Restoring an older version copies its snapshot into a new revisioned active draft rather than mutating, renumbering, or replacing history.

### Logical analysis and PDF jobs

Both logical job types use exactly `queued`, `running`, `succeeded`, and `failed`. PostgreSQL is authoritative for state and attempts; Redis/Celery only delivers work. Idempotency keys, database uniqueness, and transactional transitions make repeated clicks and broker redelivery safe. Attempts retain retry-specific timestamps and sanitized failures, while clients receive stable safe errors rather than provider details.

- An analysis operation binds to one confirmed semantic input identity and one metric result. Retry may add an attempt or safely requeue the failed logical job only while that identity remains unchanged; it cannot create duplicate current results, replace a prior valid result on failure, or overwrite newer work.
- A PDF operation binds to one immutable report version, snapshot input identity, and template version. Retry adds an attempt or safely requeues that same logical export; it cannot create a report version, switch versions, or render from a mutable draft.

## CSV and Metric Baseline

The documented MVP CSV schema supports mapping to:

- Dimensions: `date`, `campaign_name`, `currency`.
- Measures: `impressions`, `clicks`, `spend`, `leads`.

`date`, `campaign_name`, and `currency` are required for structured CSV analysis. At least one supported measure must be present. Provided measures must parse as non-negative numeric values. Validation reports missing columns, unmapped columns, invalid rows, ambiguous dates, unsupported currencies, and mixed-currency aggregation risks before confirmation.

KPI formulas are:

- `CTR = aggregate clicks / aggregate impressions * 100`
- `CPC = aggregate spend / aggregate clicks`
- `CPM = aggregate spend / aggregate impressions * 1000`
- `CPL = aggregate spend / aggregate leads`

A KPI is unavailable when an input is absent, invalid, incompatible, or has a zero denominator. Ratios are calculated from aggregated numerators and denominators, never by averaging row ratios. Spend-based metrics are calculated only within a single currency group; the MVP does not convert currencies.

## AI Contract

AI receives validated metrics, explicit limitations, report objectives, and bounded source excerpts or claims. Source text is delimited and treated as untrusted data, never as instructions. Computed values and user-provided claims are labeled separately.

Structured output contains:

- `summary`
- `findings`
- `anomalies`
- `recommendations`
- `data_gaps`

The backend validates the result with Pydantic before persistence or display. Analysis must distinguish direct observations from causal hypotheses, avoid unsupported period comparisons, and avoid inventing figures. Provider errors, refusals, incomplete responses, and schema failures produce a failed job that can be retried.

## MVP Acceptance Criteria

### Steps 1–3: create, import, and confirm

- **Step 1 — create:** An authenticated user can create an owner-scoped report only with a non-empty name, an inclusive period whose end is not before its start, and at least one objective. Success creates one revisioned draft in `created` without a version or job; invalid input returns stable field-level errors and creates nothing.
- **Step 2 — preserve and preview:** Pasted text is stored unchanged with provenance and checksum. A CSV within configured size, content-type, and encoding limits is stored immutably through the storage abstraction with safe filename handling and an authorized preview; rejected files create no confirmed import, job, or public object reference. Both source types are treated as untrusted data and enter `source_review`; pasted claims remain labeled rather than becoming validated metrics.
- **Step 3 — map, normalize, and confirm:** CSV preview supports user-correctable mapping to `date`, `campaign_name`, `currency`, `impressions`, `clicks`, `spend`, and `leads`. Required dimensions and at least one measure must be mapped; measures normalize to non-negative numbers and currencies to valid uppercase ISO 4217 codes. Missing/duplicate mappings, unmapped columns, bad rows, ambiguous dates, unsupported currencies, and mixed-currency risks are explicit warnings or blocking errors. Only explicit confirmation after blocking errors are resolved persists the configuration/canonical-data identity and permits analysis. Pasted text receives an equivalent explicit source-review confirmation gate.

### Step 4: calculate and analyze

- Deterministic Python calculates aggregate CTR, CPC, CPM, and CPL; it never averages row ratios. Missing, invalid, incompatible, or zero-denominator inputs yield an unavailable metric with a reason, never zero, infinity, `NaN`, or an invented substitute. Spend metrics stay within one ISO 4217 currency group, no conversion is implicit, and incompatible periods are not compared.
- An owner-authorized, persisted, idempotent logical analysis job captures the current semantic input and moves through the shared job states. AI receives only computed metrics, explicit limitations and objectives, plus bounded, delimited untrusted excerpts or labeled claims; AI does not perform arithmetic or invent figures.
- Success requires the structured output schema and persists model, prompt, request, and numeric-source provenance before attachment. Timeouts, refusals, incomplete or invalid schemas, and provider errors become explicit sanitized failures with retry. Retry remains bound to unchanged input, and a stale result may be recorded but cannot attach to or overwrite newer work.

### Steps 5–7: review, version, export, and reopen

- **Step 5 — review and edit:** The owner sees computed metrics/charts with units and availability, limitations and data gaps, editable narrative, labeled claims, and AI provenance. Narrative saves use the expected revision; conflicts do not overwrite content, and a successful draft save creates no version.
- **Step 6 — version and export:** An owner-authorized, idempotent transaction creates one sequential immutable version from the exact current draft revision with the complete reproducibility snapshot. PDF generation is a separate persisted logical job rendered only from that version and template. Later draft changes cannot alter the saved version or completed PDF; failed export retry targets the same version without creating another.
- **Step 7 — history and restoration:** The owner receives ordered immutable history with creation/provenance summaries and persisted PDF status. Completed PDFs download only through an authorized backend response or short-lived signed URL. Retry remains bound to the selected historical version, and restoring history creates a new revisioned active draft while every historical version and PDF remains unchanged.

## Version and PDF Invariants

Each immutable report version preserves:

- Report metadata, reporting period, exact source draft revision, and sequential version identity.
- Source references and checksums.
- Confirmed mappings, normalization settings, validation summary, and canonical-data identity.
- Calculated metrics, inputs, scopes, currencies, calculation version, and availability metadata.
- Validated AI analysis, user-edited narrative content, limitations, and labeled claims.
- AI model identifier, prompt version, and request provenance.
- Report template version.
- Creation timestamp.

PDF export is a separate version-bound logical operation. Rendering consumes only the version snapshot; a failed export leaves the version intact, and export retry targets the same version without creating or switching a report version.

## Access Control

All user-visible resources inherit ownership from the report. The backend must verify the authenticated principal for reads, writes, jobs, version access, and downloads. Object keys are not authorization tokens. Downloads use a short-lived signed URL or an authorized backend response.

The concrete authentication mechanism must be selected before backend implementation. Until then, APIs should depend on an authenticated-principal interface so ownership rules do not depend on a specific provider.

## Delivery Sequence

Complete these stages sequentially. For every stage after project instructions, create, review, validate, and approve a focused OpenSpec change before implementation. Do not combine database, backend, and frontend implementation into one change.

### Stage 0: Project instructions

- Establish repository guidance and project context.
- Keep application code and stage-specific infrastructure out of this stage.
- Use `AGENTS.md` and `project.md` as context for every later OpenSpec change.

### Stage 1: Database and local infrastructure

- Create and approve a dedicated database and local-infrastructure OpenSpec change.
- Add PostgreSQL, Redis, and S3-compatible local services.
- Scaffold SQLAlchemy and Alembic.
- Implement the initial schema, constraints, migrations, and migration verification.

### Stage 2: Backend foundation

- Create and approve a dedicated backend OpenSpec change using the database contracts from Stage 1.
- Scaffold FastAPI, configuration, authentication boundary, ownership enforcement, repositories, and error contracts.
- Implement report, source, draft, job, version, and export APIs in dependency order.

### Stage 3: Data import and calculation

- Implement source preservation, CSV parsing, preview, mapping, normalization, validation, and deterministic KPIs.
- Complete focused unit and PostgreSQL integration tests.

### Stage 4: Background jobs and AI

- Add Celery orchestration, persisted job transitions, retries, and idempotency.
- Add the Responses API adapter, prompt versioning, Structured Outputs validation, and deterministic provider fakes.

### Stage 5: Versioning and PDF

- Implement atomic immutable-version creation, history, draft cloning, Playwright rendering, storage, downloads, and retry behavior.

### Stage 6: Frontend

- Create and approve a dedicated frontend OpenSpec change after the required backend contracts are stable.
- Scaffold Next.js, Tailwind CSS, and shadcn/ui.
- Build the guided workflow, validation UI, analysis status, report editor, charts, version history, and download states.

### Stage 7: Integrated verification

- Run migration, unit, integration, worker, PDF, and browser suites.
- Verify KPI correctness, version immutability, safe repeated clicks and retries, ownership isolation, and the complete browser journey.

### Downstream verification matrix

Each focused stage owns the evidence for its behavior and must name applicable lifecycle scenarios and exact verification commands in its proposal and tasks. This allocation does not authorize an umbrella implementation; stages remain sequential, and live OpenAI or object-storage checks remain opt-in while deterministic fakes and fixed snapshots run by default.

| Owning focused stage | Required evidence before handoff |
|---|---|
| Database and local infrastructure | PostgreSQL integration tests for UUID, foreign-key, and check constraints; ownership filters; revisions; legal job transitions; unique idempotency; immutable snapshots; and migration upgrade verification |
| Backend foundation/API | Contract tests for field validation, stable error codes, owner authorization on every resource, optimistic draft conflicts, persisted-state serialization, and repeated-click idempotency |
| Data import and calculation | Unit and integration tests for original preservation; upload size/type/encoding; previews; mappings; confirmation gates; invalid rows; ISO 4217 normalization; aggregate formulas; zero denominators; missing inputs; mixed currencies; and period comparability |
| Background jobs and AI | Deterministic fake-provider and worker tests for queue/run/succeed/fail transitions, redelivery, retry, stale input, bounded untrusted context, structured-result validation, refusals/timeouts, and AI provenance |
| Versioning and PDF | Integration and fixed-snapshot rendering tests for atomic version numbers, complete immutable snapshots, repeated version clicks, exact-version PDF content, export failure/retry, authorized download, and draft cloning |
| Frontend | Component and browser tests for explicit loading, empty, validation, job, failure, unavailable, retry, and conflict states; keyboard/focus behavior; unsaved-edit preservation; and the seven-step journey |
| Integrated verification | PostgreSQL-backed and browser evidence for create/import/confirm/analyze/edit/version/export/history, ownership isolation, and safe repeated delivery, clicks, and retries |

## Environment Configuration

Expected configuration groups include:

- Application: environment, public origins, API base URL, signing or authentication settings.
- PostgreSQL: application and migration database URLs.
- Redis/Celery: broker and worker settings.
- Object storage: endpoint, region, bucket, access credentials, path-style option, and signed-URL lifetime.
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`, request timeout, and prompt version.
- PDF: renderer timeout, template version, and browser executable settings where needed.

Secrets belong in local untracked environment files or a deployment secret manager. A committed example file may contain names and safe defaults but never credentials.

## Highest-priority Verification

1. KPI correctness across aggregate ratios, zero denominators, missing values, and currencies.
2. Database-enforced immutable versions and ownership isolation.
3. Idempotent version creation, job delivery, repeated clicks, and retries.
4. PDF generation from the exact version snapshot.
5. The main browser journey from report creation through history and download.
