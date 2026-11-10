# ai-marketing-report

This repository includes a guarded local AI workflow that selects an eligible GitHub Project `Todo` issue, creates or reuses a validated OpenSpec proposal, and later verifies the implemented change before updating only that Project item to `Done`.

```sh
npm run ai:local
npm run ai:local -- --sync-task
npm run ai:local -- --sync-task --change <change-id>
```

Planning can be cancelled safely and reuses an existing valid issue/change link instead of duplicating it. Review and apply the proposal manually in Codex with `$openspec-apply-change <change-id>`. Failed verification leaves `Todo` unchanged; a failed GitHub synchronization retains passing evidence for a fingerprint-checked retry.

The issue always remains open. The automation never switches branches, commits, pushes, merges, rebases, deploys, destructively cleans the worktree, or updates a non-selected Project item.

See [Local AI Planning and Project Synchronization](docs/ai-local-workflow.md) for authentication, configuration, every Todo-to-Done gate, evidence/redaction limits, lock recovery, and troubleshooting.
