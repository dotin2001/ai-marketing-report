## Purpose

Allow an operator to target one known GitHub issue by URL while retaining the local planning workflow's configured Project boundary, proposal safeguards, and review stop.

## ADDED Requirements

### Requirement: Explicit issue URL is a supported planning input
The workflow SHALL support `npm run ai:local -- --issue <github-issue-url>` as a planning command. The `--issue` option SHALL accept exactly one value and SHALL be incompatible with synchronization, change selection, help, duplicate `--issue` options, missing values, and unknown options. Running `npm run ai:local` without `--issue` SHALL retain the existing interactive planning behavior.

#### Scenario: Explicit URL planning is requested
- **WHEN** the operator supplies one valid value with `--issue` and no incompatible option
- **THEN** the workflow enters planning mode with that URL as its explicit issue target

#### Scenario: Interactive planning remains available
- **WHEN** the operator runs `npm run ai:local` without planning options
- **THEN** the workflow continues to enumerate eligible items and offer the numbered selector

#### Scenario: Arguments are invalid or incompatible
- **WHEN** `--issue` is missing a value, repeated, combined with `--sync-task`, `--change`, or help, or accompanied by an unknown option
- **THEN** the workflow exits with an actionable usage error before preflight, proposal generation, runtime linkage, or GitHub mutation

### Requirement: Explicit issue URL is canonical and repository-scoped
The workflow SHALL accept only an HTTPS `github.com` issue URL whose path identifies one repository and one positive decimal issue number. It SHALL reject credentials, non-default ports, query strings, fragments, non-issue paths, extra path segments, malformed encoding, and repository identities that do not match the configured repository. Repository comparison SHALL be case-insensitive while the configured repository remains the authoritative identity.

#### Scenario: Canonical configured-repository URL is accepted
- **WHEN** the URL has the form `https://github.com/<owner>/<repository>/issues/<positive-number>` and its repository matches configuration
- **THEN** the workflow extracts the configured repository identity and issue number for live resolution

#### Scenario: URL shape or authority is unsafe
- **WHEN** the value is malformed, is not HTTPS, is not hosted by `github.com`, contains credentials, a non-default port, query or fragment data, a non-positive issue number, or a path other than one issue path
- **THEN** the workflow exits with a typed validation error and performs no GitHub read or write

#### Scenario: URL targets another repository
- **WHEN** a valid GitHub issue URL names a repository other than the configured repository
- **THEN** the workflow reports both configured and supplied repository identities and stops before proposal generation or GitHub mutation

### Requirement: Explicit issue resolves through the configured Todo Project boundary
After normal preflight and dynamic Project discovery, the workflow SHALL resolve the supplied repository and issue number to exactly one eligible item from the complete configured Project enumeration. The item SHALL be an Issue in the configured repository with status exactly the configured Todo option. The workflow SHALL not plan a URL that is absent from the Project, linked to non-issue content, in another status, or otherwise ineligible.

#### Scenario: One matching Todo item exists
- **WHEN** complete Project enumeration contains exactly one eligible Todo issue matching the supplied repository and issue number
- **THEN** the workflow selects that Project item without displaying the numbered issue selector

#### Scenario: Matching issue is not eligible
- **WHEN** no eligible item matches because the issue is absent, deleted, not an Issue, belongs to another repository, lacks the configured status, or is not exactly Todo
- **THEN** the workflow reports that the explicit issue is not eligible and creates no proposal or runtime link

#### Scenario: Matching item is ambiguous
- **WHEN** more than one eligible Project item matches the same explicit issue identity
- **THEN** the workflow reports an identity conflict and stops without selecting an item or changing state

### Requirement: Explicit selection preserves the complete safe proposal workflow
After resolving the item, the workflow SHALL use the same live issue and paginated-comment fetch, untrusted-data boundary, linked-change detection, reuse confirmation, deterministic change identifier, traceability identities, `$openspec-propose` Codex invocation, artifact checks, strict OpenSpec validation, and local link persistence used by interactive planning. It SHALL stop for review without applying the change or mutating GitHub.

#### Scenario: New explicit issue proposal succeeds
- **WHEN** the explicit issue is eligible, has no linked change, Codex completes proposal generation, and independent artifact and strict validation pass
- **THEN** the workflow records linkage, reports the validated change and artifacts, and instructs the operator to review and manually apply it

#### Scenario: Explicit issue already has a linked change
- **WHEN** the selected issue has exactly one consistent active link
- **THEN** the workflow offers the existing reuse decision and does not silently create a duplicate proposal

#### Scenario: Proposal generation or validation fails
- **WHEN** Codex fails or the generated artifacts, traceability, requirements, tasks, or strict validation are invalid
- **THEN** the workflow reports failure, persists no new link, leaves GitHub unchanged, and does not invoke the apply workflow

### Requirement: Help and documentation expose the exact command boundary
CLI help and repository documentation SHALL show `npm run ai:local -- --issue <github-issue-url>`, explain that the standalone `--` forwards the option through npm, distinguish URL-targeted planning from interactive planning and synchronization, and state that both planning forms stop before implementation.

#### Scenario: Operator checks help or documentation
- **WHEN** the operator views `npm run ai:local -- --help` or the local workflow guide
- **THEN** the exact explicit-issue command, validation boundary, Project eligibility rule, and manual apply next step are visible
