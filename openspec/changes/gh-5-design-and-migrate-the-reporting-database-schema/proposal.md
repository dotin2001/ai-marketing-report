## Why

The application workspace and local PostgreSQL service now exist, but the reporting domain has no durable schema or migration history. Defining the ownership, provenance, concurrency, idempotency, and immutability constraints at the database boundary is the next dependency-ordered step and prevents later API, processing, worker, and PDF stages from encoding incompatible persistence assumptions.

## What Changes

- Add SQLAlchemy 2.x models and repositories for owner identities, reports, revisioned drafts, immutable text/CSV sources, import configurations and validations, confirmed datasets and canonical rows, metric result sets, analysis jobs and attempts, validated analysis results, report versions, PDF export jobs and attempts, file-asset metadata, and idempotency records.
- Add PostgreSQL constraints and indexes for UUID identities, timezone-aware timestamps, ownership-safe relationships, inclusive report periods, positive revisions and sequence numbers, exact job states, one-to-one mappings, metric availability, legal attempt ordinals, scoped idempotency, deterministic pagination, and version/export uniqueness.
- Store mutable operational state in normalized tables while preserving complete report-version reproducibility in immutable JSONB snapshots; persist object-storage keys and metadata without public URLs or credentials.
- Scaffold Alembic against the application's SQLAlchemy metadata, create the initial schema migration, and provide guarded upgrade verification against PostgreSQL without runtime `create_all` schema mutation.
- Add PostgreSQL integration tests for constraints, ownership filters, optimistic revisions, legal job transitions, idempotent logical operations and attempts, immutable versions, file-asset bindings, migration upgrade/downgrade behavior, and clean-schema parity.
- Document the database and migration commands plus required non-secret configuration while leaving API routes, parsing/KPI execution, Celery orchestration, AI calls, object upload/download, PDF rendering, and frontend behavior to their later approved stages.

## Capabilities

### New Capabilities

- `reporting-database-schema`: PostgreSQL persistence contracts, relational constraints and indexes, immutable snapshot and file-asset metadata boundaries, SQLAlchemy/Alembic integration, ownership-safe data access, and migration verification for the reporting lifecycle.

### Modified Capabilities

None.

## Impact

- Affects `backend/app/db/`, `backend/alembic/`, `backend/tests/`, backend dependency and tool configuration, and database-focused developer documentation and commands.
- Uses the existing PostgreSQL service and `DATABASE_URL`; no new external service, public API, authentication provider, object-storage operation, or deployment resource is introduced.
- Establishes persistence contracts consumed by the later backend, import/calculation, background-job/AI, version/PDF, and frontend changes.
- The initial migration creates new application tables only; the repository has no production reporting data or prior product schema to transform.

## Acceptance Criteria

- Reports, imports, datasets, analysis runs, drafts, report versions, export jobs, and file assets have implementation-ready SQLAlchemy models and Alembic-managed PostgreSQL tables aligned with the approved lifecycle, import/KPI, and API contracts.
- Foreign keys, check constraints, uniqueness constraints, and indexes enforce ownership consistency, valid revisions and periods, mapping cardinality, metric availability semantics, legal persisted states, scoped idempotency, attempt ordering, sequential version identity, immutable snapshot binding, and version-bound exports.
- Original source metadata and object references remain immutable and untrusted; internal object keys are persisted without public URLs, credentials, signed URLs, or using object keys as authorization tokens.
- Repository access paths always anchor child-resource reads and writes through the owning report/principal, and tests prove cross-owner identifiers cannot return or mutate another owner's records.
- Draft updates and mutable import configuration use compare-and-set revisions; logical jobs, retries, versions, exports, and idempotent commands use transactional uniqueness so repeated requests or delivery cannot create duplicate logical results, attempts, or sequence gaps.
- Saved report versions contain a complete immutable reproducibility snapshot, and database enforcement prevents update or delete paths from changing a committed version while export retries remain bound to the same version.
- A fresh PostgreSQL database upgrades to the current head, schema/model parity is verified, downgrade behavior is tested where safe and lossless, and application startup never creates or mutates product tables implicitly.

## Verification

- Run the database unit and PostgreSQL integration suites covering models, repositories, constraints, ownership isolation, optimistic revisions, job transitions, idempotency, attempt deduplication, immutable snapshots, file assets, and deterministic indexes.
- Run Alembic upgrade verification from an empty database, compare the migrated schema with SQLAlchemy metadata, exercise safe downgrade and re-upgrade, and verify a second upgrade is a no-op.
- Run the backend formatting/lint, type-check, and existing health/configuration tests to ensure the database layer does not regress the approved workspace foundation.
- Inspect generated migration SQL and PostgreSQL catalog metadata for every required foreign key, check, unique constraint, index, UUID key, and timezone-aware timestamp; verify no secret, public object URL, or unrestricted source value is introduced into diagnostics.
- Run `openspec validate gh-5-design-and-migrate-the-reporting-database-schema --strict --json` and require a valid result with no issues; verify exactly one versioned traceability marker exists in `proposal.md` and none exists in another artifact.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhHa4Wo","issueId":"I_kwDOVnzly88AAAABd54VnQ","branch":"feature/database","baseCommit":"5990e44cf1e5a47549e7559a66d40508c7c6ac95","changeId":"gh-5-design-and-migrate-the-reporting-database-schema","projectNumber":2,"issueNumber":5} -->
