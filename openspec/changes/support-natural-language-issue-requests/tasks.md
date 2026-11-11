## 1. Resolve Issue Requirements

- [x] 1.1 Update heading detection in `scripts/ai-local/verification.mjs` to recognize Acceptance Criteria ATX headings with zero to three leading spaces while preserving section-level termination and one criterion per list item; verify explicit and indented-heading parser tests pass.
- [x] 1.2 Add deterministic plain-body fallback criteria and distinct fail-closed outcomes for whitespace-only bodies and explicitly malformed criteria sections; verify the fallback retains the complete trimmed request, uses stable source metadata, and never falls back after an explicit heading.

## 2. Preserve Verification Safety

- [x] 2.1 Expand `scripts/ai-local/__tests__/manifest.test.mjs` for explicit criteria precedence, CommonMark indentation, a natural-language-only request, an empty body, and a malformed explicit section; verify manifest entry counts, text, identifiers, source lines, and error codes.
- [x] 2.2 Add synchronization coverage showing a natural-language request reaches semantic verification and that failed semantic evidence for its fallback criterion prevents the Project mutation; verify the focused sync workflow test passes.
- [x] 2.3 Add or update command-discovery coverage proving commands embedded in a plain issue request remain untrusted and are never executed; verify the focused check-discovery test passes.

## 3. Update User Guidance

- [x] 3.1 Update `docs/ai-local-workflow.md` and concise README guidance so explicit Acceptance Criteria are recommended for granular verification but are not mandatory when the issue has a non-empty request body; document empty-body and malformed-explicit-section failures and verify documented CLI commands remain unchanged.

## 4. Verify the Change

- [x] 4.1 Run `node --test scripts/ai-local/__tests__/manifest.test.mjs scripts/ai-local/__tests__/sync-workflow.test.mjs scripts/ai-local/__tests__/check-discovery.test.mjs` and verify all focused regressions pass without GitHub access or mutation.
- [x] 4.2 Run `npm test` and verify the complete local workflow suite passes without external state changes.
- [x] 4.3 Run `openspec validate support-natural-language-issue-requests --strict` and `git diff --check -- scripts/ai-local/verification.mjs scripts/ai-local/__tests__ docs/ai-local-workflow.md README.md openspec/changes/support-natural-language-issue-requests`; verify strict validation and whitespace checks pass and review the diff for scope.
