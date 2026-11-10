## Why

The repository has OpenSpec planning conventions and installed Codex workflows, but no local automation that safely connects GitHub Project work selection to proposal generation and completion synchronization. A guarded CLI is needed to preserve issue-to-change traceability, keep proposal approval and implementation manual, and prevent a Project item from being marked Done without evidence that the approved work is actually complete.

## What Changes

- Add a repository-local `npm run ai:local` planning workflow that discovers the configured GitHub repository and Project, paginates eligible Todo issues, supports interactive selection and cancellation, and gathers the selected issue requirements and relevant repository context.
- Invoke the installed `openspec-propose` Codex skill through its actual Codex invocation mechanism, generate and validate an OpenSpec change, detect an existing linked change, show its artifacts and validation result, and stop for human review without applying code or changing GitHub state.
- Preserve stable traceability among the repository, Project, Project item, issue, branch, commit, and OpenSpec change while treating all GitHub content as untrusted task data.
- Add a separate `--sync-task` workflow that verifies identities, current requirements, approved artifacts, implementation tasks, acceptance criteria, repository checks, and relevant uncommitted changes before it can update exactly one Project item from Todo to Done.
- Persist local verification evidence and fingerprints so a failed GitHub synchronization can be retried only while the verified inputs remain unchanged.
- Add repository-wide concurrency protection, dynamic GitHub Project field discovery, safe retry and conflict behavior, credential-safe logging, and actionable error reporting.
- Document configuration, minimum GitHub permissions, exact planning/apply/synchronization usage, runtime-record handling, and failure recovery.
- Add automated tests for selection, proposal reuse, verification gates, evidence invalidation, synchronization conflicts and retries, concurrency, and the primary end-to-end CLI journeys using controlled fakes.

## Capabilities

### New Capabilities

- `ai-local-planning`: Configures and runs local GitHub Project issue selection, issue inspection, installed OpenSpec proposal generation, review stopping, and issue-to-change traceability.
- `ai-local-synchronization`: Verifies approved work, records reusable evidence, protects concurrent execution, and safely synchronizes a single eligible Project item from Todo to Done.

### Modified Capabilities

None.

## Impact

- Adds the repository's initial Node/npm tooling entry point, using Node.js built-ins plus the existing `gh`, `codex`, and `openspec` CLIs rather than duplicating their authentication, agent, or validation behavior.
- Adds local automation modules, schemas, tests, setup documentation, explicit GitHub repository/Project configuration, and ignored runtime state under `.ai-local/`.
- Reads GitHub Issues and Projects v2 through the authenticated GitHub CLI and performs one narrowly scoped Project field mutation only after all synchronization gates pass.
- Does not implement application features, automatically apply an OpenSpec change, alter issue state, create branches, or commit, push, merge, deploy, or use GitHub Actions.
