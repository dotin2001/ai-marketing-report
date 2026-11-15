# Local AI Planning and Project Synchronization

This repository uses a local, fail-closed workflow that turns one eligible GitHub Projects v2 `{{TODO_OPTION}}` issue into a reviewed OpenSpec proposal and, after explicit implementation plus independent verification, changes only that Project item to `{{DONE_OPTION}}`.

## Configuration and prerequisites

Target settings live in `ai-local.config.json`. The file contains no credentials or GitHub node IDs. Authentication stays in `gh auth`; install Node.js 22+, Git, {{PACKAGE_MANAGER}}, GitHub CLI (`gh`), Codex CLI, and OpenSpec CLI.

```sh
gh auth login -h github.com
gh auth refresh -h github.com -s repo,read:project,project
gh auth status
```

The configured repository is `{{REPOSITORY}}`, Project owner/number is `{{PROJECT_OWNER}}#{{PROJECT_NUMBER}}`, status field is `{{STATUS_FIELD}}`, and exact transition options are `{{TODO_OPTION}}` to `{{DONE_OPTION}}`. Required verification commands are explicit argv arrays under `verification.commands`; trusted package scripts and repository instructions are also discovered when `verification.autoDiscover` is true. Each ambiguous command can receive a `neutral`, `backend-test`, or `postgresql` profile through trusted configuration.

## Preview and scaffold

Inspect only:

```sh
node {{BOOTSTRAP_SCRIPT}} --mode inspect --target .
```

Preview this exact scaffold without writing:

```sh
{{PREVIEW_COMMAND}}
```

Apply the same scaffold by changing `--mode preview` to `--mode apply`.

## Plan

Interactive selection:

```sh
{{RUN_COMMAND}}
```

Select one canonical issue URL:

```sh
{{RUN_COMMAND}} -- --issue <github-issue-url>
```

Show CLI help through the package script:

```sh
{{RUN_COMMAND}} -- --help
```

The standalone `--` tells {{PACKAGE_MANAGER}} to forward the runner option. The URL must be `https://github.com/<owner>/<repository>/issues/<positive-number>` with no credentials, port, query, or fragment, and it must match the configured repository. The issue must resolve to exactly one configured-Project item in the exact `{{TODO_OPTION}}` option.

Both planning paths fetch the issue and paginated comments as untrusted data, retain duplicate-link detection, invoke the literal `$openspec-propose` skill, independently validate the artifacts and traceability, and stop. They never implement, apply, close the issue, change Project status, switch branches, commit, push, merge, or deploy.

## Apply explicitly

Review `proposal.md`, `design.md`, delta specifications, and `tasks.md`. Then invoke the apply skill deliberately in Codex:

```text
$openspec-apply-change <change-id>
```

This is a Codex skill invocation, not a shell executable, and is never called by `ai:local` planning.

## Verify the installed runner

```sh
{{PACKAGE_MANAGER}} run ai:local:test
{{PACKAGE_MANAGER}} run ai:local:check
node scripts/ai-local.mjs --help
```

Before synchronization, complete every approved OpenSpec task and run the configured application checks. Synchronization independently runs strict OpenSpec validation, every explicit verification command, and applicable checks discovered from trusted repository files.

The linked issue must contain a parseable section in this form:

```md
## Acceptance Criteria

- First observable outcome
- Second observable outcome
```

When the heading is absent, the complete non-empty issue body becomes one criterion; a malformed explicit section still fails closed. A failed, missing, skipped, timed-out, or unavailable required check produces failed or blocked evidence and cannot move the item to `{{DONE_OPTION}}`. Backend-test profiles run in a child environment with `APP_ENV=test` and a test-only dotenv-disable signal; the parent environment and dotenv files remain unchanged. Missing semantic evidence, progress without exactly one terminal result, or a failed Codex verification also fails closed.

PostgreSQL variables are conditional: a non-PostgreSQL check plan needs neither variable and performs no probe. For a PostgreSQL profile, use secret environment values with approved local hosts and matching isolated `_test` targets:

```sh
APP_ENV=test \
TEST_DATABASE_URL='postgresql+psycopg://<test-role>:<test-password>@localhost:5432/<isolated-name>_test' \
MIGRATION_DATABASE_URL='postgresql+psycopg://<migration-role>:<migration-password>@localhost:5432/<isolated-name>_test' \
{{RUN_COMMAND}} -- --sync-task --change <change-id>
```

Malformed or unsafe URLs report `postgres_preflight_invalid`; socket permission denial reports `postgres_permission_denied`; a refused or timed-out service reports `postgres_unreachable`; server rejection reports `postgres_access_denied`. A command that runs after a successful preflight but fails an assertion reports `test_assertion_failed`.

## Sync

Synchronize the sole unambiguous linked change:

```sh
{{RUN_COMMAND}} -- --sync-task
```

Or select one change explicitly:

```sh
{{RUN_COMMAND}} -- --sync-task --change <change-id>
```

Only after tasks, acceptance criteria, required commands, semantic evidence, fingerprints, and final live identity/status checks all pass can the guarded mutation set the selected item's `{{STATUS_FIELD}}` field from exact `{{TODO_OPTION}}` to exact `{{DONE_OPTION}}`. The issue remains open.

Runtime links, evidence, bounded redacted events, locks, and temporary files stay under ignored `.ai-local/`. If GitHub synchronization fails after passing verification, retrying may reuse evidence only when every identity and fingerprint still matches.

## Direct Node fallback

These commands bypass package-manager forwarding while preserving identical behavior:

```sh
node scripts/ai-local.mjs
node scripts/ai-local.mjs --issue <github-issue-url>
node scripts/ai-local.mjs --sync-task
node scripts/ai-local.mjs --sync-task --change <change-id>
node scripts/ai-local.mjs --help
```
