## Context

See `proposal.md` for motivation and `specs/ai-local-interactive-work-start/spec.md` for behavior. `scripts/ai-local/workflow.mjs` uses a numbered selector over exact `Todo` items for interactive planning. It already calls `startProjectWork` for the URL path after issue and linked-change checks. That helper re-reads the Project item, verifies linkage and status, writes the configured `In Progress` option, and confirms the resulting name and ID. The bootstrap template mirrors the runner and tests enforce byte parity for shared modules. Earlier change deltas explicitly left interactive status unchanged, so archive reconciliation is required.

## Goals / Non-Goals

**Goals:** Use the same guarded start transition for numbered and URL selection, keep all selected-item identity checks, and show the confirmed status accurately on success.

**Non-Goals:** Expand the numbered list beyond `Todo`, reverse a confirmed status after later proposal failure, change issue state, or change `--sync-task` completion policy.

## Decisions

1. **Call the existing start guard after selection and linked-change decisions for both paths.** Remove the URL-only branch around `startProjectWork` in the new-proposal and accepted-reuse paths. Apply the existing selected-item link check to both paths before the write. This keeps one mutation implementation and prevents the interactive path from bypassing the live identity, exact option-ID, or post-write checks. A separate interactive mutation would duplicate security logic.
2. **Keep cancellation and declined reuse before the write.** A cancelled selector exits before issue loading. A declined linked-change reuse exits after link resolution and before start. For a new proposal, start immediately before Codex proposal generation; for accepted reuse, start before validation. This matches the existing URL path's retry boundary.
3. **Keep the numbered list restricted to `Todo`.** A proposal failure after a confirmed start removes the item from that list. Document the existing canonical `--issue` URL command as the retry path; it accepts exact `In Progress` and does not write status twice. Adding all `In Progress` items to the numbered list would broaden selection and eligibility beyond this request.
4. **Update the runner and bootstrap bundle together.** Mirror the workflow change in the template, update CLI/help and user guides, and add mocked interactive success, cancellation, reuse, status-failure, stale-item, and retry evidence. Keep tests isolated from live GitHub.

## Risks / Trade-offs

- [Proposal fails after status is confirmed] → Preserve `In Progress`, report failure, and document URL-targeted retry without a duplicate mutation.
- [Project item changes after the numbered list is shown] → Use the existing live item and issue identity checks immediately before mutation; fail closed on drift.
- [GitHub writes but confirmation fails] → Return the existing sanitized retry error; a later URL retry re-reads the current status.
- [Older deltas still say interactive planning does not write status] → Reconcile or archive those deltas coherently before this change is archived; do not silently leave contradictory main specs.

## Migration Plan

1. Update the runner and mirrored template to start both selected paths through the existing guarded helper.
2. Update mocked tests and operator guidance; run the focused planning/status tests, `npm test`, `npm run check`, and strict OpenSpec validation. No live GitHub status write is part of automated verification.
3. If rolled back, restore the previous interactive planning behavior in code. Project items already confirmed as `In Progress` remain there for operator review; no reverse mutation is performed.
