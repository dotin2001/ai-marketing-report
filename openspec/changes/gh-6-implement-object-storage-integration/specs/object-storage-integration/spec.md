## Purpose

Define private, integrity-checked storage and owner-authorized retrieval for original CSV inputs and generated PDF artifacts while PostgreSQL remains the authoritative metadata and ownership boundary.

## ADDED Requirements

### Requirement: Supported artifacts are stored immutably and privately
The system SHALL store every accepted original CSV and completed generated PDF as a private object through the backend storage boundary. An original CSV object SHALL preserve the accepted bytes unchanged; a generated PDF object SHALL preserve the exact bytes produced for its immutable report version. Objects SHALL use an environment-, owner-, report-, purpose-, and logical-resource-scoped identity that is not derived solely from an untrusted filename. The system MUST NOT configure public-read access, expose an object-listing operation to product callers, or overwrite an object with different bytes under the same logical identity.

#### Scenario: Original CSV is stored unchanged
- **WHEN** an authorized source workflow accepts a CSV for a report
- **THEN** the backend stores the exact accepted byte sequence as a private `source_csv` object under that environment, owner, report, and source identity
- **AND** the untrusted original filename neither controls the storage scope nor becomes object-storage instructions

#### Scenario: Generated PDF is stored for one immutable export
- **WHEN** a PDF export attempt produces a valid non-empty PDF for an immutable report version
- **THEN** the backend stores those bytes as a private `generated_pdf` object bound to that report, version, and logical export
- **AND** a later draft or version cannot replace the stored object under that export identity

#### Scenario: Conflicting retry is rejected
- **WHEN** a retry addresses an existing logical object identity with different content, size, checksum, content type, or ownership metadata
- **THEN** the system rejects the collision as a sanitized non-success outcome
- **AND** it neither overwrites nor adopts the existing object

### Requirement: PostgreSQL records authoritative object metadata and bindings
After an object write is verified, the system SHALL persist its environment, bucket, internal object key, safe filename, content type, byte size, SHA-256 checksum, purpose, owner, and report identity in PostgreSQL. A CSV asset SHALL bind to exactly one immutable CSV report source, and a generated PDF asset SHALL bind to exactly one PDF export and its immutable report version. Public resource representations MUST NOT contain the bucket or internal object key. A storage write that does not complete and verify MUST NOT create an observable asset or success binding in PostgreSQL.

#### Scenario: CSV metadata is persisted with its source
- **WHEN** a CSV object is written and verified successfully
- **THEN** one PostgreSQL asset record contains its exact storage and integrity metadata and is attached to the matching owner-scoped CSV source
- **AND** the source representation exposes only its approved safe metadata, never the bucket or object key

#### Scenario: PDF metadata is persisted with a succeeded export
- **WHEN** a valid PDF object is written and verified for a running export attempt
- **THEN** one generated-PDF asset record is bound to the same owner, report, version, and export before that export becomes `succeeded`
- **AND** the succeeded representation exposes safe file metadata and download availability without internal storage identity

#### Scenario: Upload fails before verification
- **WHEN** object storage rejects, times out, truncates, or otherwise fails an upload before its metadata and integrity are verified
- **THEN** no source or export is reported as successfully bound to that object
- **AND** the caller receives only the stable failure classification appropriate to its workflow

### Requirement: Storage and database retries converge on one logical asset
Storage operations SHALL be safe to retry using a stable logical source or export identity. If the expected private object already exists, the system SHALL compare authoritative ownership, purpose, content type, byte size, and SHA-256 metadata before reusing it; an exact match SHALL converge on the existing logical asset and a mismatch SHALL fail closed. If a database transaction fails after a successful object write, the system SHALL make the object recoverable by the same logical retry and MAY perform a best-effort delete only for the exact newly written key. Retrying PDF storage MUST NOT create a new report version or rebind the export to a different version.

#### Scenario: Exact CSV retry converges
- **WHEN** the same authorized CSV command is retried after its object write completed but its database outcome is uncertain
- **THEN** the system verifies the existing object's ownership, purpose, type, size, and checksum and creates or returns one matching source/asset result
- **AND** no duplicate logical object or source is created

#### Scenario: Exact PDF retry targets the same version
- **WHEN** a generated-PDF storage attempt is retried with the same export, immutable version, input identity, and bytes
- **THEN** the system reuses or completes the one matching asset binding for that export
- **AND** it creates no report version and does not change the export's version or template binding

#### Scenario: Uncertain object cannot be validated
- **WHEN** a retry finds an object at the expected key but cannot prove that its required metadata and checksum match the requested logical asset
- **THEN** the system fails closed with a sanitized storage or integrity failure
- **AND** it does not create a PostgreSQL binding or expose the existing object

### Requirement: Retrieval verifies ownership and integrity
Every object retrieval SHALL begin from an owner-scoped PostgreSQL lookup of the report and its bound source or PDF export; possession of an object key, asset identifier, or signed location MUST NOT grant authorization. Missing and cross-owner resources SHALL produce the same public `404 resource_not_found` outcome. Backend retrieval SHALL verify that the returned object's content length, content type, and SHA-256 identity match the persisted asset metadata before the bytes are accepted by internal processing or issued as a completed download. Integrity or provider failures SHALL not return partial trusted content.

#### Scenario: Owner retrieves an original CSV for processing
- **WHEN** an authenticated owner requests an internal preview or processing operation for the owner's CSV source
- **THEN** the system resolves the asset through the owner and report, retrieves the private object, and verifies its persisted metadata and checksum before use
- **AND** no unrestricted original-source download endpoint or object key is exposed

#### Scenario: Cross-owner retrieval is hidden
- **WHEN** a principal requests a source or PDF export belonging to another owner
- **THEN** the system returns the same `404 resource_not_found` response used for an unknown identifier
- **AND** it performs no object retrieval, mutation, or background work

#### Scenario: Retrieved content fails integrity verification
- **WHEN** storage returns content whose size, content type, or SHA-256 checksum differs from the bound asset metadata
- **THEN** the system rejects the content and returns or records a sanitized integrity/storage failure
- **AND** no partial CSV is processed and no partial PDF is delivered

### Requirement: Completed PDF downloads are authorized and streamed
The completed PDF download operation SHALL reauthorize the authenticated principal against the report owner and confirm that the selected export is `succeeded` with a bound generated-PDF asset. This implementation SHALL return an authorized `application/pdf` stream with safe content metadata and SHALL NOT issue a signed object-storage location. A queued, running, or failed export SHALL return `409 export_not_ready` without file bytes.

#### Scenario: Owner downloads a completed PDF
- **WHEN** the owner requests download for a succeeded export with a verified generated-PDF asset
- **THEN** the system returns the exact PDF through an authorized backend stream
- **AND** the response uses safe content type, length, and attachment filename metadata

#### Scenario: Incomplete export cannot be downloaded
- **WHEN** the owner requests download for an export in `queued`, `running`, or `failed`
- **THEN** the system returns `409 export_not_ready` with the persisted public export state
- **AND** it returns no object key or file bytes

### Requirement: Storage failures and telemetry are redaction safe
Storage configuration, access credentials, internal bucket and object identities, untrusted filenames, customer file content, raw provider responses, and stack traces MUST NOT appear in public errors or ordinary logs. Storage failures SHALL map to stable safe categories, retain retryability where the calling workflow supports it, and preserve enough non-sensitive correlation data for diagnosis. Operation timeouts SHALL be bounded and validated; non-local object-storage transport SHALL remain encrypted.

#### Scenario: Provider rejects an operation
- **WHEN** the storage provider returns an authentication, authorization, timeout, unavailable, or malformed-response error
- **THEN** the backend emits only a stable sanitized failure and non-sensitive correlation metadata
- **AND** neither the client response nor ordinary logs contain credentials, bucket names, object keys, raw provider bodies, or customer bytes

#### Scenario: Configuration is unsafe
- **WHEN** a non-local environment is configured with insecure object-storage transport or an invalid operation-timeout bound
- **THEN** application configuration fails before serving storage operations
- **AND** the validation error identifies the setting without echoing its secret value

### Requirement: Object-storage behavior is independently verifiable
The implementation SHALL provide deterministic adapter-level verification without external accounts, isolated PostgreSQL integration verification for asset ownership and aggregate bindings, and an opt-in live S3-compatible suite using only test-scoped objects. Live cleanup MUST target only the exact test prefix or keys created by the suite and MUST NOT delete unrelated bucket content. Verification SHALL prove byte-for-byte retrieval, metadata and SHA-256 integrity, retry convergence, owner-safe denial, private direct access, authorized streamed download behavior, and sanitized failures.

#### Scenario: Deterministic checks run without live storage
- **WHEN** the normal backend verification suite runs without an object-storage service
- **THEN** deterministic fakes cover successful and failed upload, retrieval, head, and delete compensation behavior
- **AND** the tests assert stable error mapping and sensitive-data redaction

#### Scenario: Live compatibility check is enabled
- **WHEN** the explicitly configured live storage integration suite runs against the local private S3-compatible service
- **THEN** it verifies CSV and PDF round trips, persisted metadata compatibility, direct anonymous denial, and owner-authorized streamed download behavior
- **AND** cleanup addresses only suite-created test keys under the isolated test prefix
