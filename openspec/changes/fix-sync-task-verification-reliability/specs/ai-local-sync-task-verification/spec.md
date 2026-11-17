## Purpose

Make every supported local synchronization invocation verify the currently selected OpenSpec change in a deterministic, secret-safe environment before it can update one linked GitHub Project item.

## ADDED Requirements

### Requirement: Synchronization uses one invocation-derived verification path
Every supported `--sync-task` entry point SHALL converge on the same synchronization runner. The runner SHALL derive the issue and Project identities from the selected traceability record and live GitHub state, the linked OpenSpec change from the current invocation, required checks from the shared `ai-local-basic-completion-policy` and trusted repository inputs, and any optional semantic manifest from that issue and change. It SHALL NOT use an issue number, change identifier, branch name, manifest entry, or check list copied from a previous run.

#### Scenario: Explicit change is synchronized
- **WHEN** an operator invokes `--sync-task --change <change-id>` for an eligible linked change
- **THEN** the shared runner verifies the issue, Project item, checks, and manifest derived for that exact change

#### Scenario: Implicit candidate is synchronized
- **WHEN** an operator invokes `--sync-task` and selects or automatically resolves an eligible linked change
- **THEN** the same runner and gates used by the explicit form verify the resolved change

#### Scenario: A later issue requires a different check set
- **WHEN** trusted repository configuration and that issue's approved OpenSpec tasks select checks different from an earlier issue
- **THEN** only the newly derived required check set and its corresponding manifest govern the run

### Requirement: Applicable backend checks run in an isolated test configuration
The workflow SHALL run selected backend test checks with `APP_ENV=test` even when the caller environment uses another application environment. During those checks, a test-only dotenv policy SHALL allow tests that deliberately remove a required setting to observe it as missing instead of having `backend/.env` silently restore it. Ordinary application startup outside the test workflow SHALL retain its existing dotenv behavior.

#### Scenario: Caller uses a local application environment
- **WHEN** a selected backend check is started while the caller has `APP_ENV=local`
- **THEN** that check receives `APP_ENV=test` without modifying the caller's environment or local dotenv file

#### Scenario: A configuration test removes a required setting
- **WHEN** a backend test deliberately unsets a required application setting
- **THEN** `backend/.env` does not backfill the setting for that test and the test controls the expected missing-setting outcome

#### Scenario: Application starts normally outside verification
- **WHEN** the application is started through its ordinary non-test path
- **THEN** its existing dotenv loading and environment validation behavior is preserved

### Requirement: PostgreSQL prerequisites are conditional, validated, and safely diagnosed
The workflow SHALL determine from selected checks whether PostgreSQL is needed, respecting negated pytest markers. Before any PostgreSQL connection for a check being run, it SHALL validate `TEST_DATABASE_URL` and `MIGRATION_DATABASE_URL` for presence, supported PostgreSQL syntax, absence of embedded newlines or unescaped whitespace, approved test host, and an isolated safe test database target distinct from the ordinary application database. Diagnostics SHALL name the affected setting or command but SHALL NOT expose credentials or complete URLs. A run whose required checks do not require PostgreSQL SHALL proceed without these variables; separately run optional PostgreSQL checks retain this preflight.

#### Scenario: Selected checks do not require PostgreSQL
- **WHEN** the current issue selects only checks that do not connect to PostgreSQL
- **THEN** synchronization does not require or probe `TEST_DATABASE_URL` or `MIGRATION_DATABASE_URL`

#### Scenario: PostgreSQL setting is missing
- **WHEN** a PostgreSQL-requiring check is selected and either required database setting is absent
- **THEN** that PostgreSQL check is blocked before connection and names the missing setting; its optional status does not block a passing basic completion gate

#### Scenario: PostgreSQL setting contains whitespace corruption
- **WHEN** a required database URL contains an embedded newline or unescaped whitespace, including whitespace in the database target
- **THEN** that PostgreSQL check is blocked before connection and reports the affected setting without printing the URL

#### Scenario: PostgreSQL target is unsafe
- **WHEN** a required database URL uses an unsupported scheme, unapproved host, non-test database, or unsafe relationship to the application database
- **THEN** that PostgreSQL check is blocked before connection and reports the failed safety rule without exposing credentials

#### Scenario: Local permission denies PostgreSQL access
- **WHEN** a validated PostgreSQL target cannot be accessed because the process or sandbox is denied socket permission
- **THEN** the workflow reports a permission-denied blocked state distinct from service unavailability and from a test assertion failure

#### Scenario: PostgreSQL service is unreachable
- **WHEN** a validated PostgreSQL target cannot be reached because no service accepts the connection or the connection times out
- **THEN** the workflow reports an unreachable-service blocked state distinct from permission denial and from a test assertion failure

#### Scenario: PostgreSQL check executes and an assertion fails
- **WHEN** PostgreSQL preflight succeeds and the selected test command runs but returns a test failure
- **THEN** the workflow reports the affected command as a failed check rather than an infrastructure block

### Requirement: Optional semantic verification requires an explicit terminal result when run
When separately run or available as supplementary evidence, the workflow SHALL distinguish verifier progress messages from the terminal structured verification result. It SHALL report an explicit missing-final-result diagnostic when the verifier process completes without a terminal result. A terminal result SHALL cover the manifest generated for the current issue and change exactly once per entry, and a coverage error SHALL list the missing manifest IDs. The workflow SHALL continue to reject unknown IDs, duplicate IDs, duplicate command evidence, missing concrete evidence, references to commands that did not pass, unsupported not-applicable verdicts, and conflicts between per-entry verdicts and actual command results. An optional review result SHALL NOT block `Done` under the shared basic completion policy.

#### Scenario: Verifier emits progress before a complete result
- **WHEN** the semantic verifier emits one or more progress messages and then a valid terminal result
- **THEN** progress is retained only as diagnostic output and the terminal result alone is reconciled

#### Scenario: Verifier never emits a terminal result
- **WHEN** the verifier exits after progress output without a terminal structured result
- **THEN** the optional review reports a missing final semantic result without blocking a passing basic completion gate

#### Scenario: Terminal result omits current manifest entries
- **WHEN** the terminal result lacks one or more IDs from the current invocation's manifest
- **THEN** the optional review reports every omitted manifest ID without blocking a passing basic completion gate

#### Scenario: Terminal result cites invalid evidence
- **WHEN** a result uses an unknown or duplicate ID, lacks required evidence, cites a command that did not pass, or conflicts with its overall verdict
- **THEN** the existing semantic validation rejects that optional review result and reports it without blocking a passing basic completion gate

### Requirement: Project synchronization remains narrow, guarded, and idempotent
The workflow SHALL preserve the repository lock, traceability and live identity checks, strict OpenSpec validation, shared basic required-check gates, optional semantic-result reporting, evidence persistence, final fingerprint and status rechecks, and live Done confirmation. A run passing the required gates MAY request exactly one configured Todo-or-In-Progress-to-Done field update for the selected item. A failed or blocked required gate SHALL NOT request the update. An item already in Done SHALL succeed without a duplicate update, and synchronization SHALL NOT close the linked GitHub issue.

#### Scenario: Every gate passes for a Todo item
- **WHEN** the current invocation passes all required basic checks, identity checks, fingerprints, and final live status checks
- **THEN** the workflow requests one Todo-to-Done update for only the selected item and confirms its live Done status

#### Scenario: Verification is failed or blocked
- **WHEN** any required command, identity, or fingerprint gate fails or is blocked
- **THEN** the workflow persists the applicable diagnostic evidence and sends no Project status mutation

#### Scenario: Selected item is already Done
- **WHEN** every required verification and final live check passes and the selected item is already exactly Done
- **THEN** the workflow returns an idempotent success without sending a status mutation

#### Scenario: Synchronization completes
- **WHEN** either a Todo item is confirmed Done after the guarded update or an already-Done item is confirmed
- **THEN** the linked GitHub issue remains open
