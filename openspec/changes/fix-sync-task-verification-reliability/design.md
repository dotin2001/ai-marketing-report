## Context

See `proposal.md` for motivation and `specs/ai-local-sync-task-verification/spec.md` for the required behavior.

The repository has one runtime entry module, `scripts/ai-local.mjs`, reached through the `ai:local` npm script and also executable directly. Argument parsing sends both `--sync-task` forms to `runSynchronizationWorkflow`. That workflow resolves one traceability-linked change, builds a manifest from the live issue plus that change's specs and tasks, discovers trusted commands, executes them, invokes the semantic verifier, rechecks fingerprints and live identities, and reaches the sole GitHub mutation through the final guard. The bootstrap skill contains a distributable copy of this workflow; it is not a second live path in this checkout, but it must remain behaviorally aligned so newly bootstrapped repositories do not reintroduce the defects.

Current check discovery records only a command, arguments, source, rationale, timeout, and required flag. Execution inherits `process.env` unchanged. Consequently a caller's `APP_ENV=local` reaches PostgreSQL tests, while Pydantic Settings can read `backend/.env` from the backend working directory and backfill settings that a negative test intentionally removed. Database URL safety is checked late and separately inside backend fixtures; the workflow cannot reject whitespace-corrupted URLs before a connection or distinguish an operating-system permission denial from an unreachable service. Any nonzero executed command is reported only as `failed`.

Semantic verification writes progress events to a JSONL log but parses only the `--output-last-message` file as a terminal result. The issue 5 event log demonstrates a schema-shaped progress message followed by tool activity and no final agent result; it was misreported as omitted manifest coverage. Coverage validation stores missing IDs in error details, but the CLI prints only the generic message.

The completed issue 5 evidence is read-only regression input. No design or test may call the live mutation for that item, reopen or close its issue, or rewrite its link/evidence history.

## Goals / Non-Goals

**Goals:**

- Represent every discovered command as an issue-independent check plan with an explicit execution profile before fingerprints are computed.
- Make backend test environment handling deterministic without editing, moving, or sourcing a user's dotenv file.
- Fail before a PostgreSQL connection on malformed or unsafe settings and classify infrastructure failures separately from executed test failures.
- Accept exactly one explicit final semantic result for the current manifest while retaining progress as diagnostics.
- Exercise the actual CLI orchestration with multiple distinct issue/change fixtures and mocked remote mutation.
- Preserve every existing synchronization and no-mutation boundary.

**Non-Goals:**

- Changing how issues are selected, proposals are generated, OpenSpec tasks are applied, or completed changes are archived.
- Making PostgreSQL optional for a check that actually requires it, provisioning a database automatically, or weakening backend database safety rules.
- Changing production application settings, database schema, GitHub Project configuration, branch policy, or issue open/closed state.
- Reusing identifiers, manifests, commands, or expected results from issue 5 in general workflow logic.
- Treating semantic verification as a replacement for deterministic required commands.

## Decisions

### 1. Build one normalized check plan in the shared synchronization workflow

After the current change and manifest are resolved, discovery will normalize every required command into a check plan containing its existing evidence fields plus an execution profile. The profile will be derived from trusted repository configuration: direct command metadata, the repository package-script graph, and approved task commands. Npm script references will be expanded transitively for classification, so a top-level aggregate such as `backend:check` inherits the backend and PostgreSQL capabilities of the scripts it invokes. The selected issue only determines which trusted checks enter the plan; it does not provide environment values or executable policy.

Repository configuration will define the recognized backend-test and PostgreSQL capabilities and explicit overrides for commands that cannot be classified safely. A discovered backend/database marker that is ambiguous rather than clearly neutral will fail closed and ask for repository metadata instead of guessing. Neutral checks keep the ordinary subprocess environment. The fully resolved profile becomes part of the required-check fingerprint, so changing classification or environment policy invalidates reusable evidence.

This is preferred over issue-number branches or a fixed list assembled in `sync-workflow.mjs`: those approaches repeat the defect for every later issue. It is also preferred over setting all commands to test mode because frontend, OpenSpec, and general Node checks need no backend-specific environment.

Both supported CLI forms continue to call the same workflow function. The distributable bootstrap copy will receive the same module changes and a parity assertion for files whose behavior must remain identical.

### 2. Construct a child-only backend test environment and add an explicit dotenv-disable signal

For a check with the backend-test profile, the executor will clone the caller environment, override `APP_ENV` to `test`, and set a narrowly named test-only signal that disables Settings dotenv loading. It will not rewrite `backend/.env`, alter the parent process, or manufacture missing application credentials. Backend Settings will honor the signal only when `APP_ENV=test`; without both conditions, its current `.env` behavior remains unchanged. This lets a test's `monkeypatch.delenv(...)` control the process environment without a lower-priority dotenv source restoring the value.

The environment builder will be a shared helper called for every check plan, not a wrapper around only `database:check`. Unit tests will assert the environment passed to the subprocess rather than inspecting or renaming local files.

Alternatives rejected:

- Temporarily moving `backend/.env` is stateful, crash-prone, and unsafe with concurrent tools.
- Requiring operators to export `APP_ENV=test` repeats manual setup and makes results caller-dependent.
- Disabling dotenv permanently would change ordinary application startup and violate the compatibility requirement.

### 3. Preflight PostgreSQL once per applicable plan with credential-free result codes

If no selected check has the PostgreSQL profile, the workflow will neither require nor probe PostgreSQL variables. Otherwise a shared preflight runs before the first PostgreSQL check and receives values only through the child environment.

Structural validation will reject absent values; literal control characters or whitespace; unsupported schemes; missing host or database; unapproved hosts; decoded whitespace in URL components; non-`_test` targets; equality with `DATABASE_URL`; and migration targets that do not resolve to the same approved test server/database as `TEST_DATABASE_URL`. Migration and test roles may have different usernames or credentials. Error messages contain only the variable name and a stable reason code.

After structural validation, a small backend-side probe will connect and execute a harmless query using each required role. It will return a bounded credential-free JSON result. Error mapping will distinguish at least:

- `postgres_permission_denied` for operating-system or sandbox `EPERM`/`EACCES` socket denial;
- `postgres_unreachable` for refusal, timeout, DNS, or absent service;
- `postgres_access_denied` for server authentication, authorization, or database rejection;
- `postgres_preflight_invalid` for a rejected variable/target.

Affected required checks will receive a `blocked` result with the stable code when preflight cannot establish infrastructure. Once preflight passes, a nonzero test process is a `failed` command result (for example `test_assertion_failed`), not an infrastructure block. Evidence and CLI diagnostics will name the command and setting where relevant, use existing bounded redaction, and never store full database URLs.

Using only a TCP port probe was rejected because it cannot validate the target database or credentials. Letting pytest fail first was rejected because it produces misleading stack traces and cannot reliably separate sandbox denial, service absence, and assertion failure.

### 4. Make semantic progress and terminal output different protocol messages

The semantic output protocol will have an explicit discriminator. Progress messages may carry bounded diagnostic text but cannot carry a final verdict. Exactly one message identified as the terminal verification result may contain `schemaVersion`, `overallVerdict`, and results. The Codex event stream and last-message file will be reconciled so a process that exits after progress produces `semantic_final_result_missing`, not a coverage error. Zero or multiple terminal results are invalid.

The final result is then validated against the manifest built in the current run. Coverage errors will include a bounded, deterministic list of all missing manifest IDs in both the user-facing message and evidence details. Existing validation remains: exact known IDs, no duplicates, valid verdicts, concrete evidence for passes, unique command evidence, only actually passed command references, allowed not-applicable results, and consistent aggregate/per-entry/check verdicts.

This explicit protocol is preferred over assuming the last schema-shaped assistant message is final. Prompt wording alone is insufficient because the observed verifier already emitted a schema-shaped progress placeholder.

### 5. Leave the final Project mutation architecture unchanged

The workflow will keep its lock, initial and final preflight, traceability agreement, fresh Project/item/issue reads, check and semantic reconciliation, evidence/retry rules, post-check and pre-mutation fingerprints, typed `VerifiedSynchronization` token, status conflict handling, one GraphQL field mutation, and confirming read. Environment profiles and PostgreSQL preflight results become verification inputs, so they are covered by evidence and fingerprints before the existing guard is reached.

For exact Done status, the final guard returns `already_done` and never calls the mutation adapter. For Todo, only a complete typed verification can call it once. Issue-closing operations remain prohibited by policy and absent from the status mutation.

### 6. Use multi-fixture CLI regression tests and read-only issue 5 evidence

Regression tests will enter through the exported CLI `main` with real argument parsing, candidate resolution, manifest/check planning, environment construction, semantic reconciliation, guards, and evidence handling. GitHub reads/writes, Codex transport, and process boundaries will be deterministic fakes where necessary; mutation calls and payload counts will be asserted.

At least two fixture repositories will use different issue numbers, change IDs, branches, manifests, and required checks:

- a non-PostgreSQL fixture that proves database variables are not required;
- a PostgreSQL fixture modeled on the issue 5 check shape but using fixture-only identities, proving test environment isolation and conditional database preflight.

The matrix will cover caller `APP_ENV=local`, dotenv negative tests, missing and whitespace-corrupted URLs, unsafe targets, permission denial, unreachable service, an assertion failure, progress followed by final output, progress without final output, missing manifest IDs, a fully passing Todo run with one mocked update, a blocked run with zero updates, and an already-Done rerun with zero updates. A regression test may parse the local issue 5 evidence/events to assert the historical failure classification, but it must never invoke GitHub for that live item.

Real PostgreSQL integration checks will run when the approved local test service and safe URLs are available. If the environment denies access, the test report will record the stable blocked reason instead of claiming the integration passed.

## Risks / Trade-offs

- **[Package-script classification can become stale when scripts change]** → Resolve transitive script references on every run, fingerprint the resolved plan, fail closed on ambiguous backend/database markers, and test configuration validation.
- **[A test-only dotenv signal could leak into normal startup]** → Require both the explicit signal and `APP_ENV=test`; add positive tests for test isolation and ordinary dotenv loading.
- **[Database driver exceptions vary by platform]** → Normalize known OS and PostgreSQL categories into stable codes, retain bounded redacted command context, and treat unknown connection failures as blocked rather than assertions.
- **[Semantic protocol changes require verifier prompt/schema coordination]** → Version the protocol, test progress-only and multi-message streams, and reject missing or duplicate final messages explicitly.
- **[The bootstrap template can drift from repository runtime code]** → Update the distributable copy in the same tasks and add parity tests for shared workflow modules and documentation placeholders.
- **[Real PostgreSQL checks may be unavailable in a restricted sandbox]** → Keep deterministic classification tests mandatory and report live integration as blocked with the exact safe reason when access is unavailable.

## Migration Plan

1. Add check-profile configuration validation and normalized plan tests without changing the final mutation path.
2. Add the child environment builder, test-only dotenv signal, and backend configuration tests.
3. Add structural PostgreSQL validation, the safe connectivity probe, stable diagnostic codes, and unit/integration tests.
4. Version the semantic message schema and parser, then add progress/final and manifest-coverage tests.
5. Add the two full CLI fixtures, status-mutation assertions, issue 5 read-only regression fixture, and bootstrap parity checks.
6. Update workflow documentation with the future-issue command and PostgreSQL test configuration, run strict OpenSpec validation, the complete Node suite, backend checks, and live PostgreSQL integration checks when available.

Rollback removes the new execution-profile, preflight, and semantic-protocol code together and restores the prior tests/configuration. It requires no application data or database migration and must not alter existing evidence, link records, issues, or Project states.
