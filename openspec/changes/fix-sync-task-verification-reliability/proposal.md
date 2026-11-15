## Why

The shared `--sync-task` workflow inherits caller-local backend settings and treats an incomplete semantic-verifier message as final output, so correct work can fail for environmental reasons that are unrelated to the selected issue. The completed reporting-database issue provides concrete regression evidence: local `APP_ENV`, dotenv backfill, a whitespace-corrupted test URL, restricted PostgreSQL access, and a progress-only semantic message each produced misleading or nondeterministic failures.

## What Changes

- Make every supported `--sync-task` CLI form use one issue-agnostic execution path that derives the linked issue, OpenSpec change, required checks, check capabilities, and semantic manifest from the current invocation and trusted repository configuration.
- Give applicable backend checks a deterministic test environment with `APP_ENV=test` and a test-only dotenv policy that lets deliberate missing-setting tests remain missing without changing normal application startup.
- Preflight PostgreSQL configuration only when selected checks require it, reject missing, whitespace-corrupted, credential-unsafe, or non-test targets without disclosing secrets, and distinguish access denial, service unavailability, and an executed test failure.
- Separate semantic-verifier progress from its terminal result, fail explicitly when no terminal result exists, and report manifest-specific missing IDs while retaining all existing evidence and consistency checks.
- Preserve the current lock, traceability, required gates, fingerprint rechecks, single Todo-to-Done mutation, Done idempotence, confirmation read, and open GitHub issue behavior.
- Add real-CLI regression fixtures with mocked GitHub operations for at least two different issues and OpenSpec changes, including PostgreSQL and non-PostgreSQL check sets, passing, blocked, reported-failure, and already-Done paths.
- Update the repository workflow documentation and keep the reusable bootstrap workflow assets behaviorally aligned with the repository runner.

## Capabilities

### New Capabilities

- `ai-local-sync-task-verification`: Reliable, issue-independent required-check execution, environment isolation, PostgreSQL preflight diagnostics, terminal semantic-result validation, and guarded Project synchronization for `--sync-task`.

### Modified Capabilities

None. The repository has no archived/main capability spec for the existing synchronization workflow; this focused capability defines the reliability contract while preserving the current synchronization gates.

## Impact

- Affected runtime code: `scripts/ai-local.mjs`, the npm wrapper, and shared modules under `scripts/ai-local/` for synchronization, check discovery/execution, subprocess environments, semantic verification, evidence, and diagnostics.
- Affected configuration and tests: `ai-local.config.json`, `package.json` script metadata as needed, Node regression fixtures under `scripts/ai-local/__tests__/`, and backend test-only configuration behavior.
- Affected reusable assets and documentation: `.agents/skills/bootstrap-ai-local/assets/template/` parity where the same runner is distributed, `docs/ai-local-workflow.md`, and related command/documentation assertions.
- No application API, production database schema, GitHub issue state, branch identity, or Project state is changed during proposal or implementation. The completed issue remains regression evidence and its existing Done status must not be mutated.
