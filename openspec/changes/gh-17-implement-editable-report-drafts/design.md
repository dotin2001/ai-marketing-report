## Context

See `proposal.md` and `specs/editable-report-drafts/spec.md`. `ReportDraft` already has a revision and normalized child tables for objectives, narrative, limitations, claims, charts, and chart metric references. The current draft endpoint accepts only objectives. `save_draft_charts` exists in the repository layer but has no public route, and `DraftDetail` omits charts. Version snapshot code already checks chart metric membership and scope. The current analysis job captures the draft revision, so a later save can make an in-flight result stale.

## Goals / Non-Goals

**Goals:** Route all permitted draft edits through one owner-scoped domain command and one revision boundary; return a complete, safe draft projection; reuse the existing tables and chart contract; and make the API and database checks agree.

**Non-Goals:** A frontend editor, version creation or restoration, PDF rendering, free-form chart calculations, or changing generated AI result and metric records. Existing metadata editing remains on its current route.

## Decisions

1. **Extend the current draft route and response.** Replace the objectives-only request shape with a strict patch request containing `expected_revision` and optional collection fields. Distinguish omitted fields from explicit empty arrays so each supplied collection is replaced and each omitted collection is preserved. Reuse existing objective validation. The response and report detail gain ordered chart declarations. A separate route per section would create multiple revision boundaries for one editor save.
2. **Place the save transaction in the report domain service.** Authorize the report by owner before reference checks, lock the report and active draft, compare the expected revision, validate all supplied content and references, then replace only supplied child collections and advance the revision once. Any failure rolls back the entire save. Reuse repository helpers where they can participate without independently incrementing the revision; the existing `save_draft_charts` helper needs this integration or a shared lower-level chart write operation. Independent calls to the current objective and chart helpers would increment twice and risk partial saves.
3. **Use server-owned item identity and contiguous order.** Treat submitted arrays as the complete replacement for each supplied collection. Assign positive contiguous ordinals server-side and generate identifiers for new rows; preserve an existing item ID only when it belongs to the same active draft and represents the same retained item. Response IDs are for stable display and provenance, not authority to bind a foreign row. This avoids trusting client-supplied ordinals or cross-owner IDs.
4. **Validate trust boundaries before writing.** Pydantic accepts only known narrative sections and classifications, nonblank bounded text, claims labeled `user_claim`, and chart types `bar`, `line`, or `table`. Use existing `ChartSnapshot` constraints for presentation fields and cardinality. Domain checks require claim `source_id` to be an owner/report source, each chart metric to be in the current result set and compatible with the declared scope, and no chart when there is no current compatible metric set. Neither request schema accepts numeric values, original source data, AI metadata, or protected lifecycle fields. Avoid logging submitted content.
5. **Keep content edits separate from deterministic and historical state.** Narrative, claim, limitation, and chart edits do not mutate sources, metric results, analysis results, or version rows. Objective edits continue incrementing `objectives_revision` and invalidating current analysis when needed. Any effective draft edit advances the draft revision; the existing job completion freshness check rejects an older captured revision rather than overwriting editor content. A later version command can snapshot the saved draft through its own change.
6. **Use the existing safe API error family.** Stale revisions return `409 revision_conflict`; invalid fields or references return `422 validation_failed` with safe paths; foreign and missing reports are indistinguishable `404 resource_not_found`. Generated OpenAPI must match the runtime request and complete draft response. No customer content or reference lookup details enter error messages.

## Risks / Trade-offs

- [Replacing a collection can change item IDs] → Preserve IDs for retained owned items where possible and test order and read-after-save behavior; references remain server validated.
- [Chart references can become stale after a new dataset or metric set] → Check current result-set identity and scope at save time; the version command keeps its own snapshot-time compatibility check.
- [Concurrent saves can overwrite different fields] → Require one expected revision for the entire active draft and reject the loser without merging; the client can reload while retaining its local edits.
- [Existing helper methods each advance the revision] → Refactor their write internals into one transaction path and retain focused repository tests for direct helper behavior if they remain public internally.

## Migration Plan

1. Add API schemas, domain command, projection, and focused tests together. Existing objective-only calls keep the same route and payload shape and return the expanded draft response.
2. Existing draft tables appear sufficient. If implementation reveals a missing database invariant, add an Alembic migration, verify upgrade against PostgreSQL, and include a safe downgrade when lossless.
3. Deploy the API change without rewriting existing drafts. Old drafts read with empty chart and content collections where none were saved. A rollback must preserve the added rows; the previous API can ignore them while existing version code still validates them.
