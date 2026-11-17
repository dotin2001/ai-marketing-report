## Purpose

Defines the repository-wide minimum local verification policy that permits a linked GitHub Project issue to reach Done through `ai:local --sync-task` while retaining conflict-safe synchronization.

## ADDED Requirements

### Requirement: Shared basic checks govern Done
Every `--sync-task` invocation SHALL derive its required checks from the shared repository verification policy and the selected change using the workflow's existing suite-applicability rules. The required set SHALL contain strict validation of that OpenSpec change, `git diff --check`, and the repository's `frontend:test` and `backend:test` scripts when their respective suites apply. A required check SHALL pass in the current worktree before `Done`; missing, skipped, blocked, timed-out, or failed required checks SHALL prevent the status update and be named in the diagnostic and evidence. An inapplicable suite SHALL be reported as inapplicable and SHALL NOT be a required failure.

#### Scenario: Applicable basic checks pass
- **WHEN** an eligible linked change has complete required tasks and all applicable basic checks pass
- **THEN** `--sync-task` may proceed to its existing final identity, fingerprint, and status guards

#### Scenario: Required check fails or cannot run
- **WHEN** any applicable basic check fails, is missing, or cannot run
- **THEN** no Project status write occurs and the command identifies the blocking command and result

#### Scenario: Only one application suite applies
- **WHEN** the existing suite-selection rules select the backend suite but not the frontend suite, or the reverse
- **THEN** only the selected suite's unit-test script is required, alongside strict OpenSpec validation and `git diff --check`

### Requirement: Negated backend markers remain service-free
The workflow SHALL interpret pytest marker expressions according to their positive and negated meaning when deciding service prerequisites. A backend unit-test command excluding `postgres` and `storage_live` SHALL run with the existing isolated backend test environment without requiring PostgreSQL, live object storage, `TEST_DATABASE_URL`, or `MIGRATION_DATABASE_URL`. Positively selected live-service checks SHALL retain their existing safe prerequisite handling when run separately.

#### Scenario: Service-free backend unit tests
- **WHEN** `backend:test` uses `-m "not postgres and not storage_live"` and no live-service configuration is present
- **THEN** the backend unit test runs without PostgreSQL or object-storage preflight and its result counts toward the basic gate

#### Scenario: Live marker is selected
- **WHEN** a separately requested check positively selects PostgreSQL or live storage
- **THEN** its existing service safety checks still apply

### Requirement: Expanded verification is optional for synchronization
Live PostgreSQL integration tests, migration smoke tests, live object-storage tests, and AI semantic review SHALL be optional for `--sync-task` under this policy. Their available results SHALL be reported and retained as supplementary evidence, including failures and unavailable or skipped states, but SHALL NOT block `Done` when the required basic checks pass. The repository SHALL continue to provide separate ways to run these checks. A missing or failed optional semantic review SHALL NOT invalidate the basic-check completion result.

#### Scenario: Optional checks are unavailable
- **WHEN** required basic checks pass and one or more optional checks are skipped or unavailable
- **THEN** the optional states are reported and synchronization continues to the final guards

#### Scenario: Optional check fails
- **WHEN** required basic checks pass and an optional live or semantic check fails
- **THEN** its failure is reported as optional evidence and does not prevent the guarded `Done` transition

### Requirement: Existing synchronization safety remains
The workflow SHALL preserve linked issue and Project lookup, required task and artifact checks, verification input fingerprints, retry invalidation, final live identity and status reads, exact `Todo` or `In Progress` to `Done` transitions, idempotent `Done`, and conflicts for every other status. It SHALL update only the linked Project item, confirm its resulting status, and leave the issue open. The manual `--apply` path SHALL be unaffected. Passing evidence SHALL be reusable only when its recorded policy, required-check set, identities, and fingerprints still match.

#### Scenario: Basic checks pass for In Progress
- **WHEN** the required basic checks and final guards pass for the linked item at exact `In Progress`
- **THEN** the workflow writes `Done` once for that item and confirms the live result

#### Scenario: Final guard fails
- **WHEN** a linked identity, verified fingerprint, or allowed status changes before the write
- **THEN** the workflow leaves Project status unchanged and reports the conflict

#### Scenario: Retry follows a policy change
- **WHEN** a prior passing record was created with a different required-check policy
- **THEN** `--sync-task` reruns verification before any Project write
