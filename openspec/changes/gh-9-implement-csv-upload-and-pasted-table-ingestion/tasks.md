## 1. Input bounds and parsing

- [x] 1.1 Add validated `SOURCE_TEXT_MAX_BYTES`, `SOURCE_CSV_MAX_RECORDS`, and preview row/text/cell/response bounds in backend settings, example environment, and project documentation; verify configuration tests cover defaults, nonpositive values, and maximum bounds.
- [x] 1.2 Implement bounded CSV envelope parsing in `backend/app/processing/` using exact original bytes, UTF-8/BOM, comma and quote rules, header ordinals, and one-based data-record indexes; verify unit tests cover byte and record boundaries, duplicate headers, header-only data, quoted newlines, malformed syntax, unsupported encoding, NUL/binary content, and type mismatch.
- [x] 1.3 Implement bounded preview projection for parsed CSV and unchanged pasted text, including truncation and inert formula-like strings; verify unit tests prove row, cell, total-response, and text bounds without modifying original content.

## 2. Source domain and persistence

- [x] 2.1 Add source intake command and safe Pydantic source-detail/preview models that reject unknown fields and omit internal asset data; verify model tests cover Unicode, byte lengths, original-versus-display filename labeling, serialization, and redaction.
- [x] 2.2 Implement owner-scoped idempotency reservation and stable source identity using the existing PostgreSQL uniqueness and row locking, then finalize the source/current-pointer mutation atomically; verify isolated PostgreSQL tests cover equivalent replay, changed fingerprint conflict, concurrent same-key requests, and no duplicate source.
- [x] 2.3 Connect accepted CSV to bounded spooling and existing storage coordinator, preserving bytes/checksum and binding the existing `FileAsset`; verify deterministic storage-fake and PostgreSQL tests cover exact bytes, pre-commit failure, crash/retry convergence, verified reuse, and exact-object compensation.
- [x] 2.4 Persist unchanged pasted content in `ReportSource` without object I/O and apply source-transition invalidation for both media types; verify PostgreSQL tests cover owner association, prior current-source preservation on failure, new `source_review` stage, cleared current dataset/metric/analysis references, and intact history.
- [x] 2.5 Implement owner-scoped source detail and verified CSV/text preview reads, requiring parent/report consistency before storage access; verify tests cover foreign/missing `404`, corrupted object failure, duplicate-header ordinals, one-based record indexes, bounded excerpts, and no unrestricted original or object key.

## 3. HTTP contracts and wiring

- [x] 3.1 Add thin `POST /api/v1/reports/{report_id}/sources/csv` and `/text` routes with required `Idempotency-Key`, single-file multipart validation, safe error mapping, replay header, and `201` envelope; verify contract tests cover valid requests, empty/multiple files, limit/type/encoding/CSV faults, unauthorized access, replay, and conflict.
- [x] 3.2 Add owner-authorized `GET /api/v1/reports/{report_id}/sources/{source_id}` and `/preview` routes and wire services into application lifespan; verify runtime tests cover safe envelopes, bounded preview, source/report mismatch, and generated OpenAPI request, response, status, and error schemas.

## 4. Stage verification

- [x] 4.1 Run focused parser, storage-fake, API contract, and isolated PostgreSQL source tests; verify all pass and document exact commands and any unavailable database or storage gate in the implementation handoff.
- [x] 4.2 Run backend lint, strict type check, and the backend stage-level unit, contract, and PostgreSQL integration suites; if a schema change was required, verify Alembic upgrade and safe downgrade behavior and record the result.
- [x] 4.3 Run `openspec validate gh-9-implement-csv-upload-and-pasted-table-ingestion --strict --json`; verify zero issues and confirm the implementation meets every scenario in `specs/source-ingestion/spec.md` before handoff.
