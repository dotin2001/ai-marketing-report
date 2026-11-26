## Context

See `proposal.md` and `specs/report-version-creation-and-history/spec.md`. The repository already has `ReportVersion` constraints and an owner/report keyset index, schema 1 and schema 2 snapshot parsers, `save_current_report_version` and `restore_saved_version`, repository create/get/list/restore functions, and PostgreSQL tests for numbering, immutability, and bindings. No public version route, version response model, or read service exists. The existing report API uses owner-aware dependencies, Pydantic envelopes, stable errors, and signed cursors.

## Goals / Non-Goals

**Goals:** Keep all authorization and lifecycle decisions in a version domain service; expose the already specified four version operations through thin routes; make public projections safe and schema aware; verify the end-to-end backend boundary against PostgreSQL.

**Non-Goals:** Render or queue PDFs, add a frontend history view, change the authentication provider, or change the version snapshot format. PDF summary fields may report an existing export or an explicit absence; this stage does not create one.

## Decisions

1. **Use the existing version transaction functions.** A `VersionServices` entry point will open transactions, authorize the report, validate the command, and call `save_current_report_version` or `restore_saved_version`. The version builder already assembles schema 2 snapshots from confirmed current state and checks reference compatibility. Extending it only for a verified contract defect avoids duplicating snapshot construction in routes. Alternative: build snapshots in API handlers; rejected because it would bypass the established owner and concurrency rules.
2. **Keep one public version contract.** Add strict create and restore request models and summary/detail envelopes with existing scalar serialization. Use the current active draft identity from the owner-scoped report, require `expected_draft_revision` for creation, and require both expected draft ID and revision for restore so a replay cannot target a newly active draft by accident. Use the server's fixed current report template version; do not accept an arbitrary client template string. The detail projection parses schema 1 or 2 before exposing approved snapshot fields and source metadata. Alternative: return raw JSONB; rejected because internal fields and future schema additions would escape review.
3. **Page by version number with an owner/report-bound signed cursor.** Query by owner and report, order by descending `version_number` and ID, fetch `limit + 1`, and sign cursor fields including route, owner, report, ordering, boundary, and expiry using the existing report cursor secret. Verify cursor scope and signature before querying. Alternative: offset paging; rejected because new versions would shift later pages.
4. **Preserve transaction-level idempotency and consistent HTTP behavior.** The existing idempotency record and version uniqueness constraints remain authoritative. The service returns whether a command replayed so routes can set `Idempotency-Replayed: true`; creation returns `201` and restore returns `200` as `project.md` specifies. Correct the restore idempotency success status if its stored `201` conflicts with that public response. Same-snapshot deduplication in the repository is preserved, including when a fresh key submits the same snapshot; it does not consume another number.
5. **Treat missing and foreign resources identically.** Resolve report and version through owner-scoped predicates before reads or mutations, map absence to `404`, stale draft or binding to `409 revision_conflict`, key reuse to `409 idempotency_conflict`, malformed cursors to `400 invalid_cursor`, and Pydantic failures to `422 validation_failed`. Do not echo private references or provider details. Alternative: surface repository exception text; rejected because it can disclose state and is not a stable API contract.

## Risks / Trade-offs

- [A schema 1 historical snapshot lacks schema 2 binding fields] → Parse by declared schema and expose absent fields without guessing identities.
- [The current repository `list_versions` reads the entire history] → Add a bounded owner-scoped keyset query before exposing pagination; verify page boundaries across a newly inserted version.
- [Concurrent requests can race on a draft or sequence] → Retain report row locking, uniqueness, and transactional idempotency; test with independent PostgreSQL sessions.
- [Restore may return a draft whose source references are no longer current] → Restore only editable saved content; ordinary current-input confirmation and analysis gates still apply to subsequent work.
- [Public snapshot projection can leak object storage references] → Use an allowlisted response schema, inspect nested source fields, and contract-test redaction.

## Migration Plan

1. Add API contracts, service wiring, and routes without a schema migration; the existing version tables and constraints support the operations.
2. Run focused schema, contract, and PostgreSQL tests, then the backend stage suite. Verify existing schema 1 and schema 2 reads and the migration upgrade suite if a constraint correction becomes necessary.
3. Roll back the API deployment if needed. Existing committed versions remain intact and readable by the prior persistence code; no destructive data rollback is planned.
