## 1. Skill Structure and Portable Assets

- [x] 1.1 Initialize `.agents/skills/bootstrap-ai-local/` with valid skill metadata and verify `quick_validate.py` accepts its structure.
- [x] 1.2 Bundle a sanitized snapshot of the runner entry point, modules, schema, and tests; verify no source repository identity, Project identifier, or credential-like value remains.
- [x] 1.3 Add generic configuration, documentation, README snippet, and issue-template assets; verify the issue template contains `## Acceptance Criteria` and Markdown bullets.

## 2. Bootstrap Behavior

- [x] 2.1 Implement target inspection for structure, package manager, CI, tests, OpenSpec, and existing workflow files; verify preview output reports each category without writes.
- [x] 2.2 Implement conflict-aware scaffolding and package-script/gitignore integration; verify identical partial files are reused and incompatible files abort before overwrite.
- [x] 2.3 Add target configuration for Project/status settings and argv-based verification commands; verify generated configuration contains no source identities or secrets.
- [x] 2.4 Generate exact preview, planning, apply, verification, and synchronization commands for the target package manager; verify the generated guide and CLI help preserve the manual apply boundary.

## 3. Portable Runner Verification

- [x] 3.1 Extend only the bundled runner for configurable package-manager and verification-command discovery; verify tests cover validation, explicit commands, failed/blocked execution, and unavailable evidence.
- [x] 3.2 Add a disposable-repository validator using mocked integrations; verify planning stops before implementation, failed/blocked checks make zero mutations, and passing verification produces one Done decision.
- [x] 3.3 Run the disposable validation, the bundled full test suite, syntax checks, skill validator, and `openspec validate add-bootstrap-ai-local-skill --strict --json`; record any command not run.
