## Context

See `proposal.md` for motivation and `specs/reporting-database-schema/spec.md` for normative behavior. The applied workspace change already provides PostgreSQL 17.6 locally, SQLAlchemy 2.1 with its async API, psycopg 3, a strict secret-bearing `DATABASE_URL`, and a lifespan-owned engine used only by the readiness probe. `backend/app/db/` is otherwise a placeholder; there is no declarative metadata, session boundary, domain repository, Alembic configuration, product table, or migration revision.

The database must serve later FastAPI and Celery processes without becoming the location for lifecycle business logic. It must nevertheless make invalid ownership relationships, impossible field combinations, duplicate logical operations, and mutation of historical records unrepresentable. Authentication remains provider-neutral, Redis remains delivery-only, and object storage remains the binary store; PostgreSQL retains authoritative state and private object references.

## Goals / Non-Goals

**Goals:**

- Define one implementation-ready relational model for every resource family named by issue 5 and the approved lifecycle/API contracts.
- Make owner/report consistency, immutable provenance, compare-and-set revisions, scoped idempotency, attempt ordering, and sequential report versions safe under concurrent API and worker transactions.
- Keep mutable operational state normalized while using one schema-versioned JSONB snapshot where denormalization is necessary to reproduce immutable versions and PDFs.
- Establish Alembic as the only product-schema writer, separate runtime and migration concerns, and make PostgreSQL migration/constraint verification deterministic and fail closed.
- Provide small repository operations for atomic database invariants without implementing HTTP routes, processing, workers, storage I/O, or later-stage domain behavior.

**Non-Goals:**

- Implement authentication, public API serialization, pandas parsing/KPI calculation, Celery delivery, OpenAI calls, object upload/download, PDF rendering, or frontend flows.
- Store uploaded bytes or generated PDFs in PostgreSQL, expose object keys, or define a public file URL.
- Add general deletion, retention, audit-log, collaboration, soft-delete, tenant administration, analytics warehouse, full-text search, or database row-level-security behavior to the MVP.
- Encode report workflow stage as a mutable database enum; later domain services derive it from current persisted facts.
- Use schema events or ORM hooks as substitutes for domain-service transitions and transactions.

## Decisions

### 1. Use typed SQLAlchemy metadata and Alembic with PostgreSQL-native constraints

Add `app/db/base.py` with SQLAlchemy 2.x typed declarative metadata and a deterministic naming convention for primary keys, foreign keys, unique constraints, checks, and indexes. Add async session construction in `app/db/session.py`, but do not create a process-global session or call `metadata.create_all`. Domain transactions receive an `AsyncSession`; health keeps using the existing engine directly.

Add Alembic as a pinned runtime/tooling dependency, `backend/alembic.ini`, an async `backend/alembic/env.py`, and `backend/alembic/versions/`. Alembic imports the same metadata used by the models. Online migrations read `MIGRATION_DATABASE_URL`; offline SQL generation accepts a sanitized command-supplied URL and never prints it. Runtime settings continue to expose `DATABASE_URL` to the application role. `MIGRATION_DATABASE_URL` and `TEST_DATABASE_URL` are documented server-only settings and are not placed in `Settings` used by the web process unless a runtime consumer actually needs them.

UUID primary keys use PostgreSQL `uuid` with `gen_random_uuid()` server defaults. Instants use `timestamptz` with `CURRENT_TIMESTAMP`; domain code normalizes them to UTC on serialization. Calendar dates remain `date`. Exact amounts and metric values use unconstrained PostgreSQL `numeric` plus finite/non-negative checks where applicable; counts use `bigint`. Text-backed enumerations use named check constraints rather than PostgreSQL enum types so later additive changes do not require enum-type surgery. JSONB is reserved for the immutable version snapshot.

Using SQLite or `create_all` for tests was rejected because neither verifies PostgreSQL checks, partial indexes, deferrable relationships, triggers, JSONB, or migration order. Native enum types were rejected because the exact values are still an application contract but check constraints provide simpler reviewed migrations. Fixed `numeric(p,s)` was rejected because it can silently round or reject otherwise valid exact source decimals before a product limit has been approved.

### 2. Carry owner and report identity through every aggregate relationship

`principals` is the provider-neutral identity boundary:

| Column group | Contract |
|---|---|
| Identity | `id`, `identity_namespace`, opaque `subject` |
| Lifecycle | `created_at` |
| Constraints | unique `(identity_namespace, subject)`; neither value is a credential or display profile |

Every owner-visible descendant contains `owner_id` and `report_id` even when its UUID is globally unique. `reports` exposes a unique key on `(id, owner_id)`, and descendants use composite foreign keys beginning with `(report_id, owner_id)`. Deeper relationships repeat the aggregate keys, for example a dataset-to-confirmation foreign key includes dataset `report_id`, `owner_id`, and the referenced confirmation identity. This makes a cross-owner or cross-report link fail at the database boundary and makes owner-scoped query predicates indexable.

Repository reads take `owner_id` plus the parent `report_id` before a child identifier. Mutations put the same predicates in `UPDATE` or `DELETE` statements; an affected-row count of zero is the only not-found/stale signal returned to the later domain layer. Repositories never provide an unscoped `get(child_id)` method to API or worker consumers. Foreign keys default to `RESTRICT`; this MVP has no cascade deletion of historical data.

PostgreSQL row-level security was considered but deferred. The application has one database role and no reviewed mechanism to set a transaction-local principal safely across every connection, so premature RLS would create a false security boundary. Composite ownership constraints plus scoped repositories are testable now and do not prevent a later dedicated RLS change.

### 3. Model the mutable report and draft as normalized rows

The report/draft group is:

| Table | Important fields and constraints |
|---|---|
| `reports` | owner, trimmed `name`, `period_start`, `period_end`, timestamps, and nullable current source/dataset/metric/analysis pointers; check `period_end >= period_start` |
| `report_drafts` | owner/report, positive `revision`, `is_active`, timestamps, optional current metric-result-set and analysis-result references; one active draft per report through a partial unique index |
| `draft_objectives` | draft identity/revision-independent stable item UUID, positive ordinal, non-empty text; unique draft ordinal |
| `draft_narrative_items` | draft, one of five section names, stable item UUID, positive ordinal, bounded text, optional classification; unique section/ordinal |
| `draft_limitations` | draft, stable item UUID, positive ordinal, non-empty text |
| `draft_claims` | draft, stable item UUID, positive ordinal, non-empty text, mandatory `user_claim` classification and optional source reference |
| reference joins | normalized links from narrative items to metric results or claims, with aggregate-consistent composite foreign keys |

The initial create-report transaction inserts the report, an active draft at revision 1, and at least one objective. A draft update locks or compare-and-set updates the active draft with `WHERE revision = :expected_revision`, replaces or diffs its normalized editable children within the same transaction, and increments the revision exactly once. Restoration marks the prior draft inactive and creates a new active draft, serialized by locking the report row; the partial unique index is the final concurrency guard.

Current resource pointers on `reports` are nullable composite foreign keys used to distinguish retained history from the current source/dataset/analysis. Their constraints are deferrable until transaction end so a service can create a current descendant and attach it atomically. The user-facing stage is not stored; the later domain service derives it from these pointers, the active draft, current job state, and latest version relationship.

Storing draft content as JSONB was rejected because it would weaken field-level ownership, ordering, reference, and protected-field constraints for mutable state. Keeping every historical draft revision was also rejected for this stage: optimistic concurrency needs the current revision, while immutable report versions preserve the reviewed historical state required by the MVP.

### 4. Separate private file metadata from immutable source records

`file_assets` stores `id`, owner/report, `purpose` (`source_csv` or `generated_pdf`), environment scope, bucket, object key, safe filename, content type, byte size, SHA-256 checksum, creation time, and optional version/export binding fields. It stores no endpoint, access key, secret, public URL, signed URL, or authorization flag. A unique constraint on `(environment, bucket, object_key)` prevents two metadata rows from claiming one object; additional composite unique keys allow source/export relationships to verify owner, report, and purpose.

`report_sources` stores immutable source metadata plus one of two representations:

- `text`: exact `inline_text`, UTF-8 encoding metadata, and no file asset;
- `csv`: one `source_csv` asset, declared/detected media metadata, separately labeled untrusted original filename and normalized display filename, and no inline text.

A named check constraint enforces this exclusive shape. Source checksum, content, representation, filenames, asset binding, owner, and report cannot be updated. The initial migration adds a shared `reject_immutable_row()` trigger function and attaches update/delete triggers to committed sources and file assets. Physical object cleanup and retention require a later explicit design; this change records metadata only and never attempts an object-store operation inside a database transaction.

Combining object keys directly into source/export rows was rejected because it duplicates storage metadata and makes purpose-safe bindings harder to enforce. Persisting signed URLs was rejected because they expire and would turn a database row into a credential leak. Database large objects were rejected because S3-compatible storage is the approved binary boundary.

### 5. Represent import editing as an append-only revision stream

One CSV source has at most one `import_configurations` logical record containing `current_revision`, timestamps, and aggregate keys. `import_configuration_revisions` uses `(configuration_id, revision)` as a unique logical key and retains the normalization-policy version plus explicit date-format setting. `import_column_mappings` is keyed by configuration and revision with both unique `(configuration, revision, source_column_ordinal)` and `(configuration, revision, canonical_field)` constraints. Canonical-field checks admit exactly the seven approved names.

Updating a configuration executes one transaction:

1. Compare-and-set `current_revision` from the submitted expected value to the next value.
2. Insert the revision and all mappings.
3. Commit only after required dimensions and at least one measure are present; aggregate cardinality checks that span rows are performed by the repository before commit, while unique constraints protect races and duplicates.

`import_validations` references one exact configuration revision and stores error/warning counts, an optional canonical-preview identity, and validation time. `import_validation_issues` stores stable code, severity, safe message, canonical field, source ordinal, primary source-record index, optional related record index, and deterministic ordinal. It deliberately stores no rejected source value.

`confirmed_imports` uniquely references an error-free validation and retains canonical-data identity, row count, period, confirmer, and confirmation time. `confirmed_import_warning_acknowledgements` links the confirmation to every warning issue so the acknowledged set can be compared exactly. `source_review_confirmations` provides the parallel exact-revision acknowledgement for pasted text and cannot create a canonical dataset.

Mutating one configuration row in place was rejected because validations and confirmations must remain reproducible after a later edit. Encoding mappings and issues as JSONB was rejected because one-to-one ordinals, canonical fields, locations, and acknowledgement membership need relational constraints and deterministic queries.

### 6. Store canonical rows and deterministic metrics as immutable relational results

The confirmed-data group is:

| Table | Important fields and constraints |
|---|---|
| `canonical_datasets` | owner/report/source/confirmation, unique canonical-data identity, period, positive row count, normalization-policy version, created time; one dataset per confirmation |
| `dataset_currencies` | dataset plus uppercase three-letter currency; unique per dataset |
| `canonical_rows` | dataset, stable row UUID, one-based source-record index, date, trimmed campaign name, currency, nullable non-negative impressions/clicks/leads and exact non-negative spend; unique dataset/record index |
| `metric_result_sets` | owner/report/dataset, calculation version/time, unique deterministic result-set identity |
| `metric_results` | result set, metric name, availability, scope, period, optional currency, exact value/unit or unavailable reason/supporting field; named checks enforce the discriminated variants |
| `metric_result_inputs` | metric result, stable input name, exact numeric total, deterministic ordinal; unique metric/input name |
| `metric_result_currencies` | represented currencies for provenance; unique metric/currency |

Repository preconditions verify dataset row count, period inclusion, currency membership, and at least one mapped measure before the dataset is attached as current. Database checks independently reject negative measures, malformed currencies, blank campaign names, non-finite numerics, duplicate source-record indexes, and invalid available/unavailable combinations. Metric reasons admit only `missing_input`, `zero_denominator`, `invalid_input`, `incompatible_currency`, and `incomparable_period`.

Datasets, rows, result sets, results, inputs, and currency provenance receive immutable update/delete triggers after insertion. A new source or calculation produces a new identity and updates current pointers; it never rewrites a prior result. The processing layer remains solely responsible for parsing, ISO 4217 membership, aggregate arithmetic, metric definitions, and period comparability.

Storing canonical rows or metric inputs in JSONB was rejected because exact numeric types, non-negative constraints, row provenance, pagination, and queryable currency isolation are core database contracts. Adding database formulas or generated KPI columns was rejected because deterministic calculation belongs to the processing service and is versioned independently.

### 7. Use logical operations plus append-only attempts for analysis and PDF work

`analysis_jobs` contains owner/report, semantic-input identity, dataset, metric result set, objectives revision, captured draft/revision, current state, attempt count, current result pointer, timestamps, and sanitized failure summary. A unique key on `(report_id, semantic_input_identity)` ensures one logical analysis operation for identical input. `analysis_job_attempts` has unique `(job_id, attempt_ordinal)`, state and queue/start/finish times, plus sanitized code/message/retryability. State-specific checks require timestamps and failure fields only in compatible states.

`analysis_results` is one-to-one with a succeeded job and retains model identifier, prompt version, bounded request provenance, numeric-source identity, and creation time. `analysis_result_items` normalizes the five output sections, stable ordering, classification (`observation`, `hypothesis`, or `user_claim` where valid), and text. Reference joins link result items to metric results or claims without copying arithmetic. Result rows are immutable.

`pdf_exports` contains owner/report/version, snapshot identity, template version, logical input identity, current state, attempt count, optional generated asset, timestamps, and sanitized failure summary. A unique semantic binding on `(version_id, snapshot_identity, template_version)` makes retry reuse the same logical export. `pdf_export_attempts` mirrors analysis attempt ordinal/state rules. A composite foreign key binds a succeeded export only to a matching `generated_pdf` asset for the same owner/report/export; state checks require exactly one asset on success and none otherwise.

Repositories expose named compare-and-set operations rather than a generic state setter: claim queued attempt, finish running attempt successfully, finish with sanitized failure, and enqueue one retry from a failed logical operation. Each operation includes the observed state and attempt count in its predicate, locks only the logical operation being changed, and creates the next ordinal in the same transaction. Celery redelivery therefore observes the already-created attempt instead of allocating another one.

Database triggers for every legal state edge were rejected because stale-input checks require current aggregate identities and belong to domain services. Plain unrestricted ORM mutation was also rejected because it cannot prove compare-and-set behavior. Named repositories plus state/field checks and uniqueness constraints provide a narrow, integration-testable boundary.

### 8. Persist idempotency with the domain mutation

`idempotency_records` contains principal, operation name, scope kind, scope UUID (the principal itself for report creation), SHA-256 key digest, canonical command fingerprint, logical result type/UUID, original success status needed for replay, and timestamps. It never stores the raw request body or source content. Unique `(principal_id, operation, scope_kind, scope_id, key_digest)` serializes competing requests.

The repository first attempts to insert or lock the scoped record inside the domain transaction. A matching fingerprint returns the recorded result; a different fingerprint raises a domain-neutral conflict; a new key proceeds and records the result only if the mutation commits. PostgreSQL transaction rollback handles partial failures. The record has no short expiration in the MVP and uses `RESTRICT` to remain as long as its logical result.

Using only resource-table uniqueness was rejected because it cannot distinguish an equivalent replay from different input using the same client key. Storing raw idempotency keys or bodies was rejected because digests and canonical fingerprints are sufficient and reduce sensitive-data retention.

### 9. Allocate immutable report versions under the report lock

`report_versions` contains owner/report, positive `version_number`, source draft and exact revision, template version, `snapshot_schema_version`, JSONB snapshot, deterministic snapshot identity, and creation time. Unique `(report_id, version_number)`, `(report_id, snapshot_identity)`, and the scoped idempotency record prevent duplicate versions. The version-creation transaction:

1. Resolves idempotency and locks the report row.
2. Verifies the requested draft is active and its revision matches.
3. Selects `COALESCE(MAX(version_number), 0) + 1` while holding that report lock.
4. Builds and validates the snapshot through a versioned Pydantic boundary in the domain layer.
5. Inserts the version, records the idempotent result, and commits.

Because allocation and insertion occur in one transaction under a per-report lock, a rollback consumes no sequence value and concurrent reports do not block each other. A shared PostgreSQL sequence was rejected because rollback gaps violate the approved per-report behavior. A mutable `next_version` counter was rejected because it duplicates derived state and is easier to advance accidentally.

The snapshot is the single intentional denormalization. It contains public-safe source references and checksums, confirmed mapping/normalization/validation provenance, canonical identity, exact metrics and availability, validated AI provenance/output, edited narrative, limitations, claims, report metadata/period, and template version. It excludes unrestricted source contents, object keys, signed URLs, and credentials. A generic immutable-row trigger rejects `UPDATE` and `DELETE` on `report_versions`; foreign keys from exports use `RESTRICT`.

### 10. Use explicit current pointers and indexes for lifecycle and API query shapes

The domain service updates nullable current pointers on `reports` only in the transaction that validates and attaches the corresponding source, dataset, metric set, or analysis result. Composite deferrable foreign keys require pointer targets to share owner/report. Clearing downstream pointers is how a later service records invalidation; retained rows remain available for audit and versions.

Add explicit B-tree indexes matching the approved keyset order:

- reports: `(owner_id, created_at DESC, id DESC)`;
- analysis jobs: `(owner_id, report_id, created_at DESC, id DESC)`;
- report versions: `(owner_id, report_id, version_number DESC, id DESC)`;
- PDF exports: `(owner_id, report_id, version_id, created_at DESC, id DESC)`;
- canonical rows: `(owner_id, report_id, dataset_id, source_record_index ASC, id ASC)`.

Additional indexes cover every foreign key not already led by a unique constraint, current pointers, source checksum, current configuration revision, canonical-data identity, metric result-set identity, semantic-input identity, idempotency scope, and `(logical_operation_id, attempt_ordinal)`. Catalog tests assert exact names and leading columns. Raw content, narratives, source cell values, credentials, and object keys are not generally indexed.

Computing current state exclusively by `created_at` was rejected because retained stale outcomes and retries make recency different from currentness. Storing a user-facing stage was rejected because it can drift from current pointers, job state, and version facts.

### 11. Protect immutable operational results with database triggers

The initial migration creates one schema-local trigger function that raises a stable SQLSTATE and table-safe message for forbidden update/delete operations. It attaches to sources, file assets, configuration revisions and mappings once referenced, confirmations, canonical datasets/rows, metric results/provenance, analysis results/items, and report versions. Mutable logical roots—reports, active drafts, import configuration heads, jobs, attempts while transitioning, exports, and idempotency records while being finalized—remain updateable only through narrow repositories and checks.

Integration tests attempt both ORM and direct SQL mutations so immutability does not depend on Python conventions. The trigger message names only the table/operation and never includes row contents, object keys, or customer data.

Making every table append-only was rejected because current pointers, revisions, and job states are deliberately mutable operational state. Relying only on ORM events was rejected because direct SQL, migrations, and worker code could bypass them.

### 12. Verify against a disposable PostgreSQL database with fail-closed guards

Add `TEST_DATABASE_URL` for integration tests and `MIGRATION_DATABASE_URL` for Alembic. Test helpers parse URLs without logging them and require `APP_ENV=test`, a database name ending in `_test`, a loopback or explicitly allowlisted CI host, and inequality from the ordinary `DATABASE_URL`. Destructive fixtures operate only after all guards pass. The test database is migrated through Alembic; tests never call `create_all`.

The verification layers are:

| Layer | Evidence |
|---|---|
| metadata unit tests | naming convention, server defaults, nullability, no forbidden JSONB outside version snapshots, and expected table/column declarations |
| PostgreSQL integration tests | every check/unique/composite foreign key, scoped repositories, compare-and-set revision/state operations, concurrency, immutable triggers, and query ordering |
| migration tests | empty upgrade, one head, second-upgrade no-op, schema/metadata parity, guarded empty downgrade, re-upgrade, and refusal to downgrade a populated schema |
| catalog tests | named UUID/FK/check/unique constraints, required indexes and leading columns, timestamptz columns, immutable triggers, and absence of secret/content indexes |
| existing backend checks | configuration, health, lint, formatting, mypy, and application import remain green |

The initial revision's downgrade checks that every product table is empty before dropping objects in reverse dependency order. It is therefore lossless only for an empty disposable schema; it aborts on a populated database. Production rollback after data exists is a reviewed forward migration, not a destructive downgrade.

## Risks / Trade-offs

- **[Risk] The table graph is broad for an initial migration** → Keep models grouped by aggregate modules, use one reviewed naming convention, generate the candidate revision once, then manually inspect and test every object before accepting it.
- **[Risk] Composite ownership keys add columns and index width** → Accept the storage cost because they make cross-aggregate links impossible and align authorization predicates with query indexes.
- **[Risk] Immutable triggers can complicate future retention or privacy requirements** → Treat deletion/retention as a later explicit migration and privileged maintenance workflow; do not add an unreviewed bypass now.
- **[Risk] Deferrable current-pointer relationships can hide errors until commit** → Keep transactions small, translate integrity failures to safe domain errors later, and integration-test every attach/invalidate path.
- **[Risk] Unconstrained `numeric` values can be very large** → Retain exactness at persistence; enforce request/source bounds in the later API and processing changes once product limits are approved.
- **[Risk] A complete version snapshot can grow substantially** → Keep source bodies and object keys out, store only reproducibility fields, version the snapshot schema, and measure representative row size before the version/PDF stage.
- **[Trade-off] Database checks cannot validate the full ISO 4217 list or KPI arithmetic** → Enforce structural currency/numeric constraints here and leave versioned semantic validation/calculation to deterministic processing code.
- **[Trade-off] No RLS in this stage** → Composite database constraints and mandatory scoped repositories provide the reviewed boundary; any later RLS design must include safe connection-local principal propagation and independent tests.

## Migration Plan

1. Add pinned Alembic/test dependencies, migration/runtime/test URL examples, safe database commands, typed metadata, session factory, and fail-closed PostgreSQL test fixtures without creating product tables at application startup.
2. Implement model groups and narrow repositories in dependency order: principals/reports/drafts, assets/sources/imports, datasets/metrics, analysis jobs/results/idempotency, then versions/exports.
3. Add metadata and repository unit tests, then generate the single initial Alembic revision. Review and edit the revision so constraint/index names, deferrable ownership keys, triggers, and reverse dependency order are explicit and deterministic.
4. Apply the revision to a fresh isolated PostgreSQL database, run catalog/schema parity and integration suites, run a second upgrade, perform the empty guarded downgrade and re-upgrade, and prove downgrade refuses when product rows exist.
5. Run the complete backend foundation suite and documentation/environment consistency checks. Record the exact passing commands in the implementation handoff.

There is no deployed reporting schema or production data to backfill. Before data exists, rollback is the guarded empty-schema downgrade. After any reporting data exists, rollback is a new reviewed forward migration; operators MUST NOT force the initial downgrade or manually mutate shared schema objects.
