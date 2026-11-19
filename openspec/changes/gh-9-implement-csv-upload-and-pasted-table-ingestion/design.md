## Context

See `proposal.md` for motivation and `specs/source-ingestion/spec.md` for the intake contract. The backend already has `/api/v1/reports` management, owner-scoped `ReportSource`, `FileAsset`, and `IdempotencyRecord` tables, a report current-source pointer, and a storage coordinator that verifies immutable CSV objects. It has no public source intake or preview routes, and `backend/app/processing/` is empty. `SOURCE_CSV_MAX_BYTES` exists; text and record limits do not. The active import and API changes define later mapping and confirmation behavior, including acceptance of a header-only CSV for review.

## Goals / Non-Goals

**Goals:**

- Connect the existing report, database, and storage boundaries to one bounded source intake flow with stable replay identity and owner-safe reads.
- Ensure parser output is useful for preview and later mapping while never becoming a confirmed dataset on attachment.
- Keep all limits and safe error behavior explicit and testable.

**Non-Goals:**

- Implement import-configuration revisions, normalization, confirmation, deterministic KPIs, or user interface work.
- Interpret pasted table cells as canonical fields or as validated numeric claims.

## Decisions

### 1. Reuse source rows as intake records

`ReportSource` is the persisted import intake identity for both media types; CSV sources bind one `FileAsset`, while pasted text uses `inline_text`. No second intake table is needed because an `ImportConfiguration` represents a later reviewed mapping revision, not the initial source. The source service owns lifecycle and authorization; routes only validate shape, call the service, and serialize safe Pydantic views. This avoids duplicating provenance in a new table.

### 2. Validate once from a bounded, seekable input

For CSV, first enforce the existing 10 MiB default `SOURCE_CSV_MAX_BYTES` while copying the request stream into a spooled temporary file and computing SHA-256. Validate declared multipart media type and detected textual CSV envelope, decode strict UTF-8 with optional BOM, and parse with a deterministic comma delimiter and quoted-field rules. Reject invalid encoding, binary/NUL data, malformed quoting, a missing/empty header, and a count beyond `SOURCE_CSV_MAX_RECORDS` (default 100,000 data records). Accept duplicate header names by ordinal and header-only input for later `empty_dataset` validation. Detect CSV content by parseability and textual structure, not filename extension alone; normal CSV columns need not match canonical marketing names before mapping. Use the same parser on verified stored bytes for preview, bounded by `SOURCE_PREVIEW_MAX_ROWS` (default 50) and `SOURCE_PREVIEW_MAX_TEXT_CHARS` (default 2,000). Reject only structural faults at intake; field counts, data types, report-period validity, and mapping belong to later import validation. Limit individual preview cell length and total preview response size to avoid a single giant field defeating row bounds. Formula-like cells are emitted as inert strings and never evaluated; any future CSV export must escape them separately.

For text, validate a non-empty Unicode `content` request without trimming the stored value, calculate SHA-256 over its UTF-8 encoding, and enforce `SOURCE_TEXT_MAX_BYTES` (default 1 MiB). Use a bounded raw excerpt in previews, labeled as unvalidated. No delimiter inference or tabular-to-canonical conversion occurs in this stage. New settings and examples must document their limits and positive bounds.

### 3. Reserve replay identity before object I/O

Use the existing owner/operation/report-scoped idempotency row and canonical fingerprint. The fingerprint for CSV covers exact original bytes, declared media type, and untrusted filename as semantic metadata; for text it covers the exact Unicode content and optional display label. Validate the full bounded input before reserving. In a short transaction, insert or load the idempotency row and commit its pending identity. Derive a stable source UUID from that durable record ID for CSV storage keys. Then lock the row, recheck fingerprint and finalized result, write/verify the private object through the existing coordinator, and atomically bind source, asset, current report pointer, and finalized idempotency result in one transaction. Keep that lock across the bounded object operation so same-key calls converge; cap storage timeout and test contention. A crash after object write leaves a recoverable object at the stable key. On transaction failure, reconcile a possibly committed result, then compensate only an exact object created by this attempt. Text follows the same durable replay reservation and atomic source/current-pointer finalization without object I/O.

An alternative single transaction with a random source UUID would leave an object with an unknown retry key if the process crashed after storage success. A new job table for ingestion would add state that this synchronous, bounded workflow does not need.

### 4. Read previews from authorized, verified originals

Load the report/source by owner and parent ID before object access. CSV preview uses the storage service's verified retrieval, then parses the original into a bounded response with zero-based column ordinals, one-based record indexes, truncation/count metadata, and optional unconfirmed suggestions. Text preview slices for response only and never rewrites `inline_text`. Avoid returning object keys, provider metadata, or unrestricted original content. The API uses the established error envelope and records safe operation failures without logging source bytes or filenames.

### 5. Treat attachment as a source transition

Persist the new source and update the report's current-source reference in the same transaction, clearing current dataset, metric, and analysis references through the existing repository pattern. Historical source rows, datasets, and versions remain immutable. Any already queued analysis is stale under the changed source identity and cannot attach a result as current. Do not create `ImportConfiguration`, confirmed dataset, metric, or job rows during attachment.

## Risks / Trade-offs

- **[Database lock lasts through bounded object I/O]** → Limit bytes and provider timeout; use the existing uniqueness constraint for deterministic convergence and test simultaneous same-key submissions.
- **[Crash leaves an unbound private CSV object]** → Stable idempotency reservation and source key make the next equivalent request verify and reuse it; test recovery and safe exact-key compensation.
- **[CSV syntax differs between libraries]** → Pin explicit delimiter, quote, newline, BOM, header, and record-index behavior in parser tests; use the same parser for intake and preview. Later pandas normalization consumes this established envelope.
- **[Untrusted preview content can be rendered unsafely]** → Return JSON strings only, never executable markup or formulas, and keep response bounds; later frontend must render as text.

## Migration Plan

1. Add and document bounded text, record, and preview settings. Reuse current `ReportSource`, `FileAsset`, and idempotency schema; only add an Alembic migration if implementation reveals a database constraint needed for the stated guarantees.
2. Deploy parser/service/routes with existing report and storage dependencies. Existing reports need no backfill; previously stored sources remain readable under owner authorization.
3. Rollback removes the new routes and service wiring while retaining immutable accepted sources and private objects. Do not delete user originals during rollback.
