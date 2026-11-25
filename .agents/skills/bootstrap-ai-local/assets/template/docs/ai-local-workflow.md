# Local AI Planning and Project Synchronization

This repository uses a local workflow that turns one eligible GitHub Projects v2 `{{TODO_OPTION}}` issue into a reviewed OpenSpec proposal. Numbered and URL-targeted planning confirm `{{IN_PROGRESS_OPTION}}` before proposal generation. After explicit implementation plus the shared basic local checks, synchronization changes only that Project item to `{{DONE_OPTION}}`.

## Configuration and prerequisites

Target settings live in `ai-local.config.json`. The file contains no credentials or GitHub node IDs. Authentication stays in `gh auth`; install Node.js 22+, Git, {{PACKAGE_MANAGER}}, GitHub CLI (`gh`), Codex CLI, and OpenSpec CLI.

```sh
gh auth login -h github.com
gh auth refresh -h github.com -s repo,read:project,project
gh auth status
```

The configured repository is `{{REPOSITORY}}`, Project owner/number is `{{PROJECT_OWNER}}#{{PROJECT_NUMBER}}`, status field is `{{STATUS_FIELD}}`, and exact transition options are `{{TODO_OPTION}}`, `{{IN_PROGRESS_OPTION}}`, and `{{DONE_OPTION}}`. The repository-wide `verification.syncTask` policy defines the basic `Done` gate; explicit argv arrays under `verification.commands`, trusted package scripts, and repository instructions remain discoverable for expanded verification. Each ambiguous command can receive a `neutral`, `backend-test`, or `postgresql` profile through trusted configuration.

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

The standalone `--` tells {{PACKAGE_MANAGER}} to forward the runner option. The URL must be `https://github.com/<owner>/<repository>/issues/<positive-number>` with no credentials, port, query, or fragment, and it must match the configured repository. The issue must resolve to exactly one configured-Project item in exact `{{TODO_OPTION}}` or `{{IN_PROGRESS_OPTION}}` status.

Both planning paths fetch the issue and paginated comments as untrusted data, retain duplicate-link detection, invoke the literal `$openspec-propose` skill, independently validate the artifacts and traceability, and stop for review. Choosing a number re-reads that item's live identity and status and moves only the selected `{{TODO_OPTION}}` item to `{{IN_PROGRESS_OPTION}}` before proposal generation. The URL-targeted path makes the same guarded transition; a retry already in progress skips the write. Cancellation and declined linked-change reuse leave status unchanged, and a failed update stops proposal generation. If numbered planning fails after a confirmed start, retry the same issue with its canonical `--issue` URL without another write. Neither path implements, applies, closes the issue, switches branches, commits, pushes, merges, or deploys.

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

Before synchronization, complete every approved OpenSpec task. Synchronization runs strict OpenSpec validation, `git diff --check`, and applicable `frontend:test` and `backend:test` scripts. Other discovered commands are optional for `Done` and remain separately runnable.

The linked issue must contain a parseable section in this form:

```md
## Acceptance Criteria

- First observable outcome
- Second observable outcome
```

When the heading is absent, the complete non-empty issue body becomes one optional semantic-review criterion; a malformed explicit section still fails closed. A failed, missing, skipped, timed-out, or unavailable required basic check produces failed or blocked evidence and cannot move the item to `{{DONE_OPTION}}`. Backend-test profiles run in a child environment with `APP_ENV=test` and a test-only dotenv-disable signal; the parent environment and dotenv files remain unchanged. The service-free backend script's negated `postgres` and `storage_live` markers require no PostgreSQL or object-storage setup. Set `AI_LOCAL_RUN_OPTIONAL_SEMANTIC=1` to report an AI review result during synchronization; its failure does not block `Done`.

PostgreSQL variables are unnecessary for the basic sync gate. For a separately run PostgreSQL check, use secret environment values with approved local hosts and matching isolated `_test` targets:

```sh
APP_ENV=test \
TEST_DATABASE_URL='postgresql+psycopg://<test-role>:<test-password>@localhost:5432/<isolated-name>_test' \
MIGRATION_DATABASE_URL='postgresql+psycopg://<migration-role>:<migration-password>@localhost:5432/<isolated-name>_test' \
{{PACKAGE_MANAGER}} run database:check
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

Only after tasks, the basic required commands, fingerprints, and final live identity/status checks all pass can the guarded mutation set the selected item's `{{STATUS_FIELD}}` field from exact `{{TODO_OPTION}}` or `{{IN_PROGRESS_OPTION}}` to exact `{{DONE_OPTION}}`. Optional live-service and semantic results are reported when available. The issue remains open.

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
