# ai-marketing-report

This repository includes a guarded local AI workflow that selects an eligible GitHub Project `Todo` issue, confirms its `In Progress` status, creates or reuses a validated OpenSpec proposal, and later runs the shared basic local checks before updating only that Project item to `Done`.

```sh
npm run ai:local
npm run ai:local -- --issue https://github.com/dotin2001/ai-marketing-report/issues/2
npm run ai:local -- --sync-task
npm run ai:local -- --sync-task --change <change-id>
```

Planning can be interactive or target one canonical GitHub issue URL. Selecting a number moves that `Todo` item to `In Progress` before proposal work; cancellation or declined reuse leaves status unchanged. URL-targeted planning accepts an exact `Todo` or `In Progress` item in the configured Project; the standalone `--` forwards `--issue` through npm. If planning fails after the status change, retry with the selected issue's URL without another status write. Both planning forms can reuse an existing valid issue/change link instead of duplicating it and stop before implementation. Review and apply the proposal manually in Codex with `$openspec-apply-change <change-id>`.

For synchronization, a normal non-empty issue description is sufficient and becomes one issue-level criterion for optional semantic review. A Markdown Acceptance Criteria section is optional but recommended when separate outcomes need separate evidence. Empty issue bodies and explicitly present criteria sections without bullet items fail closed. A failed required basic check leaves `Todo` or `In Progress` unchanged; a failed GitHub synchronization retains passing evidence for a fingerprint-checked retry.

The issue always remains open. The automation never switches branches, commits, pushes, merges, rebases, deploys, destructively cleans the worktree, or updates a non-selected Project item.

See [Local AI Planning and Project Synchronization](docs/ai-local-workflow.md) for authentication, configuration, every Todo-to-Done gate, evidence/redaction limits, lock recovery, and troubleshooting.

See [Local development](docs/local-development.md) for the pinned frontend/backend toolchain, environment setup, SeaweedFS dependency stack, health checks, verification commands, ordinary shutdown, and the separately labeled destructive reset.

Object storage is private and backend-authorized: original CSVs and generated PDFs use deterministic owner/report-scoped identities, PostgreSQL retains their integrity metadata, and completed PDFs are fully verified before an authenticated backend stream is returned. The local guide documents the deterministic storage checks, isolated PostgreSQL suite, and separately opted-in SeaweedFS compatibility test with exact-key cleanup.
