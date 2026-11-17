# Local AI Planning and Project Synchronization

This repository provides a local, fail-closed workflow for turning a GitHub Projects v2 `Todo` issue into a reviewed OpenSpec change. URL-targeted planning first moves the selected item to `In Progress`. Only after implementation is independently verified can synchronization change that item to `Done`.

## Prerequisites and authentication

Install Node.js, npm, Git, GitHub CLI (`gh`), Codex CLI, and OpenSpec CLI. The workflow checks every tool with `--version`, verifies the `origin` remote and current named branch, and runs `gh auth status` before reading a Project.

Authenticate for the configured repository and Project:

```sh
gh auth login -h github.com
gh auth refresh -h github.com -s repo,read:project,project
gh auth status
```

The classic-token scopes shown above cover private repository issue reads, Project discovery, and the final Project field update. A fine-grained token needs equivalent access. Organization Projects can also require organization read permission, SSO authorization, or an organization policy exception. As of 2026-11-10, this checkout's active `dotin2001` credential reports an invalid token; re-run `gh auth login` or `gh auth refresh` before a live workflow.

The default [configuration](../ai-local.config.json) targets `dotin2001/ai-marketing-report`, user-owned Project 2, exact field `Status`, and exact options `Todo`, `In Progress`, and `Done`. Node IDs are always resolved live. For a fork, copy the JSON to another repository-local path, change the explicit identities, and select it for one invocation:

```sh
AI_LOCAL_CONFIG=ai-local.fork.json npm run ai:local -- --help
```

The config path may be absolute, but `runtimeDirectory` must remain a safe repository-relative directory.

## Planning

Run:

```sh
npm run ai:local
```

The CLI acquires the repository lock, lists only exact eligible `Todo` issues from the configured repository, and lets you select or cancel. End-of-input, an empty answer, `q`, `quit`, or `cancel` exits without a proposal or GitHub mutation. Issue bodies and all comments are retained as untrusted data with provenance; they are never interpreted as commands.

When you already know the issue, target it by canonical URL:

```sh
npm run ai:local -- --issue https://github.com/dotin2001/ai-marketing-report/issues/2
```

The standalone `--` tells npm to forward the following `--issue` option to the local CLI. The URL must use HTTPS on `github.com`, have the exact path `/<owner>/<repository>/issues/<positive-number>` with at most a trailing slash, contain no credentials, port, query, or fragment, and name the configured repository. The issue must resolve to exactly one item whose status is the configured exact `Todo` or `In Progress` option in the configured Project. URL-targeted planning retains complete Project pagination, live issue and comment loading, duplicate-link detection, traceability, and validation. After eligibility checks, it moves an exact `Todo` item to `In Progress` and confirms the update before proposal generation. An already `In Progress` retry receives no duplicate write. A cancelled reuse leaves status unchanged; other statuses or a failed update stop before proposal generation. A later proposal failure leaves a confirmed `In Progress` status available for retry.

For a new issue, the CLI invokes Codex with the literal skill request `$openspec-propose`, then independently checks the artifacts, traceability marker, requirements/check definitions, and strict OpenSpec validation. If an active proposal already links the same issue, the CLI offers to reuse it instead of creating a duplicate. Planning stops after reporting validated artifact paths.

Review the proposal, design, specifications, and tasks. Applying the change is a separate, deliberate Codex action—this is a skill invocation, not a shell executable:

```text
$openspec-apply-change <change-id>
```

The local CLI never invokes that skill for you.

## Synchronization

After implementation and task completion, synchronize the only unambiguous active linked change:

```sh
npm run ai:local -- --sync-task
```

Or select one exact link:

```sh
npm run ai:local -- --sync-task --change <change-id>
```

The current issue body must contain a customer request. A Markdown Acceptance Criteria section with bullet or checkbox items is recommended for complex work because each item is verified separately, but it is not required. When no Acceptance Criteria heading exists, the workflow treats the complete trimmed issue body as one issue-level verification criterion. Acceptance Criteria headings may use zero to three leading spaces, matching CommonMark ATX heading indentation.

An empty or whitespace-only issue body stops with `issue_request_missing`. If an Acceptance Criteria heading is present but its section contains no Markdown bullet or checkbox items, synchronization stops with `acceptance_criteria_malformed` instead of weakening the explicit contract into a whole-body fallback. Issue text remains untrusted data in either form and never supplies verification commands.

Every gate below must pass before the sole GitHub mutation is reachable:

1. One local workflow owns the repository lock.
2. Configuration, tools, Git remote, named branch, HEAD, and `gh` authentication are valid.
3. Proposal marker and local link record agree on repository, Project, item, issue, branch, base commit, and change.
4. Fresh GitHub reads confirm the same Project/item/issue linkage and an exact `Todo`, `In Progress`, or idempotent `Done` status.
5. The current issue resolves to explicit Acceptance Criteria or one non-empty natural-language request criterion; proposal, design, specs, and tasks are complete; every required task is checked.
6. Required commands are discovered only from trusted repository instructions/configuration and approved OpenSpec tasks.
7. Strict OpenSpec validation and every applicable required command pass. Failed, missing, skipped, blocked, or timed-out required checks stop synchronization. Commands resolved to the `backend-test` profile run in a child environment with `APP_ENV=test`; the workflow's test-only dotenv signal prevents `backend/.env` from restoring values that a negative configuration test deliberately removes. The caller environment and dotenv file are never modified, and ordinary application startup keeps its normal dotenv behavior.
8. Verification-only Codex structured output covers every criterion, requirement, scenario, and task with concrete evidence; Node reconciles it against actual command results.
9. Identity, worktree, specification/instruction, issue/comment, and required-check fingerprints are unchanged after checks.
10. Immediately before mutation, Git/GitHub identities, linkage, status, field/options, and every fingerprint are read and compared again.
11. Exactly one `updateProjectV2ItemFieldValue` sets the selected item's `Status` from `Todo` or `In Progress` to the freshly resolved `Done` option, followed by a confirming read.

The issue remains open. A status other than exact `Todo`, `In Progress`, or `Done` is a conflict. An already-`Done` item exits successfully without a duplicate write.

### Conditional PostgreSQL checks

PostgreSQL settings are required only when the current invocation's resolved check plan contains a `postgresql` profile. A non-PostgreSQL issue does not need either database variable and performs no connectivity probe. For an applicable local database check, use an isolated database whose decoded name ends in `_test` and an explicitly approved local host:

```sh
APP_ENV=test \
TEST_DATABASE_URL='postgresql+psycopg://<test-role>:<test-password>@localhost:5432/<isolated-name>_test' \
MIGRATION_DATABASE_URL='postgresql+psycopg://<migration-role>:<migration-password>@localhost:5432/<isolated-name>_test' \
npm run ai:local -- --sync-task --change <change-id>
```

The values must use supported PostgreSQL URL syntax, contain no literal or decoded whitespace, target an approved test host, and identify the same isolated test server and database. They must not equal `DATABASE_URL`; test and migration roles may differ. Keep real values in the environment only—configuration metadata and documentation must never contain credentials or complete URLs.

Preflight failures are stable and secret-free: `postgres_permission_denied` means the local process or sandbox could not open the connection, `postgres_unreachable` means the service refused or timed out, `postgres_access_denied` means the server rejected the role or database, and `postgres_preflight_invalid` means the settings failed validation. Once preflight passes, a nonzero test process is an executed `test_assertion_failed`, not an infrastructure block.

Semantic-verifier progress is diagnostic only. The verifier must emit exactly one versioned terminal result; completing after progress alone reports `semantic_final_result_missing`. Manifest coverage diagnostics list every omitted ID from the current invocation.

## Evidence, retry, and redaction

`.ai-local/` is Git-ignored and owner-restricted:

```text
.ai-local/
  links/<change-id>.json
  evidence/<change-id>/<timestamp>-<attempt-id>.json
  events/<attempt-id>*.jsonl
  locks/repository.lock/
  tmp/
```

Evidence is schema-versioned, append-only, and atomically published. It contains identities, criterion verdicts, bounded command results, fingerprints, tool versions, and synchronization outcome—not raw issue bodies/comments or unrestricted prompts.

Redaction removes common credentials and known secrets before display or persistence, and output is bounded. Redaction is defense in depth, not a guarantee against arbitrary secrets embedded in free-form output: do not paste credentials into issues, comments, commands, filenames, or test output. Temporary context and structured verification inputs are mode `0600` and removed after their owning child exits.

If verification passes but GitHub mutation/confirmation fails, retry the same synchronization command. Passing evidence is reused only when all identities and all fingerprints match exactly and the prior synchronization state is `failed`; the CLI still repeats the final live reads. Any code, spec, instruction, issue/comment, branch, identity, tool/check definition, or relevant worktree change forces full verification. Old failed attempts remain available for diagnosis.

## Lock recovery and failure handling

The atomic lock stores PID, hostname, owner ID, mode, and start time. A live same-host or any remote-host lock is never removed. If the owning PID is dead on the same host, planning asks for explicit confirmation before recovering the stale lock. Do not manually delete a lock until you have confirmed no workflow process owns it; ownership is rechecked during release so one process cannot remove another's lock.

Authentication failures happen before Project reads or writes. Repair them with the commands in the prerequisites section and rerun. A start-status failure stops before proposal generation and reports a safe retry instruction; a retry re-reads the Project item first. Completion-verification failures leave `Todo` or `In Progress` unchanged. A GitHub failure after passing verification retains retryable evidence. The workflow never commits, pushes, merges, rebases, switches branches, deploys, destructively cleans the worktree, closes an issue, or updates another Project item.

## Command reference

```text
npm run ai:local
npm run ai:local -- --issue <github-issue-url>
npm run ai:local -- --sync-task
npm run ai:local -- --sync-task --change <change-id>
npm run ai:local -- --help
npm test
npm run check
openspec validate add-ai-local-workflow --strict --json
```
