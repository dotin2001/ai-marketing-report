## Context

See `proposal.md` for motivation and `specs/application-workspace-and-local-infrastructure/spec.md` for normative behavior. The repository currently contains requirements, OpenSpec changes, and a dependency-free Node.js `ai:local` workflow, but no `frontend/`, `backend/`, or `infra/` application trees. The existing root `package.json`, tests, and Node 22 baseline belong to that workflow and must continue to work.

This is the first implementation stage in the dependency order established by `AGENTS.md`. It must create stable seams for later database and backend changes without creating product tables, domain APIs, background jobs, or cloud dependencies. Developers will run application processes on the host and stateful dependencies in containers. Local configuration is untrusted operational input and must not leak through health checks or logs.

## Goals / Non-Goals

**Goals:**

- Make frontend, backend, and local dependencies reproducible from documented, versioned inputs.
- Preserve the root AI workflow while adding concise proxy commands for application checks and infrastructure lifecycle operations.
- Establish package boundaries and typed configuration that later stages can extend without reorganizing the repository.
- Provide safe liveness and readiness contracts with unit-testable dependency probes.
- Make the fast verification path independent of Docker while retaining a separate, explicit live-infrastructure check.

**Non-Goals:**

- Containerize the frontend or backend, define production deployment, or add CI/CD configuration.
- Choose an authentication provider or implement report, source, import, metric, job, version, or PDF behavior.
- Create Alembic revisions, database tables, Redis queues, object upload APIs, or public buckets.
- Configure Celery, OpenAI, Playwright, pandas processing, or browser end-to-end tests before their dependency-ordered stages.
- Promise cross-platform shell parity beyond the documented Unix-like local environment; commands should remain portable where practical.

## Decisions

### 1. Keep three explicit project roots and preserve the existing root package

Create the following high-level structure:

```text
frontend/
  app/
  components/
  lib/
  tests/
  package.json
  package-lock.json
  components.json
  .env.local.example
backend/
  app/
    api/
    core/
    db/
    domain/
    processing/
    ai/
    jobs/
    pdf/
  tests/
  pyproject.toml
  uv.lock
  .env.example
infra/
  compose.yaml
  .env.example
docs/
  local-development.md
```

The frontend is an independent npm project because the root Node package is an operational tool rather than an application monorepo. The root `package.json` remains non-workspace ESM and keeps `ai:local`, `test`, and `check` unchanged; new namespaced proxy scripts may call `npm --prefix frontend ...`, `uv --directory backend ...`, and `docker compose --env-file infra/.env -f infra/compose.yaml ...`.

The backend uses a standard `pyproject.toml` plus a committed `uv.lock`, with a documented supported Python version and `uv` as the deterministic installer/runner. Runtime and development dependency groups remain separate. This avoids hand-maintained duplicate requirements files. `uv` was selected over raw `pip` because it provides a cross-platform lock and a single reproducible command; Poetry was rejected because its project model and configuration are unnecessary here.

The backend package tree is created now because it is an approved architectural boundary, but only `api`, `core`, and health-related infrastructure receive behavior in this stage. Placeholder packages contain at most documentation and `__init__.py`; no speculative shared abstractions are introduced.

### 2. Scaffold a minimal Next.js App Router foundation

Initialize `frontend/` with Next.js App Router, TypeScript strict mode, ESLint, Tailwind CSS, and the shadcn/ui configuration prerequisites. Use npm and commit `package-lock.json`. The initial page is a small accessible foundation screen that states the application is set up and provides no report workflow controls. It is a Server Component unless an interaction genuinely requires a Client Component.

Add scripts with stable meanings: `dev`, `build`, `start`, `lint`, `typecheck`, and `test`. Use a lightweight TypeScript-capable unit runner for foundation tests and keep browser tests for the later end-to-end stage. `NEXT_PUBLIC_API_BASE_URL` is documented in `.env.local.example`, but the initial render does not fail if the backend is absent because product UI/API integration is not part of this change. Only variables intentionally prefixed `NEXT_PUBLIC_` may reach the browser.

Using a root npm workspace was rejected because it couples application installation to the existing local-automation tool without a second JavaScript application consumer. Calling the backend from the initial page was rejected because it would add CORS and client-state behavior before an approved product flow requires either.

### 3. Build a thin FastAPI application with typed startup configuration

Use a FastAPI application factory in `backend/app/main.py` and strict settings in `backend/app/core/config.py` based on Pydantic Settings. Settings load from process environment and the documented local `.env` file, reject unknown or malformed application settings, validate URL schemes and timeouts, and reject known example placeholders. Tests instantiate settings explicitly so they do not depend on a developer's machine.

Use the project baseline components needed for readiness: SQLAlchemy's async engine with the PostgreSQL driver for `SELECT 1`, the asynchronous Redis client for `PING`, and an S3-compatible SDK client for a bucket `HEAD` operation. Client construction and closure occur in the FastAPI lifespan. No ORM model, metadata creation, Alembic revision, Redis queue, or object upload method is introduced.

Ruff provides formatting and linting, mypy provides type checks, and pytest provides unit/integration tests. The `pyproject.toml` contains their configuration so commands do not depend on global settings. The application import check creates the app under deterministic test configuration but does not contact dependencies until readiness is requested.

Running direct driver commands in the route handler was rejected because it makes timeouts, fakes, and resource cleanup difficult. Adding a generic repository or service framework was rejected because health probes have only one consumer and AGENTS.md prohibits premature abstractions.

### 4. Treat operational health routes separately from versioned product APIs

Mount `GET /health/live` and `GET /health/ready` outside `/api/v1`. These endpoints are operational contracts for local orchestration and future deployment probes, not versioned product resources. Future domain routes remain under `/api/v1`.

`/health/live` returns:

```json
{"status":"ok"}
```

It performs no dependency calls. `/health/ready` starts the three dependency probes concurrently, applies a short per-probe timeout, waits for all results, and returns only this shape:

```json
{
  "status": "ready",
  "dependencies": {
    "postgresql": "ready",
    "redis": "ready",
    "object_storage": "ready"
  }
}
```

If any probe fails or times out, the response uses HTTP `503`, top-level `status: "not_ready"`, and `"unavailable"` for each failed dependency. It never serializes exception messages, URLs, host names, bucket names, response bodies, or timing internals. Probe failures may be logged as sanitized dependency identifiers and stable categories; raw exceptions remain confined to debug-only internal handling and must be filtered for credentials.

The S3 probe is a bucket-level authorization/readiness check rather than a write/delete probe, so health calls cannot create objects. The bucket initializer owns idempotent creation. Sequential checks were rejected because accumulated timeouts would make readiness slow and hide simultaneous failures. A single `/health` endpoint was rejected because a dependency outage must not imply that the HTTP process is dead.

### 5. Use Docker Compose for stateful local dependencies only

Place one Compose file at `infra/compose.yaml` with these services:

- `postgres`: PostgreSQL with its data directory on a named volume and a `pg_isready` health check using the configured application database/user.
- `redis`: Redis with append-only persistence, password authentication from the environment, a named data volume, and an authenticated `PING` health check.
- `object-storage`: SeaweedFS as the local S3-compatible service, with its master, volume, filer, and S3 gateway running in the reviewed single-node development mode on one named data volume. The S3 gateway loads the configured access key and secret key through its supported AWS environment credential contract, which enables authentication without committing a generated credential file.
- `object-storage-init`: a one-shot SeaweedFS container that waits for the service and uses `weed shell` to create the configured bucket only when it is absent. Repeated starts leave the existing bucket metadata unchanged, and no anonymous identity or public bucket policy is configured.

Use explicit reviewed image tags and, where the repository's update policy permits, digest pins. Do not use `latest`. All host port mappings default to `127.0.0.1:<configurable-port>:<container-port>`. Containers communicate through the default project-scoped Compose network and deterministic service names. Compose receives a fixed documented project name so stop/reset commands cannot drift onto unrelated resources.

`infra/.env.example` contains conspicuous non-secret placeholders for passwords and local identities, plus documented port and bucket settings. The real `infra/.env` is ignored and must be created deliberately. Compose interpolation uses required-variable expressions so `docker compose config` fails before container creation if a required value is absent. The backend `.env.example` maps the same settings into credential-bearing URLs or separate fields consumed only by the backend; documentation explains the duplication and URL-encoding requirement.

SeaweedFS was selected because it provides a maintained, explicitly versioned S3-compatible image, authenticated S3 access, and a deterministic single-node development lifecycle without a cloud account. MinIO was rejected after its official community images were withdrawn from Docker Hub and its Quay mirrors stopped allowing anonymous pulls, making the approved clean-checkout workflow unreproducible. A full cloud emulator was rejected as heavier than the MVP storage boundary. Running PostgreSQL or Redis as host services was rejected because versions, health behavior, and cleanup would vary by developer machine. Containerizing the applications was deferred because fast host iteration and debuggers are sufficient at this stage.

### 6. Define the environment contract by consumer

The examples and setup guide use the following conceptual settings; implementation may group validated settings without renaming their external contract silently:

| Consumer | Settings |
|---|---|
| Frontend | `NEXT_PUBLIC_API_BASE_URL` |
| Backend core | `APP_ENV`, `APP_HOST`, `APP_PORT`, `HEALTH_CHECK_TIMEOUT_SECONDS`, `LOG_LEVEL` |
| PostgreSQL/backend | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` |
| Redis/backend | `REDIS_PASSWORD`, `REDIS_URL` |
| Object storage/backend | `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_USE_SSL` |
| Host ports | `POSTGRES_PORT`, `REDIS_PORT`, `S3_API_PORT`, `S3_CONSOLE_PORT` |

Production-only credentials such as `OPENAI_API_KEY` are not required in this stage. `OPENAI_MODEL` may remain documented in the broader project but must not gate application startup until AI integration exists. Local example values never become implicit production defaults: `APP_ENV` controls validation, and non-local environments reject development placeholders and insecure object-storage settings.

Separate examples were selected over a single root `.env` because each process should receive only its own settings. A generated consolidated environment file was rejected because generation adds a secret-copying tool and another synchronization surface.

### 7. Make setup commands explicit, layered, and safe

Add `docs/local-development.md` and link it from the root README. The guide specifies supported Node/npm, Python/uv, Docker Engine/Desktop, and Compose versions; exact commands to copy and edit examples; installation; static Compose validation; dependency startup with health waiting; backend/frontend startup; URLs; all verification commands; ordinary shutdown; troubleshooting; and the destructive reset.

The root proxy commands provide discoverability but documentation also shows the underlying scoped commands. The destructive reset uses the same explicit Compose project and file and removes only that project's declared volumes. It is labeled as data-destroying and is not part of ordinary cleanup. No command recursively deletes a broad directory, uses the home directory, or relies on an unresolved glob.

A single opaque bootstrap script was rejected because it would hide trust boundaries and make partial failure hard to diagnose. Manual, unrelated service commands were rejected because they increase naming and cleanup errors. The chosen middle ground is small namespaced proxy commands whose expanded operations are documented.

### 8. Split verification into fast checks and an opt-in live stack check

Fast checks run without live containers:

| Area | Required evidence |
|---|---|
| Existing root workflow | Existing `npm test` and `npm run check` remain green |
| Frontend | Clean install, lint, type-check, unit test, production build |
| Backend | Locked sync, Ruff format check/lint, mypy, pytest, app import |
| Configuration | Valid local settings load; missing, malformed, and placeholder settings fail without echoing values |
| Health contract | Faked probes cover all-ready, each dependency failing, timeout, concurrency, liveness independence, and response redaction |
| Compose | `docker compose config --quiet` succeeds with a test-only environment and rendered ports bind to loopback |

The live check starts the Compose project, waits with a bounded timeout, verifies service health and the private bucket, starts or targets the backend with local settings, checks `200` liveness/readiness, makes one dependency unavailable, checks `503` readiness plus `200` liveness, restores or stops services, and exits through ordinary shutdown. Tests use only project-scoped resources and do not require cloud credentials.

The live check is separate from fast suites because Docker availability is an environmental prerequisite. Omitting live verification entirely was rejected because static Compose validation cannot prove that images, commands, health checks, authentication, and bucket initialization work together.

## Risks / Trade-offs

- **[Risk] Image tags or ecosystem scaffolds can change upstream** → Commit lockfiles, avoid floating image tags, record the selected versions in the setup guide, and make upgrades explicit reviewed changes with full foundation verification.
- **[Risk] Example files can drift from typed settings or Compose interpolation** → Add tests that enumerate documented settings and render Compose from a dedicated sanitized test environment; treat missing documentation as a failing check.
- **[Risk] Credential-bearing URLs may be exposed by validation or driver exceptions** → Centralize settings redaction, reject placeholders without printing values, sanitize probe logs, and assert forbidden sample secrets are absent from responses and captured logs.
- **[Risk] Readiness checks can overload dependencies or hang requests** → Use minimal read-only operations, concurrent probes, short bounded timeouts, and no retries within one HTTP health request.
- **[Risk] SeaweedFS behavior can differ from production S3 providers** → Keep later storage access behind the backend abstraction, test only the common bucket/object contract, and reserve provider-specific validation for the storage implementation stage.
- **[Trade-off] Applications run on the host while dependencies run in containers** → Document both host and container address forms clearly; defer application images until deployment requirements exist.
- **[Trade-off] Redis authentication and object-store credentials add local setup steps** → Keep explicit copy/edit instructions because exercising authenticated paths locally is closer to the security boundary than anonymous defaults.
- **[Risk] A reset command could remove unrelated local data** → Fix the Compose project name and file, enumerate target volumes in documentation, keep reset separate from stop, and test rendered resource names before documenting the command.

## Migration Plan

1. Preserve and run the existing root workflow checks to establish the pre-change baseline.
2. Add ignore rules and sanitized environment examples before any developer creates real local settings.
3. Add and statically validate the Compose definition, then prove the three services and private bucket initialize in isolation.
4. Add the backend skeleton, typed settings, clients, health probes, and unit tests; verify readiness against the live dependency stack without product migrations.
5. Add the frontend skeleton and foundation tests/build without coupling it to unfinished product APIs.
6. Add root proxy commands and the local-development guide, then execute both the fast matrix and clean-setup live walkthrough.

There is no production or data migration. Rollback stops the explicit Compose project, preserves its volumes by default, and removes the new application/infra files through normal version-control reversal. If local data must also be discarded, the operator uses the separately documented project-scoped reset; rollback never deletes volumes implicitly.
