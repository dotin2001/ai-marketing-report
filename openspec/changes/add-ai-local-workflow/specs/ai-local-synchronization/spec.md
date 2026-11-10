## Purpose

Define evidence-based completion verification and conflict-safe synchronization so a GitHub Project item reaches Done only when its linked, approved OpenSpec work is demonstrably complete.

## ADDED Requirements

### Requirement: Synchronization resolves one unambiguous linked change
The workflow SHALL support `npm run ai:local -- --sync-task` and `npm run ai:local -- --sync-task --change <change-id>`. When no change identifier is supplied, it SHALL automatically choose a change only when exactly one eligible linked candidate exists; otherwise it SHALL list candidates and require interactive selection.

#### Scenario: Explicit change is eligible
- **WHEN** the user supplies an existing linked change identifier
- **THEN** verification proceeds only for that change and its recorded Project item

#### Scenario: One implicit candidate exists
- **WHEN** no change is supplied and exactly one valid linked candidate exists
- **THEN** the workflow selects that candidate and clearly reports it

#### Scenario: Candidate is ambiguous
- **WHEN** no change is supplied and zero or multiple eligible candidates exist
- **THEN** the workflow does not update GitHub and either reports no candidate or requires the user to select from the eligible list

### Requirement: Recorded and live identities are verified before synchronization
Before verification and again immediately before mutation, the workflow SHALL verify the recorded repository, branch, issue, Project, Project item, and OpenSpec change identities. It SHALL confirm that the live Project item is still linked to the expected issue in the target repository and SHALL refetch the current issue requirements and relevant comments.

#### Scenario: Identities remain consistent
- **WHEN** all recorded identities match the current repository, GitHub objects, branch, and linked change
- **THEN** completion verification may continue

#### Scenario: Identity or linkage changed
- **WHEN** any required identity differs or the Project item no longer links to the expected issue
- **THEN** synchronization stops, preserves diagnostic evidence, and leaves Project status unchanged

### Requirement: Completion requires specification and acceptance evidence
The workflow SHALL read the approved proposal, design, specifications, and tasks and compare the actual current implementation against every current issue acceptance criterion and every normative OpenSpec requirement. It SHALL require every implementation task and its required verification to be genuinely complete and marked complete. A successful agent or test process alone SHALL NOT be treated as proof of completion.

#### Scenario: All requirements are evidenced
- **WHEN** each acceptance criterion, normative requirement, and completed task has specific implementation or verification evidence
- **THEN** the semantic completion gate passes

#### Scenario: Task checkbox is incomplete
- **WHEN** any required task is unchecked or claims verification that was not performed
- **THEN** the completion gate fails and Project status remains unchanged

#### Scenario: Tests pass but a criterion is unmet
- **WHEN** all executed commands pass but an issue criterion or OpenSpec requirement lacks evidence or is not implemented
- **THEN** the completion gate fails and Project status remains unchanged

### Requirement: Repository-specific checks cover the current worktree
The workflow SHALL determine required verification commands from current repository instructions, approved OpenSpec artifacts, and declared project scripts rather than assuming a fixed stack. It SHALL include relevant tracked and untracked changes in verification and SHALL run every required applicable check, including strict OpenSpec validation and any required tests, linting, type checks, builds, or database and integration checks. A required skipped, blocked, missing, or failed check SHALL fail synchronization.

#### Scenario: Dirty worktree contains relevant implementation
- **WHEN** relevant implementation or specification changes are uncommitted
- **THEN** verification evaluates those changes and fingerprints the resulting worktree without modifying or discarding them

#### Scenario: Required command fails
- **WHEN** any applicable required command returns a failure
- **THEN** the workflow records the command and result, reports the failure, and leaves status unchanged

#### Scenario: Required check cannot run
- **WHEN** a required check is missing, skipped, or blocked by unavailable infrastructure
- **THEN** the workflow reports incomplete verification and leaves status unchanged

### Requirement: Verification evidence is durable and invalidated by change
For every synchronization attempt, the workflow SHALL persist a credential-free local evidence record containing GitHub and OpenSpec identities, verification commands and results, per-criterion results, relevant code and specification fingerprints, issue-requirement and required-check fingerprints, timestamp, and synchronization outcome. Evidence from a passing verification MAY be reused after a GitHub synchronization failure only when all recorded identities and fingerprints still match; otherwise verification SHALL run again.

#### Scenario: GitHub update fails after passing verification
- **WHEN** all completion gates pass but the GitHub mutation fails
- **THEN** passing verification evidence and the failed synchronization outcome are preserved for a later retry

#### Scenario: Retry inputs are unchanged
- **WHEN** a later synchronization attempt finds matching identity, code, specification, issue-requirement, and required-check fingerprints
- **THEN** it may reuse the passing evidence and retry only the guarded GitHub synchronization

#### Scenario: Any verified input changed
- **WHEN** code, relevant uncommitted changes, specifications, issue requirements, branch, identity, or required checks differ from the passing evidence
- **THEN** the evidence is invalidated and the complete verification process runs again before any mutation

### Requirement: Todo to Done mutation is narrow and conflict-safe
The workflow SHALL dynamically resolve the current Project Status field and Todo and Done option identifiers. It SHALL update only the recorded Project item from exactly Todo to exactly Done after every gate passes and after confirming verified fingerprints have not changed. It SHALL never close the issue or update another item.

#### Scenario: All gates pass and item remains Todo
- **WHEN** completion verification passes, fingerprints remain valid, and the selected Project item's current status is exactly Todo
- **THEN** the workflow updates only that item to Done and confirms the resulting live status

#### Scenario: Item is already Done
- **WHEN** the selected item is already exactly Done
- **THEN** the workflow reports that no update is needed and does not issue a duplicate mutation

#### Scenario: Item moved to another status
- **WHEN** the selected item is neither exactly Todo nor exactly Done
- **THEN** the workflow reports a status conflict and does not overwrite it

#### Scenario: Inputs change between verification and mutation
- **WHEN** a required fingerprint or identity changes before the mutation
- **THEN** the workflow aborts synchronization and requires fresh verification

### Requirement: Concurrent runs cannot conflict
The workflow SHALL enforce one active planning or synchronization run per repository before it creates proposal linkage or mutates Project state. It SHALL fail clearly when a live lock exists and SHALL not automatically remove an uncertain stale lock.

#### Scenario: Second run starts concurrently
- **WHEN** another planning or synchronization run already holds the repository lock
- **THEN** the second run exits without generating a duplicate proposal or attempting a status mutation

#### Scenario: Lock appears stale
- **WHEN** lock metadata does not correspond to a clearly live local process
- **THEN** the workflow reports recovery instructions and requires explicit confirmation before removing the lock

### Requirement: Security boundaries and failure handling are preserved
The workflow SHALL use the repository's existing GitHub CLI authentication, SHALL never store credentials in configuration, artifacts, evidence, or logs, and SHALL redact sensitive process output. It SHALL execute verification commands only from trusted repository instructions, approved OpenSpec artifacts, or declared scripts, never from issue content. Failures SHALL be reported accurately and SHALL leave unrelated local changes untouched.

#### Scenario: Sensitive value appears in subprocess output
- **WHEN** a known credential-bearing value is encountered during command execution
- **THEN** persisted and displayed diagnostic output omits or redacts that value

#### Scenario: Verification fails with unrelated local changes present
- **WHEN** synchronization cannot pass and the worktree also contains unrelated user changes
- **THEN** the workflow preserves those changes, performs no destructive cleanup, and reports only the in-scope failure
