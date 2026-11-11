## Why

Synchronization currently rejects a non-empty GitHub issue unless its author used a specifically formatted Acceptance Criteria heading and Markdown bullets. Customers should be able to submit an ordinary natural-language task request while the workflow still retains an independent, fail-closed completion contract.

## What Changes

- Prefer explicit issue Acceptance Criteria when a parseable section is present, preserving one verification criterion per bullet.
- When no Acceptance Criteria heading is present, deterministically treat the non-empty issue body as one issue-request verification criterion without editing the GitHub issue or asking AI to invent requirements.
- Continue to reject an empty or whitespace-only issue body, and reject an explicitly present but malformed or empty Acceptance Criteria section rather than silently falling back.
- Accept CommonMark-compatible ATX headings indented by up to three spaces so valid Markdown formatting is not rejected.
- Keep all existing semantic evidence, required-check, fingerprint, and guarded Todo-to-Done gates unchanged.
- Update tests and workflow documentation to describe explicit criteria as recommended but optional for non-empty issue requests.

## Capabilities

### New Capabilities

- `ai-local-issue-requirements`: Deterministic resolution of issue-level verification criteria from explicit Acceptance Criteria or a non-empty natural-language issue request.

### Modified Capabilities

None.

## Impact

- Affects issue-requirement parsing and verification-manifest construction in `scripts/ai-local/verification.mjs`.
- Adds or updates manifest and synchronization workflow tests under `scripts/ai-local/__tests__/`.
- Updates `docs/ai-local-workflow.md` and related user guidance; no GitHub issue mutation, credential, dependency, Project configuration, or application-runtime change is introduced.
