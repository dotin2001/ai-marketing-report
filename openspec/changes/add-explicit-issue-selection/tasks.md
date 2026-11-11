## 1. CLI and URL Input Contract

- [x] 1.1 Extend `parseArguments` and help output with planning-only `--issue <github-issue-url>` while preserving all existing forms; verify argument tests accept one explicit URL and reject missing, duplicate, help/sync/change combinations, `--issue--`, and unknown options before invoking a workflow.
- [x] 1.2 Implement a pure canonical GitHub issue URL parser that returns immutable repository and positive issue-number identity; verify unit tests cover HTTPS `github.com`, optional trailing slash, case-insensitive configured-repository comparison, and rejection of malformed encoding, credentials, ports, queries, fragments, non-issue paths, extra segments, non-positive numbers, and cross-repository URLs.

## 2. Project Resolution and Planning Integration

- [x] 2.1 Implement explicit target resolution against the complete eligible Project item list, requiring exactly one matching configured-repository Todo issue; verify tests cover one match, zero matches for absent or non-Todo content, and duplicate-match identity conflict without returning a selected item.
- [x] 2.2 Route `runPlanningWorkflow` through explicit resolution when `options.issueUrl` is present and through the existing selector otherwise, converging before the live issue fetch; verify dependency-injected tests prove explicit mode skips only the numbered selector and preserves preflight, Project pagination, issue/comment loading, link detection, proposal generation, validation, and atomic link persistence.
- [x] 2.3 Add planning failure-path coverage proving invalid or cross-repository URLs stop before GitHub access and ineligible or ambiguous Project matches stop before issue loading, Codex, OpenSpec artifact/link writes, or any GitHub mutation; verify the process and GraphQL policy-spy suites remain green.
- [x] 2.4 Add an end-to-end fake CLI journey for `npm run ai:local -- --issue https://github.com/dotin2001/ai-marketing-report/issues/2`; verify it invokes the literal `$openspec-propose` request, produces and validates one traced change, stops for review, and never applies work, changes Project status, closes the issue, switches branches, or publishes Git state.

## 3. Documentation and Verification

- [x] 3.1 Update the detailed workflow guide, README summary, and command reference with the exact npm forwarding syntax, canonical URL rules, configured Project Todo eligibility, retained interactive mode, reuse behavior, and manual `$openspec-apply-change` next step; verify documentation tests and `npm run ai:local -- --help` agree.
- [x] 3.2 Run the narrow argument, URL, Project-resolution, and planning journey tests followed by `npm test`, `npm run check`, `npm run ai:local -- --help`, and `openspec validate add-explicit-issue-selection --strict --json`; record any check that cannot run and do not mark the change implementation complete unless every applicable required check passes.
