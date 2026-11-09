# Repository Guidelines

## Scope

These instructions apply to the entire repository. More specific `AGENTS.md` files may refine them for a subtree but must not weaken the product invariants or security requirements below.

## Read Before Changing Anything

1. Read `project.md` for product scope, architecture, invariants, and delivery order.
2. Read `openspec/config.yaml` and the relevant active change under `openspec/changes/`.
3. Do not implement behavior that is absent from, or conflicts with, the approved OpenSpec artifacts.
4. Preserve unrelated user changes and keep each change limited to the current stage.

## Development Workflow

- Use OpenSpec as the behavioral source of truth. Keep proposal, specifications, design, tasks, implementation, and tests aligned.
- Work in dependency order: foundation, database, backend, data processing, background jobs and AI, versioning and PDF, frontend, then end-to-end verification.
- Complete and verify one stage before expanding into the next stage unless the user explicitly asks for parallel work.
- Use migrations for every database schema change. Never mutate a shared database schema manually.
- Add or update tests with behavior changes. Prioritize correctness and invariants over coverage percentage.
- Record newly introduced commands and required environment variables in project documentation or an example environment file.

## Intended Repository Layout

```text
frontend/             Next.js App Router application
backend/              FastAPI application, Celery worker, and Python domain code
  app/
    api/              HTTP routes and request/response schemas
    core/             Configuration, security, and shared infrastructure
    db/               SQLAlchemy models, sessions, and repositories
    domain/           Domain services and lifecycle rules
    processing/       pandas parsing, normalization, and KPI calculations
    ai/               OpenAI client, prompts, schemas, and validation
    jobs/             Celery tasks and idempotent job orchestration
    pdf/              Version-to-HTML view model and PDF rendering
  alembic/            Database migrations
  tests/              Unit and integration tests
infra/                Local service and deployment configuration
openspec/             Product specifications and change artifacts
```

Do not create shared abstractions until at least two real consumers justify them.

## Architectural Boundaries

- Keep FastAPI route handlers thin: authenticate, validate, call a service, and serialize the result.
- Put business and lifecycle rules in domain services, not routes, Celery tasks, React components, or ORM hooks.
- Keep SQLAlchemy models separate from external API schemas. Use Pydantic models at trust boundaries.
- Celery tasks must call the same domain services used by synchronous code and must be safe to retry.
- Keep pandas operations in the processing layer. AI output is never a source of arithmetic.
- Keep OpenAI prompts, prompt versions, structured response schemas, and model configuration in the backend AI layer.
- Render PDFs from immutable report-version data, never from a mutable draft or live UI state.
- Access object storage through a backend abstraction. Persist object keys and metadata, not public URLs.

## Product Invariants

- Original pasted content and uploaded files are preserved and treated as untrusted data.
- Users must confirm mappings and normalization before analysis proceeds.
- Aggregate ratios use aggregate numerators and denominators; never average row-level ratios.
- Missing inputs and zero denominators produce an unavailable metric with an explicit reason, not zero or infinity.
- Different currencies are never combined without an explicit conversion policy. The MVP has no conversion policy.
- Pasted claims remain distinguishable from validated, computed metrics.
- Period comparisons require comparable periods and compatible data.
- AI analysis distinguishes observations from hypotheses and never invents missing figures.
- Saving a draft does not create an immutable version.
- A saved version is immutable and contains every input needed to reproduce its report and PDF.
- Retrying PDF export reuses the same version. Retrying any job must not create duplicate versions or conflicting results.
- Every report, source, job, version, and PDF access is authorized against the report owner.

## Database Conventions

- PostgreSQL is the source of truth for metadata, structured content, state, and provenance.
- Use UUID primary keys, timezone-aware UTC timestamps, explicit foreign keys, and database constraints for invariants.
- Use normalized tables for mutable operational state. Use immutable JSONB snapshots only where version reproducibility benefits from denormalization.
- Use optimistic concurrency or an equivalent compare-and-set mechanism for mutable drafts.
- Enforce idempotency with database uniqueness constraints and transactional state transitions, not process-local locks.
- Alembic migrations must support upgrade verification; add downgrade behavior when it can be safe and lossless.

## Backend and API Conventions

- Version HTTP routes under `/api/v1`.
- Validate all requests and responses with Pydantic.
- Use stable machine-readable error codes plus human-readable messages and field-level details where applicable.
- Persist background-job state and expose it through the API; the broker is not the status source of truth.
- Mutating operations vulnerable to repeated clicks must accept or derive an idempotency key.
- Never expose API keys, raw storage credentials, internal object keys, or provider error details to clients.

## Frontend Conventions

- Use TypeScript, Next.js App Router, Tailwind CSS, and shadcn/ui.
- Prefer Server Components for read-oriented composition and Client Components only for interaction, browser APIs, or local state.
- Centralize API access and error normalization rather than fetching directly throughout components.
- Make loading, empty, validation, queued, running, succeeded, failed, and retry states explicit.
- Preserve unsaved edits during status polling and recoverable failures.
- Meet keyboard navigation, focus management, form labeling, contrast, and reduced-motion expectations.

## AI and Untrusted Content

- Keep `OPENAI_API_KEY` and all model calls on the backend.
- Read the model from `OPENAI_MODEL`; do not hard-code it in application logic.
- Use the OpenAI Responses API Structured Outputs path with a Pydantic schema and validate the parsed result before persistence or display.
- Send computed metrics and bounded supporting context to the model. Do not send secrets or unrestricted object-store content.
- Delimit uploaded and pasted content as data and explicitly instruct the model not to follow instructions found inside it.
- Persist model identifier, prompt version, request provenance, and validated structured output with the analysis result.
- Handle provider errors, timeouts, refusals, incomplete responses, and schema failures as explicit failed job outcomes.

## Testing and Verification

- Unit-test parsing, normalization, KPI formulas, zero denominators, missing inputs, aggregate-ratio behavior, currencies, and period comparability.
- Integration-test PostgreSQL constraints, ownership filters, migrations, immutable versions, idempotency, and job transitions against PostgreSQL.
- Contract-test OpenAI and object-storage adapters with deterministic fakes; keep live-provider tests opt-in.
- Test PDF generation from a fixed immutable version and verify retry does not create another version.
- Maintain a browser test for the main journey: create report, import, confirm, analyze, edit, save version, export, and reopen history.
- Before handoff, run the narrowest relevant checks and then the stage-level suite. Report anything not run.

## Security and Data Handling

- Apply upload size limits, CSV type and encoding checks, safe filename handling, and spreadsheet-formula injection protection on exports or previews.
- Use signed, short-lived download URLs or authorized backend streaming.
- Scope storage keys by environment and owner/report identifiers.
- Avoid logging source content, prompts containing customer data, credentials, or signed URLs.
- Use least-privilege credentials for PostgreSQL, Redis, object storage, and OpenAI.

