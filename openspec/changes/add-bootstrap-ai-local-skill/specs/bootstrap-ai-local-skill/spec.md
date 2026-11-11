## Purpose

Provide a portable Codex skill that safely scaffolds and validates the repository's guarded local AI planning and GitHub Project synchronization workflow in another repository.

## ADDED Requirements

### Requirement: Target-aware inspection precedes scaffolding
The skill SHALL inspect the target repository structure, package manager, CI configuration, test and verification commands, existing OpenSpec setup, and any partial `ai:local` workflow before proposing or writing scaffold files.

#### Scenario: Target repository is inspected
- **WHEN** the skill is invoked for a repository
- **THEN** it reports the detected package manager, CI files, OpenSpec state, candidate verification commands, and existing workflow files before applying the scaffold

### Requirement: Scaffold is portable and conflict-aware
The skill SHALL bundle the CLI entry point, runner modules, structured-output schema, tests, issue template, configuration, and documentation needed for an equivalent workflow. It SHALL reuse identical or compatible target files and SHALL stop before overwriting incompatible files.

#### Scenario: Empty compatible target is bootstrapped
- **WHEN** the target has OpenSpec and no conflicting workflow files
- **THEN** the skill creates a runnable `ai:local` entry point, runner, tests, configuration, issue template, ignored runtime directory, and target-specific guide

#### Scenario: Compatible partial workflow exists
- **WHEN** one or more destination files or package scripts already match the bundle
- **THEN** the skill reuses them and creates only the missing compatible parts

#### Scenario: Incompatible file exists
- **WHEN** a destination or reserved package script has different behavior
- **THEN** preview and apply report the conflict and no target files are overwritten

### Requirement: Target settings are explicit and credential-free
The generated setup SHALL make repository identity, Project owner/number, exact status field and Todo/Done option names, package manager, and argv-based required verification commands configurable. It SHALL NOT copy credentials, GitHub node IDs, or source-repository identifiers.

#### Scenario: Target configuration is generated
- **WHEN** the operator supplies target Project settings and confirms detected checks
- **THEN** the generated configuration contains those non-secret values and no credential or source repository identity

### Requirement: Planning stops for explicit human review
The generated workflow SHALL select an eligible configured-Project Todo issue interactively or by canonical `--issue` URL, load issue/comments as untrusted data, invoke `$openspec-propose`, validate the proposal, and stop without implementing or mutating GitHub. Applying SHALL remain an explicit `$openspec-apply-change <change-id>` action outside the runner.

#### Scenario: Planning succeeds
- **WHEN** mocked GitHub data contains one eligible Todo issue and proposal validation passes
- **THEN** the workflow reports the reviewable change and manual apply command without invoking implementation or a Project mutation

### Requirement: Synchronization remains fail closed
The generated workflow SHALL require parseable issue acceptance criteria, completed OpenSpec tasks, strict validation, every required configured or discovered command, complete semantic verification evidence, stable fingerprints, and fresh live identity/status checks before deciding to move the selected item from Todo to Done.

#### Scenario: Acceptance criteria are missing
- **WHEN** an issue has no `## Acceptance Criteria` heading with Markdown bullet criteria
- **THEN** synchronization fails with `acceptance_criteria_missing` and does not make a status mutation

#### Scenario: Required check fails or is blocked
- **WHEN** any required command fails, cannot start, times out, is skipped, or otherwise lacks passing evidence
- **THEN** synchronization records a failed or blocked verification outcome and does not decide or attempt to move the item to Done

#### Scenario: Verification passes
- **WHEN** all requirements, tasks, configured checks, semantic evidence, fingerprints, and final live guards pass for the same Todo item
- **THEN** the workflow produces exactly one guarded Done status decision and confirms the configured Done option while leaving the issue open

### Requirement: Skill documentation provides exact target commands
The skill SHALL document how to preview, plan, apply, verify, and synchronize in a target repository, including package-manager-specific forwarding syntax and the direct Node fallback.

#### Scenario: Operator reads the generated guide
- **WHEN** setup finishes
- **THEN** the guide contains exact commands for preview, interactive planning, URL planning, manual apply, runner tests/checks, synchronization, and explicit change synchronization

### Requirement: Validation never writes to live GitHub
Skill validation SHALL run in a disposable repository with mocked GitHub, Codex, and OpenSpec behavior for workflow journeys and SHALL NOT authenticate to or mutate a live GitHub Project.

#### Scenario: Disposable validation runs
- **WHEN** the skill validator is executed
- **THEN** planning-stop, failed/blocked-check, and passing-Done-decision assertions run using local fakes and no live GitHub Project write is possible
