## Purpose

Define the durable PostgreSQL contract that preserves owner isolation, lifecycle provenance, deterministic results, retry safety, and immutable report history across every reporting resource.

## ADDED Requirements

### Requirement: Migrations are the sole schema authority
The system SHALL manage every reporting table, type, constraint, index, trigger, and schema revision through an ordered migration history. Reporting records SHALL use database-generated UUID primary keys, timezone-aware UTC instants, explicit foreign keys, and named constraints. Application startup and ordinary tests MUST NOT create, drop, or alter reporting tables implicitly.

#### Scenario: Empty database is upgraded
- **WHEN** the migration history is applied to an empty supported PostgreSQL database
- **THEN** the database reaches exactly one current head containing every approved reporting object
- **AND** the resulting schema matches the application's declared persistence metadata

#### Scenario: Current database is upgraded again
- **WHEN** the current migration head is applied a second time
- **THEN** no schema or application data changes
- **AND** the command completes without creating another revision or head

#### Scenario: Application starts against an unmigrated database
- **WHEN** the application starts with a database that has not reached the required migration head
- **THEN** it does not create or modify product tables
- **AND** database readiness or the first database-dependent operation fails safely without exposing credentials or raw database errors

### Requirement: Ownership is enforced throughout the report aggregate
The persistence layer SHALL represent an authenticated principal independently of any concrete authentication provider and SHALL assign every report to exactly one principal. Every report child and descendant SHALL retain an owner-and-report-consistent relational path to its report. Database relationships MUST reject a child whose owner, report, parent resource, or immutable ancestor belongs to a different aggregate.

#### Scenario: Owner creates a report aggregate
- **WHEN** a report is persisted for a known authenticated principal
- **THEN** the report and its initial draft share that principal and report identity
- **AND** no source, job, version, export, or file asset is created implicitly

#### Scenario: Cross-owner child relationship is attempted
- **WHEN** a transaction attempts to associate a source, dataset, job, draft, version, export, or file asset with a report or parent owned by another principal
- **THEN** a foreign-key or equivalent database constraint rejects the transaction
- **AND** neither aggregate is partially changed

#### Scenario: Repository lookup receives a foreign identifier
- **WHEN** a principal-scoped repository is asked to read or mutate a child identifier belonging to another principal
- **THEN** no row is returned or changed
- **AND** the lookup does not reveal which ownership predicate failed

### Requirement: Reports and drafts preserve valid mutable state
The system SHALL persist each report's non-empty name, inclusive reporting period, creation and update instants, and one active revisioned draft. The period end MUST NOT precede its start. Draft objectives, narrative sections, findings, anomalies, recommendations, data gaps, limitations, and labeled claims SHALL be normalized owner/report-scoped records with stable ordering and identities. Draft mutations SHALL compare the expected positive revision and increment it atomically; deterministic metric values, ownership, jobs, and version fields MUST NOT be mutable through the draft boundary.

#### Scenario: Valid report and initial draft are created
- **WHEN** a report with a valid period and at least one objective is inserted transactionally
- **THEN** one report and one active draft at revision `1` are committed for the same owner
- **AND** all objective ordering and timestamps are retained

#### Scenario: Invalid report period is inserted
- **WHEN** a report period ends before it starts
- **THEN** a database constraint rejects the report
- **AND** no initial draft or objective remains

#### Scenario: Current draft revision is updated
- **WHEN** a draft update supplies the stored revision and valid editable content
- **THEN** the edit and its normalized child records commit atomically
- **AND** the draft revision increases by exactly one without creating a report version

#### Scenario: Stale draft revision is updated
- **WHEN** a draft update supplies a revision that is no longer current
- **THEN** zero draft rows and child records are changed
- **AND** the stored revision and content remain intact

### Requirement: Original sources and file assets remain immutable and private
The system SHALL persist each source as exactly one untrusted source type: unchanged pasted text or an immutable CSV file asset. Source provenance SHALL include byte size, SHA-256 checksum, media type or encoding, creation instant, and safe filename metadata where applicable. File assets SHALL persist environment/owner/report-scoped bucket and object keys plus content metadata and an asset purpose, but MUST NOT persist public URLs, signed URLs, credentials, or treat an object key as authorization. Committed sources and file assets MUST reject content, key, checksum, ownership, or report reassignment.

#### Scenario: Pasted source is persisted
- **WHEN** unchanged pasted content is stored for a report
- **THEN** the source retains the exact content, checksum, byte size, encoding, owner, and report provenance
- **AND** it has no CSV object binding

#### Scenario: CSV source is persisted
- **WHEN** a CSV source is stored after the object has been accepted by the storage abstraction
- **THEN** the source binds to exactly one private source-file asset with matching owner and report
- **AND** the untrusted original filename remains distinguishable from the normalized display filename

#### Scenario: Source representation is ambiguous
- **WHEN** a source has both pasted content and a file-asset binding or has neither representation
- **THEN** the database rejects it

#### Scenario: Committed asset is modified
- **WHEN** a transaction attempts to change or delete a source or bound file asset that is referenced by retained report history
- **THEN** the database rejects the mutation
- **AND** the original source and historical version remain reproducible

### Requirement: Import revisions and confirmation are exact and reproducible
The system SHALL persist import configuration as an owner/report/source-scoped logical record with positive append-only revisions. Each revision SHALL retain its normalization-policy version and one-to-one source-column-ordinal to canonical-field mappings. Validation SHALL reference one exact source and configuration revision and persist ordered issues using stable code, severity, safe message, canonical field, zero-based source-column ordinal, and one-based source-record locations where applicable. Confirmation SHALL reference only an error-free validation for the exact revision and SHALL retain warning acknowledgement, confirming principal, period, row count, currencies, canonical-data identity, and confirmation time.

#### Scenario: Mapping revision is appended
- **WHEN** the current expected configuration revision is updated with a valid mapping
- **THEN** one new revision is appended and becomes current atomically
- **AND** every prior revision and validation remains unchanged

#### Scenario: Mapping cardinality is invalid
- **WHEN** one source ordinal maps to multiple canonical fields or one canonical field receives multiple source ordinals in the same revision
- **THEN** a uniqueness constraint rejects the mapping revision

#### Scenario: Stale configuration revision is replaced
- **WHEN** an import update supplies an expected revision that is no longer current
- **THEN** no revision or mapping row is inserted
- **AND** the current revision remains unchanged

#### Scenario: Validation with errors is confirmed
- **WHEN** a transaction attempts to confirm a validation that contains a blocking error or does not match the exact current source and configuration revision
- **THEN** confirmation and canonical dataset creation are rejected

#### Scenario: Warnings are confirmed
- **WHEN** an error-free validation's complete warning identity set is acknowledged
- **THEN** confirmation records the exact acknowledgement and provenance
- **AND** it becomes eligible to create one canonical dataset identity

### Requirement: Canonical datasets retain exact normalized rows
The system SHALL persist a confirmed canonical dataset as an immutable owner/report/source/import-confirmation record with a unique canonical-data identity, inclusive period, row count, normalization-policy version, and represented currencies. Canonical rows SHALL retain one-based source-record identity, date, non-empty campaign name, uppercase three-letter currency, and nullable mapped measures. Counts MUST be non-negative integers, spend MUST be a non-negative exact decimal, and at least one measure SHALL be present in the confirmed dataset contract. Unmapped values and pasted claims MUST NOT be stored as canonical row fields.

#### Scenario: Confirmed dataset is stored
- **WHEN** error-free normalized rows are committed for an exact confirmation
- **THEN** the dataset row count, currencies, period, canonical identity, and ordered row provenance agree with those rows
- **AND** each source-record index occurs at most once in that dataset

#### Scenario: Invalid canonical value is inserted
- **WHEN** a canonical row contains a negative count, negative spend, blank campaign name, malformed currency, or an out-of-period date
- **THEN** a database constraint rejects the row
- **AND** the dataset is not partially attached as current

#### Scenario: Dataset provenance is changed
- **WHEN** a committed dataset or canonical row is updated, deleted, or rebound to another source, confirmation, report, or owner
- **THEN** the database rejects the mutation while it is referenced by results or history

### Requirement: Metric persistence distinguishes values from unavailability
The system SHALL persist immutable metric result sets for one canonical dataset and calculation version. Each metric result SHALL retain its name, scope, period, canonical-data identity, calculation time, exact aggregate inputs, represented currencies, and applicable currency. An available metric SHALL contain an exact decimal value and unit and no unavailable reason. An unavailable metric SHALL contain exactly one approved reason and no numeric value or unit. A valid zero numerator with a positive denominator SHALL remain an available zero; `NaN`, infinity, binary floating-point substitutes, and cross-currency combined spend values MUST NOT be representable.

#### Scenario: Available metric is persisted
- **WHEN** a calculated KPI has all compatible inputs and a positive denominator
- **THEN** its exact aggregate inputs, value, unit, scope, currency metadata, calculation version, and dataset identity are retained
- **AND** no unavailable reason is stored

#### Scenario: Unavailable metric is persisted
- **WHEN** a KPI is unavailable because of missing input, zero denominator, invalid input, incompatible currency, or incomparable period
- **THEN** exactly that approved reason and its safe supporting field or scope metadata are retained
- **AND** no numeric value or substitute unit is stored

#### Scenario: Metric availability fields conflict
- **WHEN** a result attempts to combine an available value with an unavailable reason or omits fields required by its availability variant
- **THEN** a database constraint rejects the result

### Requirement: Analysis operations are durable, idempotent, and stale-safe
The system SHALL persist each logical analysis run as an owner/report-scoped operation bound to one semantic input identity, confirmed dataset, metric result set, objectives revision, and draft revision. Logical operations and their attempts SHALL use exactly `queued`, `running`, `succeeded`, and `failed`; attempt ordinals SHALL be positive and unique within a job. Transactional compare-and-set transitions MUST reject illegal or stale state changes. A succeeded job SHALL reference at most one immutable validated analysis result with model, prompt, request, numeric-source provenance, and normalized structured sections. Failures SHALL retain only approved sanitized codes, safe messages, retryability, and timestamps.

#### Scenario: Logical analysis run is replayed
- **WHEN** the same scoped idempotent command is repeated with the same semantic input
- **THEN** it resolves to the same logical job
- **AND** no duplicate job, result, or attempt is created

#### Scenario: Analysis attempt transitions legally
- **WHEN** a queued attempt is claimed, completed, and attached while its captured input is still current
- **THEN** state changes use compare-and-set semantics and retain queue, start, and finish times
- **AND** one validated result may attach to the succeeded logical job

#### Scenario: Illegal job transition is attempted
- **WHEN** a transition skips a required state, changes a terminal success, or uses an obsolete observed state
- **THEN** zero job rows are changed
- **AND** existing attempts and results remain intact

#### Scenario: Late analysis result is stale
- **WHEN** an attempt finishes after the report's semantic input has changed
- **THEN** its sanitized outcome may be retained for audit
- **AND** it cannot become the report's current analysis or overwrite newer draft content

### Requirement: Idempotency is enforced transactionally
The system SHALL persist a compact idempotency record in the same transaction as each protected mutation. The uniqueness scope SHALL include authenticated principal, operation, parent scope, and a non-reversible digest of the client key. The record SHALL retain the canonical semantic-command fingerprint and logical result identity for the lifetime of that result. Equivalent replay SHALL resolve to the original result, while reuse with a different fingerprint MUST fail without side effects.

#### Scenario: Equivalent command is replayed
- **WHEN** the same principal, operation, parent scope, key digest, and semantic fingerprint are submitted again
- **THEN** the original logical result identity is returned
- **AND** no additional report, source, confirmation, job, attempt, version, export, or sequence allocation occurs

#### Scenario: Key is reused for different input
- **WHEN** the same scoped key digest is submitted with a different semantic fingerprint
- **THEN** the transaction reports an idempotency conflict
- **AND** neither the original result nor any domain record is changed

#### Scenario: Protected mutation rolls back
- **WHEN** the domain mutation fails after an idempotency record would otherwise be created
- **THEN** both the domain work and its idempotency record roll back
- **AND** a corrected retry can be accepted normally

### Requirement: Report versions are sequential and database-immutable
The system SHALL create each report version atomically from one exact active-draft revision and assign a positive sequence number unique within that report without gaps caused by rolled-back transactions. Each version SHALL retain owner/report identity, source draft identity and revision, creation time, report template version, a versioned complete reproducibility snapshot, and a deterministic snapshot identity. The snapshot SHALL contain every approved source, confirmation, canonical-data, metric, analysis, edited narrative, limitation, claim, and provenance value needed to reproduce the report and PDF. Committed version rows and snapshots MUST be protected from update and deletion at the database boundary.

#### Scenario: Current draft is versioned
- **WHEN** a transaction locks the report aggregate and supplies the current draft revision
- **THEN** exactly one next sequential version and complete snapshot are committed
- **AND** later draft edits cannot change the version

#### Scenario: Version request is replayed
- **WHEN** an equivalent idempotent version command is repeated
- **THEN** the original version is returned
- **AND** no duplicate version or sequence gap is created

#### Scenario: Stale draft is versioned
- **WHEN** a version command supplies a draft revision that is no longer current
- **THEN** no version or sequence allocation is committed

#### Scenario: Historical version is mutated
- **WHEN** any operation attempts to update or delete a committed version or replace its snapshot
- **THEN** the database rejects the operation
- **AND** existing exports remain bound to the original snapshot identity

### Requirement: PDF exports remain bound to one immutable version
The system SHALL persist each PDF export as an owner/report/version-scoped logical operation bound to the version snapshot identity and template version. Export attempts SHALL follow the same four persisted states and positive unique ordinals as analysis attempts. A succeeded export SHALL reference exactly one immutable generated-PDF file asset with matching owner, report, checksum, content type, and byte size; a failed export SHALL reference no generated asset and SHALL retain only an approved sanitized failure. Retry MUST target the same version, snapshot identity, and template and MUST NOT create a report version.

#### Scenario: PDF export succeeds
- **WHEN** an export for an immutable version completes successfully
- **THEN** the export references one matching private PDF asset and reaches `succeeded`
- **AND** the asset contains no public or signed URL

#### Scenario: Failed export is retried
- **WHEN** a failed export is retried with the same immutable input and next attempt ordinal
- **THEN** one attempt is added to the same logical export
- **AND** no version, export identity, or template binding changes

#### Scenario: Export asset has the wrong aggregate or purpose
- **WHEN** a PDF export is bound to a source asset, another report's asset, or an asset with a mismatched version binding
- **THEN** a database relationship rejects the binding

### Requirement: Query indexes support deterministic owner-scoped access
The database SHALL provide indexes that begin with the owner/report predicates used for authorization and support deterministic keyset ordering for report lists, analysis jobs, report versions, PDF exports, and canonical rows. Constraint-supporting indexes SHALL cover current-revision lookup, canonical identities, semantic input identities, idempotency scopes, attempt ordinals, source checksums, and version/export bindings. Indexes MUST NOT include raw pasted content, narrative text, source cell values, credentials, or object keys solely for general search.

#### Scenario: Owner lists aggregate resources
- **WHEN** reports, jobs, versions, exports, or canonical rows are queried using their documented owner scope and keyset boundary
- **THEN** PostgreSQL can use an index whose leading columns enforce that scope and whose remaining columns implement the deterministic order

#### Scenario: Constraint and index catalog is inspected
- **WHEN** migration verification examines the PostgreSQL catalog
- **THEN** every required uniqueness rule and documented keyset order has a stable named constraint or index
- **AND** no broad text or secret-bearing index exists

### Requirement: Database verification uses isolated PostgreSQL
The implementation SHALL provide deterministic database tests against supported PostgreSQL rather than substituting an in-memory or different SQL dialect for constraint and migration behavior. Test configuration SHALL target an explicitly isolated test database and MUST fail closed if it resolves to the ordinary development database or a non-test environment. Verification SHALL cover migration upgrade, safe downgrade and re-upgrade, schema/metadata parity, constraints, ownership, compare-and-set revisions, legal state transitions, idempotency, immutable versions, and cleanup.

#### Scenario: Integration database is misconfigured
- **WHEN** database tests are pointed at the ordinary application database, a non-test environment, or an unapproved remote host
- **THEN** the suite stops before applying a migration or deleting data
- **AND** the error identifies the unsafe setting without printing credentials

#### Scenario: Migration round trip is verified
- **WHEN** an isolated empty database is upgraded, exercised, safely downgraded, and upgraded again
- **THEN** all expected schema objects and constraints are reproducible
- **AND** the final schema matches the declared persistence metadata with one migration head

#### Scenario: Database suites finish
- **WHEN** the documented unit, PostgreSQL integration, migration, lint, and type-check commands run
- **THEN** all database acceptance cases pass without contacting a production service, object store, Redis broker, or AI provider
