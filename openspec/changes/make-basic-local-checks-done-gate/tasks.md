## 1. Align the approved contract

- [x] 1.1 Reconcile the completion-gate clauses in the active `add-ai-local-workflow`, `fix-sync-task-verification-reliability`, and `start-explicit-issue-work-in-progress` specs with this policy; verify all four changes pass strict OpenSpec validation.
- [x] 1.2 Add the repository-wide `syncTask` verification policy to `ai-local.config.json` and its validated schema; verify configuration tests reject missing, malformed, or unsafe command definitions and retain the mandatory strict OpenSpec check.

## 2. Implement the basic gate

- [x] 2.1 Classify trusted discovered checks as required, optional, or inapplicable using the shared policy and existing suite selection; verify discovery tests require `git diff --check` plus only applicable `frontend:test` and `backend:test` commands.
- [x] 2.2 Correct npm-script and pytest-marker profile inference so `backend:test -m "not postgres and not storage_live"` has the isolated backend-test profile without service preflight; verify positive PostgreSQL and live-storage selectors still receive their safety checks in focused tests.
- [x] 2.3 Update the sync runner and deterministic verification token so only passing applicable basic checks and existing task/artifact gates allow final synchronization; verify a failed, missing, skipped, blocked, or timed-out required command names the blocker and produces zero mocked GitHub writes.
- [x] 2.4 Record and report available optional PostgreSQL, migration, storage, and semantic results without gating `Done`; verify mocked sync tests reach `Done` with skipped or failed optional checks and do not fabricate semantic success.
- [x] 2.5 Include policy identity and required-check membership in evidence/fingerprints and retry matching while retaining final live identity/status guard and `Done` confirmation; verify legacy evidence cannot be reused and changed inputs or statuses produce zero mocked GitHub writes.

## 3. Preserve distribution and document verification

- [x] 3.1 Mirror changed runner/config/verification modules in the bootstrap template and update workflow documentation with the exact basic gate and separate expanded-check commands; verify template parity and documentation tests pass.
- [x] 3.2 Add mocked end-to-end coverage for `npm run ai:local -- --sync-task --change gh-6-implement-object-storage-integration`, asserting required-check selection, service-free backend execution, optional-check reporting, and no live GitHub status write; verify the focused regression test passes.
- [x] 3.3 Run focused `scripts/ai-local` regression tests, `npm test`, `npm run check`, strict OpenSpec validation, and `git diff --check`; report exact checks that gate `Done`, all results, and any checks not run.
