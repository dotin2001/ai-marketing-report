## Why

URL-targeted `ai:local` planning currently leaves a selected issue in `Todo`, so the configured GitHub Project does not show that work has started. Moving the eligible item to `In Progress` before proposal generation makes the Project reflect the workflow's actual start and gives a failed planning run a clear retry point.

## What Changes

- For `npm run ai:local -- --issue <github-issue-url>`, resolve the issue to one item in the configured Project and, after existing eligibility checks, change exactly `Todo` to `In Progress` before invoking Codex to generate a proposal.
- Discover the exact `In Progress` option dynamically and reuse the existing Project field mutation and confirming-read path. An already `In Progress` item receives no duplicate write and may continue through the existing link and retry checks; every other status remains untouched.
- Fail closed with an actionable, sanitized error if the required update or its confirmation fails. No proposal generation follows that failure.
- Keep manual `$openspec-apply-change` as a separate review decision. Preserve `--sync-task` completion verification and its `Done` gate while allowing a verified item that was moved to `In Progress` to reach `Done`; retain its existing `Todo` and idempotent `Done` handling.
- Add mocked GitHub regression tests and update CLI help, workflow documentation, and the bundled bootstrap template to match the new status contract.

## Capabilities

### New Capabilities

- `ai-local-project-work-start`: Defines the guarded URL-targeted `Todo` to `In Progress` start transition, idempotent retry, review stop, and compatibility with verified completion.

### Modified Capabilities

None. The earlier `ai-local-planning`, `ai-local-explicit-issue-selection`, and `ai-local-synchronization` specs exist only as unarchived change deltas, so this change introduces a separate capability and identifies the superseded clauses below.

## Impact

- Affects `scripts/ai-local/{workflow,project,explicit-issue,status-sync,guard,cli,sync-workflow}.mjs`, targeted tests, `ai-local.config.json`, `docs/ai-local-workflow.md`, and mirrored workflow files in `.agents/skills/bootstrap-ai-local/assets/template/` where applicable.
- Reuses the configured repository, Project owner and number, Status field, GitHub CLI authentication, runtime lock, and existing `updateProjectV2ItemFieldValue` mutation. The configuration gains the exact `In Progress` option name; no Project node ID is hard-coded.
- Makes one intentional exception to the prior planning specification's no-Project-mutation promise for the URL-targeted start transition. It adds no automatic apply, issue closing, branch change, commit, push, or deployment.
- Before archiving, reconcile the older pending deltas that still say planning never mutates Project status and `--sync-task` accepts only `Todo` or `Done`; this new change does not silently edit those unrelated artifacts.
