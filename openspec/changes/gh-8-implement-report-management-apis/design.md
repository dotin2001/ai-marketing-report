## Context

See [proposal.md](proposal.md) for motivation and [spec.md](specs/report-management-apis/spec.md) for observable behavior. `Report`, `ReportDraft`, `DraftObjective`, and `IdempotencyRecord` already exist. Repository helpers create a report and draft, owner-scope a detail read, compare-and-set objective saves, and resolve idempotency. There are no report routes or full report response schemas. The current authentication dependency always raises `401`; tests can override it, but a production identity provider is not implemented here. The API error handler already supplies the standard outer envelope, while Pydantic validation still needs normalization into it. The active API contract defines report creation/list/detail and draft PATCH but has no metadata PATCH; this design adds that route explicitly.

## Goals / Non-Goals

**Goals:**

- Keep route functions limited to principal resolution, strict request parsing, domain calls, and response serialization.
- Make report creation and metadata/objective mutation transactional and owner-scoped, with stable errors under concurrency.
- Reuse existing database constraints and repository idempotency rather than introduce an independent store.
- Expose a shallow list view and a safe detail view with a derived stage.

**Non-Goals:**

- Implement a production authentication provider or the other draft narrative fields.
- Process imports, launch analysis, render PDFs, or edit immutable versions.
- Add arbitrary filtering/sorting or offset/total-count pagination.

## Decisions

### Report and objective write boundaries

Add a report domain service that owns create, metadata update, objective update, list, and detail behavior. It calls narrowly scoped repository operations in a single PostgreSQL transaction. The existing `create_report` and `save_draft_objectives` helpers are reused or tightened. Requests and responses use distinct Pydantic v1 models with `extra='forbid'`; name/objective normalization and period validation run before mutation, and repository/database constraints remain the last line of defense. This is preferable to placing lifecycle rules in FastAPI routes or returning ORM instances directly.

Treat `PATCH /reports/{id}` as the issue's metadata update route, with a complete period object when changing dates and `expected_revision` on every request. The active draft revision is the shared compare-and-set token for metadata and objectives; a successful effective update increments it once. This avoids introducing a second mutable revision that could drift. A no-op normalized update returns current detail without incrementing revision, so repeated requests with a now-stale revision need explicit handling: resolve the exact no-op against the observed current revision only, otherwise return `revision_conflict`. Objectives continue through the existing draft path. `name` does not participate in analysis freshness; objectives and period do. The alternative of adding report fields to draft PATCH would blur the report/draft boundary and silently change its already-defined request schema.

### Period invalidation and historical reads

Lock the owned report and active draft in one transaction, compare the revision, then update the period. On an effective period change, retain `current_source_id` but clear or mark non-current the report's dataset, metric, and analysis pointers, and make previous confirmation non-current by comparing its captured period/source revision to the report's current period. Derive `source_review` when a source exists and `created` otherwise. Do not delete canonical datasets, jobs, or versions. This follows the lifecycle rule that a period edit requires revalidation and explicit confirmation; clearing historical rows would violate immutable snapshots. A name change only updates metadata and the revision; its semantic analysis input stays current.

### Idempotent creation and owner-safe lookup

Validate the key format at the transport boundary. Use the existing idempotency record with operation `create-report`, principal scope, and a stable root scope ID for a report with no parent; fingerprint canonical normalized name, dates, and ordered objectives. Insert the report, active draft, objectives, and finalized idempotency result in one transaction. Re-read an existing result through the same owner filter before returning replay. Any existing-key/different-command result maps to `idempotency_conflict`. For GET/PATCH, resolve the report by owner before calculating revision or lifecycle errors. Database uniqueness is the concurrency arbiter; no process-local locks.

### Pagination and response shape

Query owner-scoped reports by `(created_at DESC, id DESC)` with `limit + 1`, then encode the last returned tuple in a versioned, authenticated cursor that binds principal, route, fixed ordering, and expiry. Use HMAC with a dedicated configured secret, constant-time signature comparison, canonical encoding, and a safe `invalid_cursor` error for malformed, expired, or mismatched payloads. Add the required secret name and safe local setup guidance to the example environment/project documentation; never log the secret or cursor payload. A single-route implementation can remain in the report module; extract a shared cursor helper only when another real collection consumes it. Offset queries are simpler but violate the existing keyset contract under concurrent inserts.

Build summary/detail response models from owner-authorized state. Determine stage from source confirmation/current metric/analysis/version facts rather than a writable stage column. Keep private object keys, original source content, and provider data out of both views. The API handler should map request validation errors into the existing safe error shape with deterministic field paths, and generated OpenAPI must use the same runtime models, including the new metadata PATCH and error responses.

## Risks / Trade-offs

- [The database may have no dedicated report-level revision] → Use the active draft revision as the common mutation boundary and test concurrent metadata/objective writes against PostgreSQL.
- [A period edit can leave an older confirmation row visible] → Gate all current-reference derivation on the new period and clear current derived pointers transactionally; keep historical rows addressable only through historical resources.
- [A metadata rename advances draft revision while analysis captures draft revision] → Define semantic freshness over relevant objective/content identity, not the revision counter alone, and test that rename preserves valid analysis eligibility.
- [The principal dependency is a `401` stub] → Verify authorized paths with a test override and document that production auth integration is a deployment prerequisite.
- [Cursor signing adds a required secret] → Validate configuration at startup, provide a safe example name, rotate with an explicit expiry window, and return only `invalid_cursor` to clients on verification failure.

## Migration Plan

Implement against the existing schema first. If a constraint or column proves necessary, add an Alembic migration with upgrade verification and safe downgrade where lossless. Roll out configuration for cursor signing before enabling report listing. Existing reports remain readable; no backfill or historical snapshot rewrite is planned. Rolling back the API removes these new routes while retaining already-created reports and drafts.
