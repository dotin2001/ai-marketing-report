## Context

The current runner is a Node.js ESM CLI with dependency-injected adapters and a Node test suite. Its behavior is distributed across the CLI entry point, GitHub Project discovery, OpenSpec proposal orchestration, traceability, verification/evidence, fingerprinting, and guarded status synchronization. A portable skill must retain those tested boundaries while removing source-repository identities and accommodating a target repository's package manager and check commands.

## Goals / Non-Goals

**Goals:**

- Keep the reusable bundle reviewable as ordinary files rather than requiring access to this repository at invocation time.
- Make installation deterministic, conflict-aware, and safe for partially bootstrapped repositories.
- Preserve the current runner's fail-closed behavior and manual apply boundary.
- Prove the bundle works without network access or live GitHub writes.

**Non-Goals:**

- Publish the skill globally or to a marketplace.
- Authenticate GitHub, create a Project, or infer credentials.
- Automatically invoke `$openspec-apply-change`, implement a proposed change, close an issue, or publish Git state.
- Overwrite incompatible target files.

## Decisions

### 1. Store the skill in the repository-local skills directory

Create `.agents/skills/bootstrap-ai-local/` so the complete portable artifact is versioned with the workflow it derives from and is immediately discoverable in this repository. A user can copy that directory into another repository's `.agents/skills/` or a personal skills directory.

### 2. Bundle a sanitized plain-file template

Bundle the runner modules, schema, and tests as plain files under `assets/template/`. This keeps the implementation auditable and allows the installer to compare target files byte-for-byte. Source repository names, owners, issue URLs, token state, and Project numbers are replaced with neutral fixtures or generated target settings. An opaque archive was rejected because it makes review and selective reuse harder.

### 3. Use one deterministic Node bootstrap script

The script first inspects package metadata, lockfiles, CI files, test scripts, OpenSpec presence, and existing workflow files. It supports a preview mode, then plans all writes before changing anything. Missing files are created, identical files are reused, compatible package scripts are merged, `.ai-local/` is added to `.gitignore`, and incompatible destinations abort the operation before writes. This prevents partial overwrites while allowing an existing compatible workflow to be reused.

### 4. Keep target-specific values in generated configuration

The generated `ai-local.config.json` contains only repository/Project identities, exact status names, package manager choice, safe argv-based verification commands, and the runtime directory. The portable runner extends the source configuration contract only where needed for target package managers and explicit verification commands. Secrets remain owned by `gh auth` and environment-specific tool authentication.

### 5. Generate target-specific documentation and issue template

The bootstrap replaces documented command placeholders with the detected package manager's exact invocation syntax. It installs an issue template whose `## Acceptance Criteria` section contains Markdown bullets, matching the runner parser's contract and explaining the `acceptance_criteria_missing` failure.

### 6. Validate through a disposable mocked repository

A bundled validator creates a temporary Git repository with a minimal OpenSpec setup, runs the bootstrap, syntax checks and the portable Node tests, and runs the focused mocked planning/synchronization journeys. The tests assert planning never applies, failed or blocked verification never invokes the mutation adapter, and passing verification produces one Done decision. No real `gh` command or GraphQL request is made.

## Risks / Trade-offs

- **Bundled code can drift from the source runner** → Record its provenance in the skill reference and keep the portable runner's contract tests in the bundle.
- **Target repositories can contain conflicting partial files** → Abort before writes and report exact conflicts; require deliberate manual reconciliation rather than overwriting.
- **Auto-discovered checks can be incomplete** → Inspect target conventions and require explicit verification command configuration, while retaining trusted-source discovery as defense in depth.
- **Different package managers have different forwarding syntax** → Generate exact commands from a normalized package-manager adapter and keep the direct Node command available for troubleshooting.

## Migration Plan

No migration applies to this repository's existing runner. Rollback consists of removing the new skill directory and this change's artifacts; no application or live GitHub state is affected.
