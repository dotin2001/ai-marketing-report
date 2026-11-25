## Why

Selecting an issue number with `npm run ai:local --` currently leaves the selected GitHub Project item in `Todo`, while choosing the same issue by URL moves it to `In Progress`. The operator wants both selection paths to show that work has started.

## What Changes

- After a numbered selection, move only the selected, still-eligible Project item from exact `Todo` to exact `In Progress` and confirm the write before proposal generation or accepted linked-change reuse.
- Keep cancellation and declined reuse free of status writes. Retain idempotent retry and fail-closed identity/status checks from the URL path.
- Update CLI guidance, repository documentation, mocked workflow tests, and the bundled bootstrap template so installed workflows behave the same way.
- Preserve the separate, verification-gated `--sync-task` transition to `Done` and manual OpenSpec apply.

## Capabilities

### New Capabilities

- `ai-local-interactive-work-start`: Guarded `Todo` to `In Progress` transition after numbered issue selection, including cancellation, reuse, retries, and confirmation.

### Modified Capabilities

None. The earlier interactive no-mutation rule exists only in active change deltas; no main specification exists under `openspec/specs/`. This change supersedes that rule for a selected issue and must be reconciled with the older deltas before archiving.

## Impact

The local `ai:local` planning runner, its mocked Node tests, CLI/help and workflow documentation, and `.agents/skills/bootstrap-ai-local/assets/template/` are affected. The workflow changes one GitHub Project Status field only when the operator actually selects an eligible issue. It does not close or edit the issue, change branches, implement the proposal, or alter the completion gates.
