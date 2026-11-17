## 1. Configuration and Project Resolution

- [x] 1.1 Add and validate an exact `inProgressOption` beside the existing status names in `scripts/ai-local/config.mjs` and `ai-local.config.json`; verify config tests reject missing, duplicate, or malformed names and accept the committed configuration.
- [x] 1.2 Resolve the `In Progress` option ID from the configured Project Status field in `project.mjs` and expose full Project Issue enumeration for explicit URL matching while retaining the interactive `Todo` list; verify mocked pagination, option-resolution, wrong-type, and cross-repository cases.

## 2. Guarded Planning Transition

- [x] 2.1 Update explicit URL resolution to require one matching Project Issue and admit only exact `Todo` or `In Progress` status with matching live option IDs; verify tests for missing, duplicate, fork, cross-repository, other-status, and retry cases.
- [x] 2.2 Reuse the existing Project status mutation and confirming read behind a planning-specific live identity/status guard; verify mocked GitHub tests prove one `Todo` to `In Progress` write, zero write for `In Progress`, no write on drift, and sanitized typed errors for mutation or confirmation failure.
- [x] 2.3 Wire the guarded transition into URL-targeted `workflow.mjs` after preflight, issue and link eligibility checks and after accepted reuse, but before Codex proposal generation or successful reuse reporting; verify journey tests cover ordering, cancelled reuse, repeated runs, uncertain write outcome, other statuses, and no proposal/link on a required update failure.

## 3. Completion Compatibility and Documentation

- [x] 3.1 Extend the existing `--sync-task` final status guard to accept exact `In Progress` as a verified predecessor to `Done`, preserving `Todo` compatibility, `Done` idempotency, all verification/fingerprint/identity gates, and rejection of other statuses; verify mocked CLI and guard regressions including no mutation when a gate fails.
- [x] 3.2 Update CLI help and `docs/ai-local-workflow.md` to describe the URL-targeted start transition, retry behavior, manual `$openspec-apply-change` review step, and verified `In Progress` to `Done` synchronization; verify documentation tests match command behavior.
- [x] 3.3 Mirror runner, configuration, docs, and tests in `.agents/skills/bootstrap-ai-local/assets/template/` and update bootstrap settings/contract surfaces that require exact status names; verify template parity and bootstrap-focused tests pass.

## 4. Verification and Handoff

- [x] 4.1 Run focused mocked GitHub tests for project resolution, explicit selection, planning workflow, status sync, and completion guard; verify every start, retry, other-status, and failure case passes without live GitHub access.
- [x] 4.2 Run `npm test`, `npm run check`, and `openspec validate start-explicit-issue-work-in-progress --strict --json`; require all to pass and report any intentionally unrun live check before implementation handoff.
- [x] 4.3 Before archiving, reconcile the older unarchived planning, explicit-selection, and synchronization deltas with this capability so no main specification retains a contradictory no-mutation or Todo-only completion rule; verify the eventual archive plan with strict OpenSpec validation.
