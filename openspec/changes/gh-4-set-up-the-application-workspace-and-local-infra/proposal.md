## Why

The repository has approved product requirements but no application workspace or reproducible local runtime in which later database, backend, processing, job, and frontend stages can be implemented. Establishing the dependency-ordered project skeleton and health-checked local services now gives those later changes a consistent development boundary without implementing product behavior ahead of its approved OpenSpec stage.

## What Changes

- Initialize the intended `frontend/` Next.js App Router workspace with TypeScript, Tailwind CSS, and the shadcn/ui prerequisites, while keeping the initial surface limited to a foundation page and health-aware development configuration.
- Initialize the intended `backend/` FastAPI Python workspace with the repository's layered package structure, typed configuration, a versioned application entry point, and a lightweight HTTP health endpoint that does not require product tables or credentials in its response.
- Add a local container orchestration definition for PostgreSQL, Redis, and S3-compatible object storage, including persistent named volumes, health checks, least-privilege development credentials supplied through environment variables, and non-conflicting service dependencies.
- Provide committed, non-secret environment examples for the frontend, backend, and local infrastructure, with fail-fast validation for required values and safe local defaults only where appropriate.
- Provide deterministic setup, startup, health-verification, test, shutdown, and data-reset instructions for a new developer, including prerequisites and the boundary between host-run applications and containerized dependencies.
- Add focused foundation verification for workspace builds/imports, configuration loading, the backend health contract, container-configuration validity, and live dependency health without introducing product-domain behavior or schema migrations.

## Capabilities

### New Capabilities

- `application-workspace-and-local-infrastructure`: Reproducible frontend and backend workspaces, local PostgreSQL/Redis/object-storage services, environment contracts, health checks, and developer setup verification.

### Modified Capabilities

None.

## Impact

- Adds the initial `frontend/`, `backend/`, and `infra/` trees described by `project.md`, plus root-level developer commands and documentation needed to operate them.
- Introduces Node/Next.js, Python/FastAPI, container-image, PostgreSQL, Redis, and S3-compatible object-storage dependencies whose versions must be pinned or bounded through their native lock/configuration files.
- Establishes only foundation and health behavior; it does not add product routes, authentication, database tables or migrations, Celery jobs, OpenAI calls, report processing, PDF rendering, or deployment configuration.
- Keeps PostgreSQL as the future metadata source of truth, Redis as delivery infrastructure rather than state authority, and object storage behind future backend abstractions.

## Acceptance Criteria

- Next.js and FastAPI application workspaces are initialized in the repository's intended layout and can be installed, statically checked, tested, and started using documented commands.
- PostgreSQL, Redis, and local S3-compatible object storage are defined for local development with persistent storage, bounded host exposure, explicit health checks, and configuration supplied without committed secrets.
- Committed environment examples document every setting required to start and verify the foundation; real local environment files and credentials remain ignored.
- The backend exposes a documented health contract that distinguishes application liveness from dependency readiness and returns only safe status information.
- Setup instructions take a new developer from prerequisites through startup and health verification, and document ordinary shutdown plus an explicit destructive local-data reset.

## Verification

- Run the frontend's documented install, lint, type-check, test, and production-build commands from a clean dependency state.
- Run the backend's documented environment creation, dependency installation, formatting/lint, type-check, test, and application-import checks.
- Validate the local orchestration configuration, start PostgreSQL, Redis, and object storage, wait for every declared container health check, and verify their documented readiness probes.
- Start the backend against the healthy local dependencies and verify the liveness and readiness response bodies, status codes, safe redaction, and failure behavior when a dependency is unavailable.
- Follow the setup guide from a clean checkout-equivalent state, confirm environment examples are complete, and verify ordinary shutdown preserves named-volume data while the explicitly labeled reset removes only project-scoped local data.
- Run `openspec validate gh-4-set-up-the-application-workspace-and-local-infra --strict --json` and require a valid result with no issues; also verify exactly one traceability marker exists in `proposal.md` and none exists in another artifact.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa3JA","issueId":"I_kwDOVnzly88AAAABd53RCg","branch":"feature/set_up","baseCommit":"c78cb427e7940b7153cfa4130418e9866bb816ba","changeId":"gh-4-set-up-the-application-workspace-and-local-infra","projectNumber":2,"issueNumber":4} -->
