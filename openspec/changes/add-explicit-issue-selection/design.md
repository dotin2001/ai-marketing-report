## Context

See `proposal.md` for motivation and `specs/ai-local-explicit-issue-selection/spec.md` for the behavior contract. The current ESM CLI parses planning, synchronization, change, and help arguments in `cli.mjs`. Planning in `workflow.mjs` acquires the repository lock, performs preflight, resolves the configured Project, enumerates every eligible Todo item, prompts through `selector.mjs`, and then executes one shared issue-to-proposal pipeline. Project items already contain the stable issue node ID, issue number, repository identity, URL, status, and Project item identity needed for an explicit match.

The repository has no third-party runtime dependencies. GitHub content is untrusted, runtime linkage is written only after independent proposal validation, and planning is prohibited from applying work or mutating GitHub. These boundaries also govern URL-targeted planning.

## Goals / Non-Goals

**Goals:**

- Add a deterministic URL-targeted planning input without duplicating the proposal pipeline.
- Validate the URL before network access and enforce repository and configured-Project eligibility before issue content is loaded.
- Preserve all existing interactive, traceability, security, validation, and review-stop behavior.
- Produce typed, testable failures for syntax, repository, eligibility, and ambiguity errors.

**Non-Goals:**

- Accept arbitrary GitHub web URLs, shorthand issue numbers, API URLs, issue references from another repository, or non-GitHub hosts.
- Plan issues outside the configured Project or in a status other than the exact configured Todo option.
- Automatically apply the generated change, synchronize status, close the issue, or change branches or Git state.
- Replace or relax the existing interactive planning command.

## Decisions

### 1. Use `--issue <url>` and retain npm's forwarding separator

`parseArguments` will recognize one `--issue` option, require the following token, and return planning options containing the raw URL. Help and documentation will show `npm run ai:local -- --issue <github-issue-url>` because the first standalone `--` belongs to npm argument forwarding; `--issue--` will remain an unknown option.

This follows conventional CLI option syntax and avoids creating a one-off flag that is difficult to document or compose. Accepting both `--issue` and `--issue--` was rejected because aliases increase ambiguity without adding capability.

### 2. Parse a narrow canonical GitHub issue URL before preflight

A small pure helper will use the platform URL parser and enforce HTTPS, hostname `github.com`, no credentials, no non-default port, no query or fragment, and an exact `/owner/repository/issues/positive-decimal` path with at most a trailing slash. It will decode path segments safely, normalize the extracted `owner/repository` for case-insensitive comparison, and return an immutable repository-and-number target. Malformed escaping or any extra segment fails closed.

Generic GitHub URL acceptance followed by best-effort interpretation was rejected because pull-request, API, enterprise-host, query, and redirect forms widen the trust boundary. Directly interpolating a URL into `gh` arguments was rejected because the existing GraphQL identity path is safer and already tested.

### 3. Resolve the target from the complete eligible Project enumeration

Planning will continue to resolve the configured Project and paginate `fetchEligibleItems`. A pure resolver will compare the parsed target with the eligible items' configured repository and issue number, require exactly one match, and return the same selected-item shape currently produced by the interactive selector. Zero matches yields a typed ineligible error; multiple matches yields a typed identity-conflict error.

This deliberately treats Project membership and exact Todo status as eligibility, rather than fetching any issue directly by URL. It preserves the configured Project as the selection boundary, avoids a second issue-resolution query, and retains dynamically resolved status option IDs. A specialized single-item GitHub query was considered but rejected because it could bypass complete enumeration and duplicate status/repository checks.

### 4. Branch only at selection and converge immediately afterward

`runPlanningWorkflow(options, dependencies)` will choose between explicit resolution and `selectIssue(items, ...)`. Both branches produce `{ kind: "selected", item }`, after which the existing live issue fetch, link reuse, proposal generation, validation, persistence, and display logic runs unchanged. The prompt object remains available for stale-lock and linked-change reuse confirmation even when explicit selection bypasses the numbered selector.

Maintaining separate explicit and interactive proposal workflows was rejected because duplicated security and traceability logic would drift. Passing the URL to Codex was also rejected: the Node orchestrator resolves trusted control identity, while Codex receives issue content only through the existing bounded untrusted-data file.

### 5. Keep failures typed and side-effect ordered

Argument and URL-shape errors occur during parsing before configuration, lock, preflight, or GitHub access. Repository mismatch is checked immediately after configuration is loaded and before lock/preflight. Project eligibility and ambiguity failures occur only after read-only preflight and complete Project discovery, but before issue loading, OpenSpec artifact creation, link persistence, or mutation.

Tests will assert exact call ordering and absence of selector, Codex, link writes, and mutation on failure paths. Existing policy-spy coverage remains the final guard against prohibited commands and GraphQL mutations.

## Risks / Trade-offs

- **[Operators omit npm's standalone forwarding separator]** → Show the exact command in help and docs and describe the two distinct `--` tokens involved in npm forwarding versus the `--issue` option.
- **[Strict URL validation rejects harmless copied URL variants]** → Permit only an optional trailing slash and give an actionable canonical-format error; narrow input is preferable to ambiguous identity resolution.
- **[Enumerating all Project items is slower than a direct issue lookup]** → Reuse the already-required paginated eligibility path so repository/status invariants remain centralized and correct.
- **[A matching issue changes status during planning]** → The selection uses a fresh enumeration under the repository lock; planning never mutates status, and later synchronization revalidates live identity and status independently.
- **[Explicit selection is mistaken for automatic implementation]** → Preserve the same final output and documentation stating that proposal generation stops for human review and manual `$openspec-apply-change` invocation.

## Migration Plan

1. Add argument and URL-target parsing tests without changing the default command.
2. Add explicit eligible-item resolution and failure fixtures.
3. Route the explicit option through the existing planning workflow and verify both planning modes converge on identical proposal behavior.
4. Update help and documentation, then run the full suite, syntax checks, help smoke, and strict OpenSpec validation.

Rollback removes the `--issue` parser branch, target helper, explicit selection branch, tests, and documentation. The existing interactive and synchronization commands remain the compatibility baseline, and no persistent data migration is required.
