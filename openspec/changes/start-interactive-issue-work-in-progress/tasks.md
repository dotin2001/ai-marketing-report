## 1. Guarded interactive start

- [x] 1.1 Route numbered issue selection through the existing live `Todo` to `In Progress` guard before new proposal generation; verify a mocked interactive success writes only the selected item once and confirms the status before Codex runs.
- [x] 1.2 Apply selected-item/link identity checks and the same guarded start to accepted linked-change reuse; verify cancelled selection, declined reuse, stale linkage/status, failed mutation, and failed confirmation perform no proposal work or new-link persistence.
- [x] 1.3 Verify proposal failure after confirmed start leaves `In Progress` without a new link, and a canonical `--issue` retry continues without a duplicate status write in mocked workflow tests.

## 2. Operator and bootstrap consistency

- [x] 2.1 Update CLI help, `README.md`, and `docs/ai-local-workflow.md` for interactive start, cancellation, and URL retry; verify documentation contract tests and command examples.
- [x] 2.2 Mirror runner and guidance changes in `.agents/skills/bootstrap-ai-local/assets/template/`; verify byte-parity tests and disposable bootstrap validation without a live GitHub mutation.

## 3. Verification

- [x] 3.1 Run focused planning, selector, status, and documentation Node tests; resolve failures and record exact results (37 passed).
- [x] 3.2 Run `npm test`, `npm run check`, `git diff --check`, and `openspec validate start-interactive-issue-work-in-progress --strict --json`; record exact outcomes and any unavailable gate before handoff.

## Verification record

- Focused planning, selector, status, documentation, and template-parity tests: 37 passed.
- `npm test`: 295 passed, 0 failed.
- `npm run check`: syntax checked 67 modules.
- Disposable bootstrap validation: passed; 35 test files, 66 modules syntax checked, 0 live GitHub calls.
- `git diff --check`: passed.
- Strict OpenSpec validation: valid with zero issues.
- Live GitHub Project mutation was not run; mocked tests verify the selected-item write and confirmation.
