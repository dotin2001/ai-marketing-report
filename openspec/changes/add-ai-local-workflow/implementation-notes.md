# Implementation verification notes

Date: 2026-11-10 (Asia/Ho_Chi_Minh)

## Completed verification

- `npm test` — exit 0; 169 tests passed, 0 failed, 0 cancelled, 0 skipped, 0 todo.
- `npm run check` — exit 0; syntax checked 60 JavaScript modules.
- `npm run ai:local -- --help` — exit 0; documented planning, synchronization, `--change`, and help forms rendered successfully.
- `openspec validate add-ai-local-workflow --strict --json` — exit 0; 1 change passed, 0 failed, no validation issues.

The full suite includes controlled dependency-injected journey coverage for planning cancellation, validated proposal creation without apply, failed/blocked synchronization with no mutation, successful selected-item Todo-to-Done synchronization, issue-open output, identity/fingerprint races, remote failure evidence, safe retry, lock contention, prohibited process commands, and prohibited GraphQL mutations. These local fixtures do not claim that a live GitHub mutation occurred.

## Structured-output schema correction

Date: 2026-11-11 (Asia/Ho_Chi_Minh)

- Removed the unsupported strict Structured Outputs keyword `uniqueItems` from `commandEvidenceIds` and retained the uniqueness invariant in deterministic local validation.
- Added regression coverage that rejects duplicate command evidence and verifies the Codex output schema omits the unsupported keyword.
- `node --test scripts/ai-local/__tests__/semantic-verification.test.mjs` — exit 0; 10 tests passed.
- `npm test` — exit 0; 172 tests passed, 0 failed, 0 cancelled, 0 skipped, 0 todo.
- `npm run check` — exit 0; syntax checked 60 JavaScript modules.
- `openspec validate add-ai-local-workflow --strict --json` — exit 0; 1 change passed, 0 failed, no validation issues.
- An ephemeral, read-only live `codex exec --output-schema` smoke accepted the corrected schema and returned schema-conformant JSON. It did not run synchronization or mutate GitHub.

## Live read-only preflight blocker

The read-only preflight command was attempted against the configured `dotin2001/ai-marketing-report` Project 2. It stopped before any Project query or mutation because `gh auth status` reported:

```text
The token in default is invalid.
To re-authenticate, run: gh auth login -h github.com
```

After authentication is repaired, rerun the documented read-only preflight and perform the live disposable-item smoke. Do not mark tasks 7.1 or 8.3 complete until the configured Project/field/options/eligible query resolve live and the controlled live Todo-to-Done result confirms that only the intended item changed while its issue remained open.
