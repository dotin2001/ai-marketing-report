## Why

The planning workflow currently requires interactive selection from the configured Project even when the operator already knows the exact GitHub issue to plan. A URL-targeted entry point will make scripted and repeatable planning faster while preserving the existing Project, repository, traceability, and review safety boundaries.

## What Changes

- Add `npm run ai:local -- --issue <github-issue-url>` as an explicit planning form alongside the existing interactive `npm run ai:local` command.
- Parse and validate one canonical GitHub issue URL, require it to belong to the configured repository, and resolve it to exactly one eligible `Todo` item in the configured Project.
- Bypass only the numbered selector when `--issue` is supplied; retain preflight, locking, live issue/comment loading, untrusted-content handling, duplicate-link detection, deterministic change identity, `$openspec-propose` invocation, strict validation, traceability persistence, and the stop-for-review boundary.
- Reject malformed URLs, unsupported GitHub hosts or URL shapes, cross-repository issues, missing Project items, non-`Todo` items, deleted/non-issue content, duplicate options, and incompatible argument combinations without creating artifacts or changing GitHub.
- Update CLI help and workflow documentation, and add unit and journey coverage for the explicit-issue path and its failure modes.

## Capabilities

### New Capabilities

- `ai-local-explicit-issue-selection`: Selects one configured-repository GitHub issue by URL for the existing safe OpenSpec proposal workflow.

### Modified Capabilities

None.

## Impact

- Affects the local Node CLI argument parser, planning orchestration, Project-item resolution helpers, tests, help text, and workflow documentation.
- Reuses the existing GitHub CLI authentication, configured Project boundary, Codex planning adapter, OpenSpec validation, runtime lock, and traceability formats.
- Adds no dependency, application feature, automatic apply step, issue mutation, Project mutation, branch operation, or Git publishing behavior.
