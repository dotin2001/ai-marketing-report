## Purpose

Define when URL-targeted local planning marks one eligible GitHub Project issue as started, how retries remain safe, and how that status reaches verified completion.

## ADDED Requirements

### Requirement: URL-targeted planning starts one eligible Project issue
For `npm run ai:local -- --issue <github-issue-url>`, the workflow SHALL resolve the canonical URL to exactly one Issue item in the repository's configured GitHub Project after normal preflight and eligibility checks. A new start SHALL require exactly the configured `Todo` status and SHALL change only that item's configured Status field to the exact configured `In Progress` option before invoking proposal generation. It SHALL dynamically resolve the field and option IDs, re-read the item and issue linkage before mutation, and confirm both the resulting option name and ID before continuing. The URL-targeted start transition is the sole planning exception to the prior no-Project-mutation rule.

#### Scenario: One matching Todo issue starts
- **WHEN** the URL resolves to one eligible `Todo` Issue item in the configured Project and the live identity remains stable
- **THEN** the workflow writes exactly one `In Progress` status update, confirms it, and only then invokes proposal generation

#### Scenario: URL is absent or ambiguous in the Project
- **WHEN** the issue has no eligible matching Project item or more than one item matches its repository and issue number
- **THEN** the workflow reports the eligibility or identity conflict without a status write or proposal generation

#### Scenario: Item or status changes before the write
- **WHEN** the live Project item no longer has the expected issue linkage or exact `Todo` status when re-read
- **THEN** the workflow stops without overwriting the changed item or generating a proposal

### Requirement: In Progress retries are idempotent and other statuses are protected
The workflow SHALL admit an exact `In Progress` matching item as a URL-targeted retry candidate, subject to the existing linked-change and proposal retry rules, and SHALL perform no duplicate status write. It SHALL reject all other statuses without mutation. A cancelled reuse decision SHALL leave status unchanged; an accepted reuse SHALL confirm `In Progress` before reporting the linked proposal ready. A proposal failure after confirmed status change SHALL leave that status available for a later retry and SHALL NOT claim a proposal is ready or persist a new link.

#### Scenario: Prior start is retried
- **WHEN** the matching item is already exactly `In Progress` and existing link or proposal retry checks permit continuation
- **THEN** the workflow skips the status mutation and continues the permitted planning path

#### Scenario: User cancels linked proposal reuse
- **WHEN** the issue has one existing linked change and the user declines reuse
- **THEN** the workflow exits without a status write or new proposal

#### Scenario: Other status is encountered
- **WHEN** the matching item is neither exactly `Todo` nor exactly `In Progress`
- **THEN** the workflow reports ineligibility and leaves the item untouched

#### Scenario: Proposal generation fails after start
- **WHEN** proposal generation or strict validation fails after `In Progress` was confirmed
- **THEN** the workflow reports the failure, records no new link, and allows a guarded later retry from the current status

### Requirement: Required start status failure stops proposal work
A required `Todo` to `In Progress` status update or its confirmation SHALL fail closed with a typed, actionable, sanitized error. The workflow SHALL NOT invoke Codex proposal generation or persist a new link after such a failure. If the mutation outcome is uncertain, a retry SHALL re-read the item and avoid repeating a write when `In Progress` is already confirmed.

#### Scenario: GitHub rejects the update
- **WHEN** GitHub rejects the status mutation, times out, or returns an invalid mutation response
- **THEN** the command reports a retryable status error without credential material, skips proposal generation, and leaves unrelated items unchanged

#### Scenario: GitHub does not confirm the target status
- **WHEN** the post-mutation read does not confirm the configured `In Progress` name and option ID
- **THEN** the command reports the confirmation failure and stops before proposal generation

### Requirement: Review and verified completion boundaries remain intact
URL-targeted planning SHALL stop for human review after a validated new or reused proposal and SHALL NOT apply implementation, close the issue, switch branches, commit, push, merge, or deploy. Interactive planning SHALL retain its existing `Todo` selection and no-status-mutation behavior. The `--sync-task` workflow SHALL retain all existing task, acceptance, check, semantic-evidence, fingerprint, identity, and final-live-read gates before setting `Done`; after those gates pass, exactly `Todo` or `In Progress` may transition to `Done`, while `Done` remains idempotent and all other statuses remain conflicts. Manual `$openspec-apply-change` behavior SHALL remain separate from the CLI.

#### Scenario: URL-targeted proposal is ready
- **WHEN** a new or reused URL-targeted proposal passes its existing validation
- **THEN** the CLI reports artifacts and the manual apply step, then exits without implementation or another GitHub mutation

#### Scenario: Interactive planning runs
- **WHEN** the user runs `npm run ai:local` without `--issue`
- **THEN** the workflow keeps the numbered `Todo` selector and performs no planning status write

#### Scenario: In Progress work is verified complete
- **WHEN** all existing synchronization verification and final guard checks pass for a linked item whose exact status is `In Progress`
- **THEN** `--sync-task` updates only that item to `Done` and confirms the result

#### Scenario: Completion gate fails
- **WHEN** any required completion check, semantic evidence, identity, or fingerprint gate fails
- **THEN** `--sync-task` does not change `In Progress` or any other status to `Done`

#### Scenario: Existing completion statuses remain supported
- **WHEN** all completion gates pass for an exact `Todo` item or the linked item is already exact `Done`
- **THEN** the existing verified `Todo` to `Done` and idempotent `Done` behavior remains available
