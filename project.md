# AI Marketing Report Assistant

## Project Status

The repository is in the project-instruction stage. No application code has been implemented and there is no active OpenSpec change. Each implementation stage will receive its own focused OpenSpec change rather than one umbrella change for the whole application.

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
- **Report**: owned container with name, reporting period, objectives, active draft, and timestamps.
- **Source**: immutable pasted-text record or uploaded-object reference with content metadata and checksum.
- **Import configuration**: confirmed column mapping, normalization settings, validation summary, and canonical-data reference or snapshot.
- **Draft**: mutable report content with a revision used for optimistic concurrency.
- **Metric result**: deterministic values, units, inputs, aggregation scope, and unavailable reasons.
- **Analysis result**: validated structured AI output plus model identifier and prompt version.
- **Job**: persisted operation with type, state, attempt information, idempotency key, input identity, result reference, and sanitized error.
- **Report version**: immutable snapshot of source references, configuration, metrics, content, AI provenance, template version, and creation time.
- **PDF export**: version-bound export state and generated-object reference.

## Lifecycle and State Rules

```text
Report draft
    |
    +--> source imported --> mapping confirmed --> metrics calculated
                                                  |
                                                  v
                                        AI job queued/running
                                                  |
                                      +-----------+-----------+
                                      v                       v
                                  succeeded                failed
                                      |                       |
                                      v                       +--> retry
                              editable draft saved
                                      |
                                      v
                           immutable version created
                                      |
                                      v
                                PDF job queued
                                      |
                         +------------+------------+
                         v                         v
                     succeeded                  failed
                         |                         |
                         v                         +--> retry same version
                     download
```

Allowed job states are `queued`, `running`, `succeeded`, and `failed`. A retry creates a new attempt for the same logical operation or safely requeues the failed job; it must not duplicate a report version or overwrite a newer draft result.

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

## Version and PDF Invariants

Each immutable report version preserves:

- Source references and checksums.
- Confirmed mappings and normalization settings.
- Calculated metrics and their availability metadata.
- AI analysis and user-edited narrative content.
- AI model identifier and prompt version.
- Report template version.
- Version number and creation timestamp.
- PDF reference and export status.

PDF rendering consumes only the version snapshot. A failed export leaves the version intact, and export retry targets the same version without creating a duplicate.

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
