## Purpose

Preserve every confirmed dataset revision and saved report version as an exact, owner-scoped historical record that can be reopened or exported after current report inputs change.

## ADDED Requirements

### Requirement: Confirmed dataset revisions are append-only
The system SHALL commit a canonical dataset only from the exact error-free, owner-confirmed source, import configuration, normalization policy, and report period. The dataset identity and its canonical rows SHALL remain immutable. A behavior-affecting input change MUST invalidate current confirmation; a subsequent confirmation SHALL create or resolve a separate immutable dataset identity without replacing historical rows. A confirmed text source SHALL remain distinguishable from a structured dataset and MUST NOT fabricate canonical rows.

#### Scenario: Exact CSV confirmation is committed
- **WHEN** an owner commits normalized rows for a current error-free confirmation
- **THEN** one dataset retains the source, configuration revision, policy, period, currency, row, and canonical identity provenance
- **AND** the rows retain stable source-record indexes

#### Scenario: Dataset inputs change after confirmation
- **WHEN** the source, mapping, normalization configuration or policy, or report period changes after a dataset has been confirmed
- **THEN** the former dataset and rows remain readable as historical data
- **AND** analysis or version creation for the new current input requires its own explicit confirmation

#### Scenario: Direct historical dataset mutation is attempted
- **WHEN** a caller or persistence operation tries to update, delete, or rebind a committed dataset or canonical row
- **THEN** the operation is rejected without changing the historical dataset or any version that references it

### Requirement: A report version binds one coherent saved state
The system SHALL create a saved report version only from one owner-authorized report and the exact expected active draft revision. For a structured source, it SHALL bind the current confirmed dataset revision, compatible metric result set and validated analysis result when present, and their source, import, calculation, and request provenance. It SHALL preserve the exact edited objectives, narrative, limitations, labeled claims, and deterministic chart configuration alongside the report metadata and template version. Chart configuration SHALL reference only included computed metric identities and safe presentation parameters; it MUST NOT contain private source content, object keys, credentials, or invented numeric values. For a text-only source, the version SHALL explicitly record the absence of a canonical dataset and metrics rather than fabricate them.

#### Scenario: Current structured report is saved
- **WHEN** the owner saves the current draft revision whose source, dataset, metric, analysis, and chart references are mutually compatible
- **THEN** one sequential version contains or references the exact immutable data and analysis results and a complete render snapshot of the edited content and charts
- **AND** later draft or dataset changes cannot alter that snapshot

#### Scenario: Version contains a mismatched reference
- **WHEN** a save supplies a dataset, metric, analysis, or chart reference from another report, owner, source, confirmation, calculation, or stale semantic input
- **THEN** the save is rejected atomically and no version number is consumed

#### Scenario: Text-only report is saved
- **WHEN** an explicitly confirmed text source is saved without structured analysis
- **THEN** its version retains the source checksum, labeled claims, content, charts if valid, and explicit absence of a canonical dataset and metrics

### Requirement: Version creation and history are retry-safe and immutable
Version creation SHALL use the expected draft revision and a scoped idempotency key in one transaction. Replaying the same key and command SHALL return the original version; reusing the key for a different command SHALL fail. Concurrent saves MUST NOT produce duplicate version numbers, conflicting snapshots, or sequence gaps. Committed versions SHALL reject direct update, delete, renumbering, and rebinding. Owner-scoped history SHALL return stable ordered versions, and restoration SHALL copy selected saved content into a new revisioned active draft without modifying any version or dataset.

#### Scenario: Create request is replayed
- **WHEN** the same owner repeats a version-creation command with the same idempotency key and input fingerprint
- **THEN** the original version is returned and no second version is created

#### Scenario: Draft revision is stale
- **WHEN** a save or restore supplies an expected active draft revision that is no longer current
- **THEN** the operation reports a revision conflict and leaves the active draft and history unchanged

#### Scenario: History is restored and exported
- **WHEN** an owner restores an older version and later exports that version
- **THEN** the active draft is a new mutable copy while the old snapshot, its dataset binding, and the export input identity remain unchanged

#### Scenario: Foreign version or dataset is requested
- **WHEN** a principal requests or attempts to mutate another owner's dataset or version identifier
- **THEN** no resource or ownership detail is disclosed and no data changes
