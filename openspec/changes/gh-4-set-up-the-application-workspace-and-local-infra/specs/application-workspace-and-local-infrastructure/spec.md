## Purpose

Provide a reproducible, secure local foundation in which developers can run and verify the frontend, backend, PostgreSQL, Redis, and object storage before product behavior is added.

## ADDED Requirements

### Requirement: Application workspaces are independently operable
The repository SHALL provide a Next.js App Router TypeScript workspace under `frontend/` and a FastAPI Python workspace under `backend/`, aligned with the repository layout and technology baseline. Each workspace SHALL declare and lock or constrain its own dependencies, expose documented commands for installation, static checks, tests, production build or import validation, and development startup, and start without requiring product tables, background jobs, AI credentials, or external cloud services. The initial applications MUST NOT implement report-domain behavior that belongs to a later OpenSpec change.

#### Scenario: Frontend foundation is verified
- **WHEN** a developer follows the documented clean-install procedure in `frontend/`
- **THEN** the frontend lint, type-check, test, and production-build commands complete successfully
- **AND** the development server renders the documented foundation page without depending on product APIs that do not yet exist

#### Scenario: Backend foundation is verified
- **WHEN** a developer follows the documented environment and dependency procedure in `backend/`
- **THEN** the backend formatting or lint, type-check, test, and application-import checks complete successfully
- **AND** the development server starts without applying a database migration or creating product-domain state

#### Scenario: Foundation scope remains bounded
- **WHEN** the initialized workspaces are inspected
- **THEN** they contain the intended frontend and backend layer boundaries plus only the minimum foundation behavior needed for startup and health verification
- **AND** they contain no report routes, authentication implementation, product schema migrations, processing pipelines, Celery tasks, OpenAI calls, or PDF behavior

### Requirement: Environment configuration is explicit and non-secret
The repository SHALL commit non-secret environment example files for the frontend, backend, and local infrastructure. The examples SHALL document every required variable, its purpose, expected format, whether it is required or has a local-only default, and which process consumes it. Runtime configuration SHALL fail before serving requests when a required value is absent or malformed, while real environment files, credentials, generated secrets, and provider keys SHALL remain ignored. Logs, health responses, browser-visible configuration, and setup output MUST NOT expose database passwords, object-storage secret keys, API keys, connection strings containing credentials, or signed URLs.

#### Scenario: Examples are sufficient for local startup
- **WHEN** a developer copies each committed example to its documented local filename and replaces any explicitly required placeholder
- **THEN** the applications and local services receive every setting needed for the documented startup path
- **AND** no undocumented secret or machine-specific value is required

#### Scenario: Invalid required configuration fails closed
- **WHEN** a required backend or infrastructure value is missing, left as a forbidden placeholder, or has an invalid type or URL format
- **THEN** the affected process exits or remains unready with a concise setting-specific error
- **AND** it does not continue with an insecure production-like fallback or print the rejected secret value

#### Scenario: Secret-bearing files remain untracked
- **WHEN** a developer creates the documented real environment files or tool-generated local credentials
- **THEN** repository ignore rules exclude those files from ordinary version control discovery
- **AND** only sanitized examples remain versioned

### Requirement: Local dependencies are reproducible and isolated
The repository SHALL define one local orchestration configuration for PostgreSQL, Redis, and S3-compatible object storage using reviewed, explicitly versioned container images. Each service SHALL have a project-scoped persistent named volume, a deterministic internal service name, a container health check, restart-safe configuration, and only the minimum documented host ports bound to the loopback interface by default. Configuration and credentials SHALL be supplied through the local environment contract rather than embedded in images or source. The object-storage startup flow SHALL idempotently ensure the configured development bucket exists without making it public.

#### Scenario: Local services become healthy
- **WHEN** a developer starts the local dependency stack with valid configuration on an available host
- **THEN** PostgreSQL, Redis, and object storage reach their declared healthy states within the documented startup window
- **AND** the configured private development bucket exists and is accessible only with the configured local credentials

#### Scenario: Service state survives ordinary shutdown
- **WHEN** the dependency stack is stopped and later started without requesting a reset
- **THEN** each service reuses its project-scoped named volume
- **AND** previously written development data remains available

#### Scenario: Host exposure is bounded
- **WHEN** the rendered orchestration configuration is inspected with default local settings
- **THEN** database, cache, object API, and optional object console ports are bound only to the loopback interface
- **AND** no service grants anonymous object access or uses a host-network mode

#### Scenario: Configuration is invalid before containers start
- **WHEN** a required port, database identity, object-store identity, or bucket setting is missing or malformed
- **THEN** orchestration configuration validation fails before an apparently healthy stack is reported
- **AND** the error identifies the setting without disclosing another credential

### Requirement: Health contracts distinguish liveness from readiness
The backend SHALL expose `GET /health/live` for process liveness and `GET /health/ready` for dependency readiness. Liveness SHALL return HTTP `200` with a stable machine-readable status when the application event loop can serve requests and SHALL NOT contact dependencies. Readiness SHALL check PostgreSQL, Redis, and the configured private object-storage bucket using bounded timeouts; it SHALL return HTTP `200` only when all required dependencies are usable and HTTP `503` otherwise. Health responses SHALL use stable status values and dependency identifiers but MUST NOT include credentials, connection strings, object keys, stack traces, raw driver/provider errors, host filesystem paths, or customer data.

#### Scenario: Live application reports liveness
- **WHEN** the backend process can serve HTTP requests regardless of dependency availability
- **THEN** `GET /health/live` returns HTTP `200` with `status` equal to `ok`
- **AND** the response performs no PostgreSQL, Redis, or object-storage call

#### Scenario: Ready application reports dependency health
- **WHEN** PostgreSQL accepts a minimal query, Redis accepts a ping, and the configured private bucket can be checked within their timeouts
- **THEN** `GET /health/ready` returns HTTP `200` with `status` equal to `ready`
- **AND** it reports `postgresql`, `redis`, and `object_storage` as ready using only safe machine-readable fields

#### Scenario: Unavailable dependency fails readiness safely
- **WHEN** any required dependency is unavailable, misconfigured, unauthorized, or exceeds its health-check timeout
- **THEN** `GET /health/ready` returns HTTP `503` with `status` equal to `not_ready` and identifies each unavailable dependency
- **AND** the process remains live while the response and logs omit credentials and raw dependency error details

### Requirement: Developer setup and lifecycle operations are documented
The repository SHALL provide one discoverable setup guide that states supported tool prerequisites and versions; explains environment-file creation; identifies which processes run on the host and in containers; provides startup order and commands; lists application and dependency health checks; and provides test, shutdown, troubleshooting, and update instructions. Ordinary shutdown SHALL preserve data. Any command that removes local volumes or generated data SHALL be separately labeled destructive, name the project-scoped resources it affects, require deliberate invocation, and avoid broad or unresolved filesystem targets.

#### Scenario: New developer completes setup
- **WHEN** a developer with the documented prerequisites follows the guide from a clean checkout-equivalent state
- **THEN** the dependency stack becomes healthy, the backend becomes ready, and the frontend foundation page loads
- **AND** every invoked command and expected endpoint is described without requiring tribal knowledge

#### Scenario: Developer stops without losing data
- **WHEN** a developer follows the ordinary shutdown procedure
- **THEN** application processes and containers stop cleanly while project-scoped named volumes remain
- **AND** restarting through the documented path restores the prior local service state

#### Scenario: Developer deliberately resets local state
- **WHEN** a developer explicitly chooses the documented destructive reset procedure
- **THEN** only the named application-local containers, networks, volumes, and generated artifacts identified by the guide are eligible for removal
- **AND** the procedure does not target a home directory, workspace root, unrelated container resources, or unresolved wildcard path

### Requirement: Foundation verification is deterministic
The implementation SHALL provide automated checks for the workspace contracts, backend health behavior, configuration validation, and rendered local-orchestration definition. Live integration verification SHALL prove that all three dependencies become healthy and that backend readiness changes from ready to not ready when a required dependency becomes unavailable. Checks SHALL avoid external account requirements, MUST NOT mutate shared or production services, and SHALL document any container-dependent test separately from the fast workspace suites.

#### Scenario: Fast foundation checks pass without live infrastructure
- **WHEN** the documented non-container verification commands run with deterministic test configuration
- **THEN** frontend checks, backend checks, configuration-unit tests, health-response contract tests with faked dependencies, and static orchestration validation pass
- **AND** no external provider, production credential, or shared database is contacted

#### Scenario: Live dependency verification passes locally
- **WHEN** the container-dependent integration procedure runs against the project-scoped local stack
- **THEN** it waits for PostgreSQL, Redis, and object storage health, verifies backend readiness, and records a clear pass or bounded failure
- **AND** cleanup follows the ordinary non-destructive shutdown path unless the operator explicitly requests the documented reset

#### Scenario: Readiness regression is detected
- **WHEN** one required local dependency is stopped or made unreachable during the readiness integration test
- **THEN** the test observes HTTP `503` and the correct safe unavailable dependency identifier within the documented timeout
- **AND** liveness continues to return HTTP `200`
