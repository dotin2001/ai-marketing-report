## Why

The guarded `ai:local` workflow is currently repository-specific, which makes reproducing its planning, review, verification, and GitHub Project synchronization guarantees in another repository slow and error-prone. A repository-local Codex skill can package the proven runner and guide a target-aware, credential-free bootstrap.

## What Changes

- Add a reusable `bootstrap-ai-local` Codex skill that inspects a target repository before scaffolding an equivalent workflow.
- Bundle a sanitized runner snapshot, tests, issue template, documentation template, and deterministic bootstrap/validation scripts without changing the source repository's existing workflow.
- Configure the target repository, GitHub Project, status field/options, package manager, and required verification commands without embedding credentials or this repository's identities.
- Preserve the explicit planning/review/apply/synchronize boundary and fail-closed verification rules.
- Validate the skill itself and exercise the generated workflow in a disposable repository using mocked GitHub behavior only.

## Capabilities

### New Capabilities

- `bootstrap-ai-local-skill`: Packages and installs a portable, target-aware version of the guarded local AI planning and GitHub Project synchronization workflow.

### Modified Capabilities

None.

## Impact

- Adds files only under `.agents/skills/bootstrap-ai-local/` and this OpenSpec change.
- Introduces no application dependency and does not change `scripts/ai-local/`, `scripts/ai-local.mjs`, `ai-local.config.json`, root package scripts, or current workflow documentation.
- Validation creates only temporary disposable repositories and uses dependency-injected GitHub/Codex/OpenSpec fakes; it performs no live GitHub Project mutation.
