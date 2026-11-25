## Purpose

Ensure numbered issue selection in the local planning workflow records that the selected GitHub Project task has started while preserving safe cancellation, retry, and review boundaries.

## ADDED Requirements

### Requirement: Numbered selection starts only the chosen Project task
When the operator selects an issue number in the interactive `ai:local` planning flow, the workflow SHALL re-read the selected Project item and verify its configured Project, repository, issue identity, and exact `Todo` status before changing only that item's configured Status field to exact `In Progress`. It SHALL resolve the configured field and option IDs live and SHALL confirm the resulting option name and ID before generating a new proposal or reporting an accepted linked proposal ready. An item already at exact `In Progress` MAY continue through the existing URL-targeted retry path without another write.

#### Scenario: Eligible issue is selected
- **WHEN** the operator selects one listed `Todo` issue by number and its live Project identity and status still match
- **THEN** exactly that Project item changes to `In Progress` and the workflow confirms the result before proposal generation
- **AND** no other Project item or GitHub issue is changed

#### Scenario: Selection is cancelled
- **WHEN** the operator cancels, enters end-of-input, or makes no valid selection
- **THEN** no Project status write or proposal generation occurs

#### Scenario: Live item changed before start
- **WHEN** the selected item's live issue linkage or exact `Todo` status differs from the selected list entry
- **THEN** the workflow reports a safe conflict without a status write or proposal generation

### Requirement: Reuse and failure preserve the start boundary
The workflow SHALL ask whether to reuse an existing linked change before changing the selected item's status. A declined reuse SHALL leave status unchanged. An accepted reuse SHALL confirm `In Progress` before validating and reporting that change ready. A failed or unconfirmed status update SHALL stop before proposal generation and new-link persistence with a sanitized retryable error. A later proposal failure SHALL NOT report readiness or write a new link; the confirmed `In Progress` item SHALL remain available to the existing canonical-URL retry flow.

#### Scenario: Operator declines linked reuse
- **WHEN** the selected issue has a linked change and the operator declines reuse
- **THEN** no status write or new proposal occurs

#### Scenario: GitHub rejects or cannot confirm start
- **WHEN** the selected item's status update fails or the confirmation read does not show exact `In Progress`
- **THEN** the command stops before proposal generation and link persistence, reports a safe retry instruction, and leaves unrelated items unchanged

#### Scenario: Proposal fails after start
- **WHEN** proposal generation or strict validation fails after `In Progress` is confirmed
- **THEN** no new link or ready claim is recorded
- **AND** the operator can retry the same issue with `npm run ai:local -- --issue <github-issue-url>` without a duplicate status write

### Requirement: Manual apply and completion gates remain separate
Interactive planning SHALL stop after a validated proposal and report the manual `$openspec-apply-change` step. It SHALL NOT implement code, close the issue, switch branches, commit, push, merge, deploy, or move the Project item to `Done`. The existing `--sync-task` verification, identity, fingerprint, and final live-read gates SHALL remain required for the later `In Progress` to `Done` transition. The bundled bootstrap workflow SHALL provide the same numbered-selection behavior.

#### Scenario: Interactive proposal is ready
- **WHEN** a selected issue's new or reused proposal passes strict validation after the confirmed start
- **THEN** the CLI reports the proposal and manual apply command and exits with the selected Project item at `In Progress`

#### Scenario: Completion gate fails
- **WHEN** required `--sync-task` verification or final guards fail
- **THEN** the item remains `In Progress` and no `Done` mutation occurs
