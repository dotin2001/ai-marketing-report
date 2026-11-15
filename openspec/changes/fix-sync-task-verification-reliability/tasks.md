## 1. Shared check planning and configuration

- [x] 1.1 Extend trusted ai-local configuration with validated backend-test and PostgreSQL execution-profile metadata, rejecting malformed, conflicting, or credential-bearing profile values; verify configuration tests cover valid neutral/backend/PostgreSQL profiles and every rejection path.
- [x] 1.2 Normalize every discovered required command into a shared check plan, resolve transitive npm-script references, apply explicit configuration overrides for ambiguous commands, and verify tests use different issue/change/check fixtures without any issue number, change ID, or branch hardcoded in runtime logic.
- [x] 1.3 Include resolved execution profiles and applicability metadata in required-check fingerprints and reusable evidence decisions; verify profile or script-graph changes invalidate evidence while identical plans remain reusable.

## 2. Backend test environment and dotenv isolation

- [x] 2.1 Add one child-environment builder used by the required-check executor so backend-test profiles override `APP_ENV=test` and set the test-only dotenv-disable signal while neutral checks and the parent environment remain unchanged; verify executor tests inspect the exact environment passed to each subprocess.
- [x] 2.2 Make backend Settings disable dotenv only when both the explicit workflow signal and `APP_ENV=test` are present, preserving ordinary startup loading otherwise; verify backend configuration tests prove deliberate unsets remain missing in test mode and `.env` still loads in the normal application path.
- [x] 2.3 Add a regression for a caller with `APP_ENV=local` and an existing `backend/.env`, proving applicable backend checks run as tests without moving or modifying the dotenv file.

## 3. Conditional PostgreSQL preflight and diagnostics

- [x] 3.1 Implement a shared, credential-safe validator for `TEST_DATABASE_URL` and `MIGRATION_DATABASE_URL` that rejects missing values, literal or decoded whitespace, unsupported syntax, unapproved hosts, non-test targets, equality with `DATABASE_URL`, and mismatched migration/test targets; verify table-driven tests assert variable-specific messages never contain usernames, passwords, or full URLs.
- [x] 3.2 Implement the harmless PostgreSQL connectivity probe and stable classifications for permission denial, unreachable service, server access denial, invalid preflight, and unknown infrastructure failure; verify deterministic adapter tests cover each category and bounded redaction.
- [x] 3.3 Run PostgreSQL preflight only when at least one selected check has the PostgreSQL profile, reuse one passing preflight across applicable checks, and emit blocked check evidence on preflight failure; verify a non-PostgreSQL issue succeeds without either database variable.
- [x] 3.4 Preserve `failed` for a required command that executes after successful preflight but returns a test failure, distinct from blocked infrastructure; verify check-executor and evidence tests cover the command, reason code, exit status, and zero Project mutations.

## 4. Terminal semantic verification protocol

- [x] 4.1 Version the semantic output schema with distinct progress and terminal message types, reconcile the Codex event stream with the last-message artifact, and accept exactly one terminal result; verify tests cover progress followed by final, progress-only completion, empty output, malformed output, and duplicate final results.
- [x] 4.2 Report `semantic_final_result_missing` when no terminal result exists and retain progress only as bounded diagnostics; verify the issue 5 progress-only event shape no longer becomes a manifest-coverage error.
- [x] 4.3 Validate the terminal result against the current invocation's manifest and surface the complete deterministic list of missing IDs while preserving rejection of unknown/duplicate IDs, duplicate command evidence, missing evidence, non-passing command references, unsupported not-applicable verdicts, and global/per-entry inconsistencies.

## 5. Full CLI and Project synchronization regressions

- [x] 5.1 Add at least two fixture repositories that enter through the real CLI `main`: one non-PostgreSQL issue/change and one PostgreSQL issue/change, each with distinct issue number, change ID, branch, traceability, manifest entries, and required checks; mock GitHub and Codex boundaries while exercising real selection, planning, execution-profile, reconciliation, guard, and evidence code.
- [x] 5.2 Cover the reported failures across the CLI fixtures: caller-local `APP_ENV`, dotenv backfill, missing and embedded-newline database URLs, unsafe targets, PostgreSQL permission denial, unreachable service, an executed assertion failure, semantic progress without a final result, and omitted current-manifest IDs; verify every failed or blocked case makes zero GitHub mutations.
- [x] 5.3 Add a fully passing Todo fixture and assert exactly one configured status-field update, one confirming Done read, unchanged unrelated items, and no issue-close operation.
- [x] 5.4 Rerun a passing fixture with the live item already Done and assert idempotent success, zero status mutations, fresh identity/fingerprint/status reads, and an open issue.
- [x] 5.5 Use the completed issue 5 evidence and event data only as read-only regression input or an identity-free derived fixture, assert its root failures map to the new diagnostics, and verify no test addresses its live Project item or changes its link/evidence files.

## 6. Distributed workflow parity and documentation

- [x] 6.1 Apply the shared runner/helper, semantic protocol, configuration contract, and regression coverage to every supported repository CLI form, and mirror applicable runtime changes into the bootstrap skill's distributable template; verify parity tests prevent the root and template workflow modules from drifting.
- [x] 6.2 Update `docs/ai-local-workflow.md` and related command assertions with the exact future-issue command `npm run ai:local -- --sync-task --change <change-id>`, backend test-mode behavior, conditional PostgreSQL requirements, safe URL rules, and permission/unreachable/assertion diagnostics.
- [x] 6.3 Document the PostgreSQL test configuration using secret-free placeholders for `APP_ENV=test`, `TEST_DATABASE_URL`, and `MIGRATION_DATABASE_URL`, and verify documentation tests confirm database variables are not required for non-PostgreSQL checks.

## 7. Verification and handoff

- [x] 7.1 Run `npm test` and `npm run check`; verify the complete ai-local suite, both CLI fixtures, mutation-count assertions, redaction checks, and bootstrap parity checks pass.
- [x] 7.2 Run `npm run backend:check` with the workflow's test environment behavior and verify backend configuration, dotenv isolation, and non-database tests pass without modifying `backend/.env`.
- [x] 7.3 With an approved isolated local test database, run `npm run database:check` using validated test and migration URLs; if platform access is unavailable, capture and report the stable permission-denied or unreachable blocked reason and do not claim the live integration passed.
- [x] 7.4 Run `openspec validate fix-sync-task-verification-reliability --strict --json`, review the final worktree and evidence for credentials or issue-specific constants, and confirm the completed issue's GitHub Project state and issue-open state were never mutated by this change.
