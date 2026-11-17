## Context

See `proposal.md` for motivation. `package.json` runs `scripts/ai-local.mjs`, which delegates to `cli.mjs` and `workflow.mjs`. The explicit path currently parses a canonical URL, loads only `Todo` items from `project.mjs`, resolves one item, fetches the issue, checks linked changes, then invokes Codex or validates a reused proposal. `status-sync.mjs` already owns a Project item read, the `updateProjectV2ItemFieldValue` mutation, and a confirming read; `guard.mjs` permits `Todo` to `Done` only after complete synchronization verification. `ai-local.config.json` names `Todo` and `Done` but has no `In Progress` option. The bundled bootstrap template mirrors these files and tests.

The earlier planning and explicit-selection specs forbid every Project mutation during planning, but they exist only as unarchived change deltas; `openspec/specs/` has no baseline file for those capabilities. This change therefore defines a new `ai-local-project-work-start` capability rather than an unarchivable `MODIFIED` delta. Its requirements explicitly supersede the older no-mutation clauses for URL-targeted planning and extend the accepted pre-`Done` status while preserving existing verification gates. Reconcile those older pending deltas before any archive sequence so the resulting main specs are coherent.

## Goals / Non-Goals

**Goals:**

- Make one URL-targeted start transition conditional on a live, still-eligible item and confirm it before proposal generation or successful reuse reporting.
- Keep a retry safe when a previous invocation wrote `In Progress` but stopped before a valid proposal or link record existed.
- Preserve all completion-verification and final live-read gates before `Done`.

**Non-Goals:**

- Add an `--apply` CLI mode. Applying remains the separate manual `$openspec-apply-change` invocation.
- Change interactive selection, issue state, branch operations, or publish behavior.
- Roll back a confirmed `In Progress` status when later proposal generation fails; a retry can resume from it.

## Decisions

### Resolve the start option from existing Project configuration

Add an exact `inProgressOption` name beside `todoOption` and `doneOption` in validated configuration, then resolve its live single-select ID in `resolveProject`. Require all three names to be distinct and resolve exactly once. This keeps the configured Project and Status field as the sole mutation boundary. Hard-coded option IDs or a second Project configuration would become stale and could target the wrong item.

### Preserve one explicit issue identity across selection and mutation

Keep `fetchEligibleItems` for the interactive `Todo` list. For explicit URL selection, enumerate all configured-Project Issue items with their status metadata, match repository and issue number, and reject zero or multiple matches before considering status. Admit exact `Todo` and `In Progress` only, checking option ID as well as name. Before any write, use `fetchProjectItem` to re-read the selected item and verify the repository, issue ID/number, Project item ID, and current option. If it changed to any other status or linkage, stop without mutation or proposal generation. This avoids treating stale pagination data as authorization.

### Reuse the mutation transport with a start-specific guard

Extract or parameterize only the existing status mutation plus confirmation path so it accepts a validated target option. Keep `prepareStatusMutation` and the `ReadyStatusMutation` completion token exclusive to `--sync-task`; the planning path gets its own narrow guard for `Todo` to `In Progress`. A live `In Progress` match returns an idempotent no-write result after identity checks. A provider error, malformed mutation response, or failed confirmation becomes a typed, sanitized GitHub error with a retry instruction and stops before Codex or a new link write. The confirming read must match both option name and ID. No optimistic success is inferred from the mutation response alone.

### Place the write after eligibility and reuse decisions, before proposal work

Run preflight, lock acquisition, Project resolution, explicit selection, live issue/context checks, and linked-change conflict detection first. For a new proposal, confirm the start transition immediately before `runCodexPlanning`. For an existing link, ask whether to reuse first; cancellation leaves status unchanged, while accepted reuse confirms the transition before validation and success reporting. The interactive path bypasses the start transition. A confirmed status survives a later Codex or validation failure so a rerun can continue without duplicate mutation.

### Preserve `Done` verification and synchronize from both prior statuses

The final `--sync-task` guard still requires the typed passing verification result, unchanged fingerprints, live identity checks, and one confirming read after its single mutation. It accepts exact `Todo` for compatibility and exact `In Progress` for the new workflow; `Done` remains idempotent. Other statuses fail closed. The mutation helper still targets the configured `Done` option and never uses the planning guard to bypass completion verification.

### Update the bundled installer contract together with the repository runner

Mirror behavior, configuration validation, help, documentation, and mocked tests in `.agents/skills/bootstrap-ai-local/assets/template/`, plus its inspector and workflow contract where they list required status options. This prevents fresh installations from documenting or enforcing a different status lifecycle. No live GitHub call is part of automated verification.

## Risks / Trade-offs

- [Project status changes but proposal generation fails] → Keep `In Progress` as a visible retry state; repeated invocation performs an idempotent read and can regenerate or reuse only through existing link checks.
- [Item changes between enumeration and write] → Re-read the exact item and fail closed on status or linkage drift; confirm the post-write option before Codex.
- [GitHub mutation succeeds but the response or confirming read fails] → Report an uncertain, retryable status failure; the next run re-reads `In Progress` and avoids a second write.
- [An old synchronized item still starts at `Todo`] → Keep the previously valid `Todo` to `Done` path behind all existing verification gates.
- [Template and local runner diverge] → Extend parity tests and run the same mocked suites for both copies.

## Migration Plan

1. Add `inProgressOption` to the committed configuration and installer-generated configuration; validate exact distinct names and dynamic Project option resolution.
2. Update URL-targeted planning, status confirmation, and `--sync-task` guard behavior with mocked regressions; preserve interactive and manual apply behavior.
3. Update help, guide, bootstrap contract, and template parity. Run targeted Node tests, full `npm test`, `npm run check`, and strict OpenSpec validation before handoff.
4. Rollback restores the previous planning behavior in code, but any item already moved to `In Progress` remains in that Project state and requires an operator decision; no automatic reverse status write is performed.
5. Before archiving this change, reconcile or archive the older planning, explicit-selection, and synchronization deltas in an order that yields one coherent main specification; do not archive conflicting language unchanged.
