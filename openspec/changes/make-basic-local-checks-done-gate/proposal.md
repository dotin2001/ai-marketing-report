## Why

`ai:local --sync-task` currently treats every discovered command and AI semantic review as a blocking completion gate. That makes a locally complete issue depend on live services and an AI verifier even when the repository's basic, applicable checks pass. The shared completion policy needs to reflect the requested local verification threshold for every issue.

## What Changes

- **BREAKING**: Replace the current all-discovered-checks and semantic-review `Done` gate with a shared basic-check policy: strict OpenSpec validation, `git diff --check`, and applicable repository frontend and backend unit-test scripts.
- Classify live PostgreSQL, migration smoke, live object-storage, and AI semantic review as optional for `--sync-task`; report available outcomes without letting missing or failed optional results block `Done`. Keep standalone commands available.
- Correct backend execution-profile inference so negated pytest markers do not imply PostgreSQL or storage prerequisites. The `backend:test` script runs in its service-free test environment.
- Preserve linked issue and Project resolution, task and artifact checks, fingerprint and final live guards, exact status-transition rules, retry safety, and manual `--apply` behavior. Name the required check that blocks synchronization.
- Add mocked regression coverage and verify the issue 6 acceptance command without a live GitHub status write.

## Capabilities

### New Capabilities

- `ai-local-basic-completion-policy`: Defines the shared required and optional verification policy for all `--sync-task` runs and its guarded `Done` outcome.

### Modified Capabilities

None in `openspec/specs/` (no archived baseline specs exist). This new capability explicitly supersedes the stronger completion gates in the active `add-ai-local-workflow`, `fix-sync-task-verification-reliability`, and `start-explicit-issue-work-in-progress` change specs; those artifacts must be reconciled before implementation so the approved behavioral source stays coherent.

## Impact

The change affects `ai-local.config.json`, check discovery and execution-profile inference, synchronization and evidence/retry handling, CLI diagnostics, workflow documentation, template parity, and `scripts/ai-local/__tests__`. It does not change the product frontend/backend runtime APIs or require a live GitHub write for acceptance testing.
