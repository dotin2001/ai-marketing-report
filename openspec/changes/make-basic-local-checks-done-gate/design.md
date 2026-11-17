## Context

See `proposal.md` for motivation and `specs/ai-local-basic-completion-policy/spec.md` for behavior. `scripts/ai-local.mjs` delegates to `cli.mjs` and `sync-workflow.mjs`. The sync runner currently calls `discoverVerificationChecks`, which gathers commands from configuration, package scripts, trusted documentation, and change tasks and marks all of them required. `reconcileVerification` also requires a passing AI semantic result. `guard.mjs` accepts only a typed passing result, then compares fingerprints and live identity/status before `status-sync.mjs` writes and confirms one Project field. `ai-local.config.json` has execution profiles, but no required/optional sync policy. The bootstrap template mirrors these modules byte for byte.

The existing active specs require broader checks and semantic evidence. Their completion clauses conflict with this requested policy; implementation must reconcile them before changing runtime code. No archived baseline exists under `openspec/specs/`, so this change defines a new capability instead of a partial `MODIFIED` delta against a nonexistent file.

## Goals / Non-Goals

**Goals:** A single repository policy classifies checks for every issue, selected suites run with the right environment, and a deterministic passing result reaches the existing final mutation guard. Failed or unavailable optional checks remain visible in evidence and CLI output.

**Non-Goals:** Changing GitHub issue selection or option names, changing manual OpenSpec apply, removing standalone integration or semantic-verification commands, or proving full product correctness from the basic gate.

## Decisions

### Put the completion policy in shared verification configuration

Extend the validated `verification` configuration with a `syncTask` policy identifying the basic required commands (`git diff --check`, `frontend:test`, `backend:test`) and the optional categories. Strict OpenSpec validation remains mandatory in code so configuration cannot remove it. `git` must be added to the trusted verification executable set for this exact read-only command. Keep current trusted-source discovery and suite applicability; normalize its output against the shared policy rather than letting each issue's task prose turn a live check into a required `Done` gate. Record a stable policy identifier/hash in fingerprints and evidence so a retry from the old gate cannot reuse passing proof.

Alternative considered: hard-code a check list inside `sync-workflow.mjs`. That would duplicate configuration and make future issues drift from the repository policy.

### Make required and optional results first-class

Keep one normalized check plan with `required`, `applicable`, command source, and execution profile. Run applicable required checks; retain any discovered optional check results when they are actually run, and record skipped/unavailable optional checks explicitly. A required result that is not `passed` blocks before any semantic call or GitHub mutation and emits the failing command and reason. Build the `VerifiedSynchronization` token from required results and existing task/artifact validation. Optional semantic review may run for supplementary evidence but is not part of token creation. Preserve the existing strict semantic-result validator for separate/full review paths; optional review failure is reported, not recast as a passing verdict.

Alternative considered: fabricate a passing semantic result when no review runs. That would misstate evidence and corrupt retry records.

### Keep backend unit tests service-free

Use `backend:test` as the required backend script. Its `-m "not postgres and not storage_live"` expression must be parsed as exclusions, not matched as a raw positive `postgres` signal. Preserve `APP_ENV=test` and `AI_LOCAL_DISABLE_DOTENV=1`. Only checks that positively require PostgreSQL receive database preflight; no DB URLs or live storage setup are demanded for the excluded-marker backend command. Explicit positive live checks retain their existing safe preflights when run separately.

Alternative considered: force `backend:test` to a `neutral` profile. That would lose the isolated backend test environment.

### Keep final mutation and retry controls

`sync-workflow.mjs` should still refetch Project/issue state and recompute fingerprints after required verification. `prepareStatusMutation` and `synchronizeProjectStatus` retain exact option-ID checks and post-write confirmation. Evidence should distinguish required and optional results, including optional failures, without allowing them to make overall basic verification fail. The retry path checks the current policy and required-check fingerprint before reusing evidence.

Alternative considered: call `status-sync.mjs` directly after commands. That would bypass the existing identity and race guards.

## Risks / Trade-offs

- [A basic gate can miss integration or semantic defects] → Label the completion level clearly in CLI output and evidence; keep separate full-check commands and report optional outcomes.
- [Trusted task prose may contain live commands] → Preserve discovery for reporting but let the shared policy classify those commands as optional for `Done`.
- [A composite script may hide a live-service dependency] → Expand npm script references before classifying execution profiles and test both excluded and positively selected marker expressions.
- [Old passing evidence could be reused under the new threshold] → Include policy version/hash and required-check list in retry matching, and reject legacy evidence without them.
- [The acceptance example targets a live issue] → Exercise the exact change ID through a dry-run or mocked GitHub client with an asserted zero live mutations.

## Migration Plan

Reconcile the three active OpenSpec completion specs with this approved policy, update configuration/runtime and mirrored bootstrap assets, then update docs and tests. Existing local evidence remains readable but cannot be reused for a new-policy `Done` write. Rollback restores the former policy and runner together; evidence from either policy must not cross the policy boundary.
