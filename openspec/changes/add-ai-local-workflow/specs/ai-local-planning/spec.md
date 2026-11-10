## Purpose

Define a safe local workflow for selecting GitHub Project issues and producing reviewable, validated OpenSpec proposals with durable issue-to-change traceability.

## ADDED Requirements

### Requirement: Explicit local workflow configuration
The workflow SHALL read explicit configuration identifying the target GitHub repository, GitHub Projects v2 owner and project number, and the exact Todo and Done option names. It SHALL verify that the configured repository matches the current repository remote before reading or mutating Project data, and SHALL fail with an actionable message when configuration, authentication, or required local tools are unavailable.

#### Scenario: Valid configuration
- **WHEN** the user runs `npm run ai:local` in the configured repository with authenticated and available prerequisite tools
- **THEN** the workflow uses the configured repository and Project as its selection boundary

#### Scenario: Repository mismatch
- **WHEN** the configured repository does not match the current repository remote
- **THEN** the workflow exits before proposal generation or any GitHub mutation and reports both identities

#### Scenario: Missing authentication
- **WHEN** GitHub authentication is missing or invalid
- **THEN** the workflow exits with remediation guidance and does not expose credential material in output or runtime records

### Requirement: Dynamic Project discovery and complete Todo enumeration
The workflow SHALL discover the configured Project, its Status field, and its single-select option identifiers at runtime by exact configured names. It SHALL paginate all Project items, include only items whose current status is exactly Todo and whose content is an issue in the target repository, and SHALL not hard-code Project, field, option, item, or issue node identifiers.

#### Scenario: Multiple pages of mixed Project items
- **WHEN** eligible and ineligible items span multiple Project pages
- **THEN** the workflow fetches every page and lists only Todo issues belonging to the configured repository

#### Scenario: Status field or option is absent
- **WHEN** the configured Status field, Todo option, or Done option cannot be uniquely resolved
- **THEN** the workflow exits before selection with a configuration error and makes no changes

### Requirement: Interactive issue selection is safe and informative
The planning command SHALL present each eligible item in a numbered list containing issue number, title, and URL. It SHALL allow exactly one item to be selected and SHALL exit clearly without creating runtime linkage, OpenSpec artifacts, or GitHub changes when no eligible item exists or the user cancels.

#### Scenario: User selects an eligible issue
- **WHEN** the user chooses a valid numbered entry
- **THEN** the workflow continues using only that entry's issue and Project item identities

#### Scenario: No eligible issue exists
- **WHEN** the complete Project query returns no eligible Todo issue
- **THEN** the workflow reports that no eligible issues exist and exits successfully without changes

#### Scenario: User cancels selection
- **WHEN** the user cancels or ends the interactive prompt
- **THEN** the workflow reports cancellation and exits without changes

### Requirement: Issue requirements and repository context are gathered safely
For the selected item, the workflow SHALL fetch the current issue title, body, URL, acceptance criteria present in the issue, and all relevant paginated issue comments. It SHALL inspect the current repository and its governing instructions for context. Issue and comment content SHALL be treated as untrusted task data and SHALL not override repository instructions, OpenSpec workflow instructions, security boundaries, or command policy.

#### Scenario: Issue has paginated comments and acceptance criteria
- **WHEN** a selected issue contains acceptance criteria and relevant comments across multiple pages
- **THEN** the proposal context includes the complete requirements and comments with their source identity preserved

#### Scenario: Issue content contains executable instructions
- **WHEN** an issue or comment asks the agent to reveal credentials, ignore repository rules, run an unrelated command, or mutate GitHub state
- **THEN** the content is retained only as quoted task input and the requested override or mutation is not performed

### Requirement: Issue-to-change traceability is unique and durable
The workflow SHALL record the repository, Project, Project item, issue, current branch and commit, and OpenSpec change identifiers in a local runtime link record and in a stable machine-readable marker within the generated proposal. It SHALL detect linked active or archived changes before creating a new proposal and SHALL offer reuse rather than silently creating a duplicate.

#### Scenario: No linked change exists
- **WHEN** the selected issue has no valid linked OpenSpec change
- **THEN** the workflow proposes a deterministic, collision-safe change identifier and records all required identities after successful proposal generation

#### Scenario: Exactly one linked change exists
- **WHEN** the selected issue has one valid linked OpenSpec change
- **THEN** the workflow identifies it and allows the user to reuse it without creating another change

#### Scenario: Multiple or inconsistent links exist
- **WHEN** more than one candidate link exists or recorded identities disagree
- **THEN** the workflow reports the candidates and requires explicit resolution without overwriting any link or creating a proposal

### Requirement: Installed OpenSpec proposal workflow is invoked correctly
The planning workflow SHALL invoke Codex non-interactively with an explicit request to use the installed `openspec-propose` skill for the selected issue. It SHALL not treat a skill name as a shell executable. The generated change SHALL contain the proposal, design, capability specifications, and dependency-ordered tasks required by repository conventions, include issue and Project item traceability, define acceptance criteria and required verification, and pass available strict OpenSpec validation.

#### Scenario: Proposal generation succeeds
- **WHEN** Codex completes the installed proposal workflow and strict validation passes
- **THEN** the CLI shows the change identifier, generated artifact paths, and validation result

#### Scenario: Proposal generation or validation fails
- **WHEN** Codex fails, required artifacts are absent, traceability is invalid, or OpenSpec validation fails
- **THEN** the workflow reports the failure, does not claim the proposal is ready, and does not update GitHub status

### Requirement: Planning stops for explicit review
After generating or reusing a proposal, the planning workflow SHALL stop for human review. It SHALL NOT apply implementation tasks, invoke the apply workflow, alter Project status, close the issue, create or switch branches, or commit, push, merge, or deploy code.

#### Scenario: Valid proposal is ready
- **WHEN** proposal generation and validation complete successfully
- **THEN** the CLI explains how to review the artifacts and manually invoke `$openspec-apply-change <change-id>` in Codex, then exits without implementation or GitHub mutation

