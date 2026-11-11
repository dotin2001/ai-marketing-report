# Portable ai:local contract

## Source provenance

This bundle was derived from the repository's tested `ai:local` workflow on 2026-11-11. The source-of-truth surface inspected during packaging was:

- entry point and package scripts: `scripts/ai-local.mjs`, `package.json`;
- runner modules: `scripts/ai-local/*.mjs`;
- structured verification schema: `scripts/ai-local/schemas/verification.schema.json`;
- prompts: `planning-context.mjs` and `codex.mjs`;
- tests: `scripts/ai-local/__tests__/*.test.mjs`;
- target settings: `ai-local.config.json`;
- user documentation: `docs/ai-local-workflow.md` and `README.md`;
- behavioral artifacts: OpenSpec changes `add-ai-local-workflow` and `add-explicit-issue-selection`.

The bundled runner preserves that flow. Its portability-only additions are a configurable package manager and explicit safe argv-based verification commands. The source repository's workflow is not modified.

## Exact bootstrap commands

Set `SKILL_DIR` in the examples to the absolute directory containing this skill.

Inspect without writes:

```sh
node "$SKILL_DIR/scripts/bootstrap.mjs" --mode inspect --target .
```

Preview an npm target:

```sh
node "$SKILL_DIR/scripts/bootstrap.mjs" \
  --mode preview \
  --target . \
  --repository 'owner/repository' \
  --project-owner 'owner' \
  --project-number 1 \
  --status-field 'Status' \
  --todo-option 'Todo' \
  --done-option 'Done' \
  --package-manager npm \
  --verification-command '["npm","test"]' \
  --verification-command '["npm","run","lint"]'
```

Apply the exact preview by replacing `--mode preview` with `--mode apply`. Do not change settings between preview and apply without previewing again.

The command emits JSON containing detected structure, CI, OpenSpec state, candidate checks, partial workflow files, selected settings, create/update/reuse/conflict decisions, and exact target commands.

## Exact generated workflow commands

For an npm target:

```sh
# Plan by selecting an eligible Todo issue
npm run ai:local

# Plan one eligible issue by canonical URL
npm run ai:local -- --issue https://github.com/owner/repository/issues/123

# Review, then explicitly apply in Codex (not a shell command)
$openspec-apply-change <change-id>

# Verify the installed runner
npm run ai:local:test
npm run ai:local:check

# Verify and sync an unambiguous linked change
npm run ai:local -- --sync-task

# Verify and sync one exact linked change
npm run ai:local -- --sync-task --change <change-id>
```

For pnpm, yarn, or bun, replace `npm` with the configured package manager. The generated `docs/ai-local-workflow.md` records the exact commands for that target. Direct Node fallback commands are also in that guide.

## Configuration fields

| Field | Required value |
|---|---|
| `github.repository` | Git remote identity as `owner/name` |
| `github.projectOwner` | User or organization that owns the Project |
| `github.projectNumber` | Positive Projects v2 number |
| `github.statusField` | Exact single-select field name |
| `github.todoOption` | Exact eligible planning option name |
| `github.doneOption` | Exact successful synchronization option name |
| `packageManager` | `npm`, `pnpm`, `yarn`, or `bun` |
| `verification.autoDiscover` | Whether trusted target files add applicable checks |
| `verification.commands` | Required commands as executable plus argv, never shell strings |
| `runtimeDirectory` | Safe repository-relative ignored state directory |

Credentials are never configuration. Use `gh auth login`/`gh auth refresh`; keep provider tokens and Codex credentials outside the repository.

## Acceptance Criteria contract

The runner recognizes Markdown bullets under an Acceptance Criteria heading:

```md
## Acceptance Criteria

- First observable outcome
- Second observable outcome
```

Checkbox bullets are also accepted. No parseable bullets produces `acceptance_criteria_missing`. The bundled issue template establishes the correct shape.

## Verification and status rules

- Required commands execute without a shell. Missing executables, timeouts, skips, nonzero exits, and unavailable command evidence fail closed.
- Strict OpenSpec validation is always required, even when auto-discovery is disabled.
- Semantic verification must cover every issue criterion, normative requirement, scenario, and completed task with concrete evidence.
- Code/worktree, specification, issue, command-definition, and identity fingerprints must remain stable.
- Final Git and GitHub reads must still match the traced repository, branch, Project, item, issue, status field, and options.
- A passing result authorizes one guarded status-field update to Done and a confirmation read. It does not close the issue.

## Conflict handling

The installer plans all destinations before writing. Identical files are reused. It may merge only the three reserved package scripts and the `.ai-local/` ignore line. A different runner, config, guide, issue template, or reserved script is a conflict; preview reports it and apply writes nothing. Reconcile conflicts in the target's approved OpenSpec scope, then preview again.
